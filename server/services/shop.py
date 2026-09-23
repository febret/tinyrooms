"""Card pack draws, idempotent purchases, and sticker swapping."""

from __future__ import annotations

from dataclasses import dataclass
import json
import random

from server.content.cards import CardCatalog, CardDefinition, PackDefinition
from server.content.gameplay import GameplayContent
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.security import utc_now
from server.services.cards import grant_card_to_inventory
from server.state.migrations import DatabaseHub

DEFAULT_RARITY_DRAW_WEIGHTS = {
    "Common": 70.0,
    "Uncommon": 20.0,
    "Rare": 8.0,
    "Epic": 1.8,
    "Legendary": 0.2,
}


@dataclass(frozen=True, slots=True)
class PackPreview:
    """The pre-purchase shop view of a pack."""

    id: str
    label: str
    description: str
    price: int
    size: int
    back_image_url: str

    def as_dict(self) -> dict[str, object]:
        """Serialize the preview for the client."""

        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "price": self.price,
            "size": self.size,
            "back_image_url": self.back_image_url,
        }


@dataclass(frozen=True, slots=True)
class PurchaseResult:
    """Outcome of a pack purchase (or an idempotent replay)."""

    pack: PackDefinition
    cards: tuple[CardDefinition, ...]
    stacks: tuple[InventoryStack, ...]
    bops_spent: int
    account: AccountRecord
    replayed: bool


class ShopService:
    """Owns rarity draws and exactly-once pack purchases."""

    def __init__(
        self,
        hub: DatabaseHub,
        profiles: ProfileRepository,
        catalog: CardCatalog,
        content: GameplayContent,
        world_id: str,
        rng: random.Random | None = None,
    ) -> None:
        self._hub = hub
        self._profiles = profiles
        self._catalog = catalog
        self._content = content
        self._world_id = world_id
        self._rng = rng

    def _random(self) -> random.Random:
        return self._rng if self._rng is not None else random

    def packs(self) -> list[PackPreview]:
        """Return purchasable pack previews, showing only price and card count."""

        previews: list[PackPreview] = []
        for pack in self._catalog.packs.values():
            asset_kind = "base" if pack.source != self._world_id else f"world/{self._world_id}/cards"
            previews.append(
                PackPreview(
                    id=pack.id,
                    label=pack.label,
                    description=pack.description,
                    price=pack.price,
                    size=pack.size,
                    back_image_url=f"/assets/{asset_kind}/{pack.back_image_name}",
                )
            )
        return sorted(previews, key=lambda preview: preview.id)

    def _effective_rarity(self, definition: CardDefinition) -> str:
        return definition.rarity or "Common"

    def _pick_rarity(self, pack: PackDefinition, rng: random.Random) -> str:
        present = {self._effective_rarity(self._catalog.cards[card_id]) for card_id in pack.cards}
        candidates = [
            rarity for rarity in sorted(present) if DEFAULT_RARITY_DRAW_WEIGHTS.get(rarity, 0.0) > 0
        ]
        if not candidates:
            return sorted(present)[0]
        weights = [DEFAULT_RARITY_DRAW_WEIGHTS[rarity] for rarity in candidates]
        return rng.choices(candidates, weights=weights, k=1)[0]

    def draw(self, pack: PackDefinition, rng: random.Random | None = None) -> list[CardDefinition]:
        """Draw one pack's independent card results."""

        generator = rng or self._random()
        results: list[CardDefinition] = []
        for _ in range(pack.size):
            rarity = self._pick_rarity(pack, generator)
            pool = [
                self._catalog.cards[card_id]
                for card_id in pack.cards
                if self._effective_rarity(self._catalog.cards[card_id]) == rarity
            ]
            if not pool:
                pool = [self._catalog.cards[card_id] for card_id in pack.cards]
            results.append(generator.choice(pool))
        return results

    def purchase(self, account: AccountRecord, pack_id: str, operation_id: str) -> PurchaseResult:
        """Charge Bops and grant results exactly once per operation id."""

        pack = self._catalog.packs.get(pack_id)
        if pack is None:
            raise ValueError("Unknown card pack.")
        operation_id = (operation_id or "").strip()
        if not operation_id or len(operation_id) > 80:
            raise ValueError("A valid purchase operation id is required.")
        with self._hub.transaction() as connection:
            existing = connection.execute(
                "SELECT pack_id, results_json FROM pack_purchases WHERE operation_id = ? AND account_id = ?",
                (operation_id, account.id),
            ).fetchone()
            if existing is not None:
                card_ids = [str(entry) for entry in json.loads(existing["results_json"])]
                cards = tuple(self._catalog.cards[card_id] for card_id in card_ids)
                current = self._profiles.get_account_by_id(account.id)
                if current is None:
                    raise ValueError("Unknown account.")
                return PurchaseResult(
                    pack=self._catalog.packs[str(existing["pack_id"])],
                    cards=cards,
                    stacks=tuple(self._profiles.list_inventory(account.id, self._world_id)),
                    bops_spent=0,
                    account=current,
                    replayed=True,
                )
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            if current.bops < pack.price:
                raise ValueError(f"You need {pack.price - current.bops} more Bops for that pack.")
            draws = self.draw(pack, self._rng)
            granted: list[InventoryStack] = []
            for definition in draws:
                granted.extend(
                    grant_card_to_inventory(
                        self._profiles,
                        connection,
                        account_id=account.id,
                        definition=definition,
                        world_id=self._world_id,
                    )
                )
            updated = self._profiles.update_progress(
                connection,
                current,
                bops=current.bops - pack.price,
            )
            connection.execute(
                """
                INSERT INTO pack_purchases (operation_id, account_id, pack_id, results_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    account.id,
                    pack.id,
                    json.dumps([definition.id for definition in draws]),
                    utc_now().isoformat(),
                ),
            )
            return PurchaseResult(
                pack=pack,
                cards=tuple(draws),
                stacks=tuple(self._profiles.list_inventory(account.id, self._world_id)),
                bops_spent=pack.price,
                account=updated,
                replayed=False,
            )

    def swap_sticker(self, account: AccountRecord, sticker_name: str, valid_stickers: set[str]) -> AccountRecord:
        """Charge for and persist a sticker swap, free when unchanged."""

        if sticker_name not in valid_stickers:
            raise ValueError("That sticker does not exist.")
        cost = self._content.bops.sticker_swap_cost
        with self._hub.transaction() as connection:
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            if current.sticker == sticker_name:
                return current
            if current.bops < cost:
                raise ValueError(f"You need {cost - current.bops} more Bops to swap your sticker.")
            connection.execute(
                "UPDATE accounts SET sticker = ?, updated_at = ? WHERE id = ?",
                (sticker_name, utc_now().isoformat(), account.id),
            )
            updated = self._profiles.update_progress(
                connection,
                current,
                bops=current.bops - cost,
            )
        return updated
