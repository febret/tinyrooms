"""Card pack draws, idempotent purchases, and sticker swapping."""

from __future__ import annotations

from dataclasses import dataclass
import json
import random

from server.content.cards import (
    PACK_CARD_TYPE,
    CardCatalog,
    CardDefinition,
    PackDefinition,
    closed_pack_card_id,
)
from server.content.gameplay import GameplayContent
from server.profiles import AccountRecord, InventoryStack, ProfileRepository
from server.security import utc_now
from server.services.cards import grant_card_to_inventory
from server.services.stickers import sticker_identity
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
    """Outcome of a sealed-pack purchase (or an idempotent replay)."""

    pack: PackDefinition
    pack_card: CardDefinition
    stacks: tuple[InventoryStack, ...]
    bops_spent: int
    account: AccountRecord
    replayed: bool


@dataclass(frozen=True, slots=True)
class OpenResult:
    """Outcome of opening a sealed pack (or an idempotent replay)."""

    pack: PackDefinition
    cards: tuple[CardDefinition, ...]
    stacks: tuple[InventoryStack, ...]
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
            asset_kind = pack.source if pack.source != self._world_id else f"world/{self._world_id}/cards"
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

    def _apply_guaranteed(
        self,
        pack: PackDefinition,
        draws: list[CardDefinition],
        owned_ids: set[str],
    ) -> None:
        """Force each guaranteed card into a draw while the opener owns none of it."""

        if not pack.guaranteed:
            return
        guaranteed = set(pack.guaranteed)
        present = {definition.id for definition in draws}
        for card_id in pack.guaranteed:
            if card_id in owned_ids or card_id in present:
                continue
            index = next(
                (position for position in range(len(draws) - 1, -1, -1) if draws[position].id not in guaranteed),
                0,
            )
            draws[index] = self._catalog.cards[card_id]
            present.add(card_id)

    def sealed_definition(self, pack_id: str) -> CardDefinition | None:
        """Return the sealed inventory card that represents *pack_id*."""

        pack = self._catalog.packs.get(pack_id)
        if pack is None:
            return None
        definition = self._catalog.cards.get(closed_pack_card_id(pack.id))
        if definition is None or definition.opens_pack != pack.id:
            return None
        return definition

    def openable_definition(self, card_def_id: str) -> CardDefinition | None:
        """Return the sealed definition named by *card_def_id*, if it opens a pack."""

        definition = self._catalog.cards.get(card_def_id)
        if definition is None or definition.type != PACK_CARD_TYPE or not definition.opens_pack:
            return None
        return definition

    def purchase(self, account: AccountRecord, pack_id: str, operation_id: str) -> PurchaseResult:
        """Charge Bops and grant one sealed pack exactly once per operation id."""

        pack = self._catalog.packs.get(pack_id)
        if pack is None:
            raise ValueError("Unknown card pack.")
        pack_card = self.sealed_definition(pack.id)
        if pack_card is None:
            raise ValueError("Unknown card pack.")
        operation_id = (operation_id or "").strip()
        if not operation_id or len(operation_id) > 80:
            raise ValueError("A valid purchase operation id is required.")
        with self._hub.transaction() as connection:
            existing = connection.execute(
                "SELECT pack_id FROM pack_purchases WHERE operation_id = ? AND account_id = ?",
                (operation_id, account.id),
            ).fetchone()
            if existing is not None:
                replayed_pack = self._catalog.packs[str(existing["pack_id"])]
                current = self._profiles.get_account_by_id(account.id)
                if current is None:
                    raise ValueError("Unknown account.")
                return PurchaseResult(
                    pack=replayed_pack,
                    pack_card=self.sealed_definition(replayed_pack.id) or pack_card,
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
            grant_card_to_inventory(
                self._profiles,
                connection,
                account_id=account.id,
                definition=pack_card,
                world_id=self._world_id,
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
                    json.dumps([]),
                    utc_now().isoformat(),
                ),
            )
            return PurchaseResult(
                pack=pack,
                pack_card=pack_card,
                stacks=tuple(self._profiles.list_inventory(account.id, self._world_id)),
                bops_spent=pack.price,
                account=updated,
                replayed=False,
            )

    def open_pack(self, account: AccountRecord, stack_id: str, operation_id: str) -> OpenResult:
        """Consume one sealed pack stack and grant its drawn cards exactly once."""

        operation_id = (operation_id or "").strip()
        if not operation_id or len(operation_id) > 80:
            raise ValueError("A valid open operation id is required.")
        with self._hub.transaction() as connection:
            existing = connection.execute(
                "SELECT pack_id, results_json FROM pack_opens WHERE operation_id = ? AND account_id = ?",
                (operation_id, account.id),
            ).fetchone()
            if existing is not None:
                card_ids = [str(entry) for entry in json.loads(existing["results_json"])]
                cards = tuple(self._catalog.cards[card_id] for card_id in card_ids)
                current = self._profiles.get_account_by_id(account.id)
                if current is None:
                    raise ValueError("Unknown account.")
                return OpenResult(
                    pack=self._catalog.packs[str(existing["pack_id"])],
                    cards=cards,
                    stacks=tuple(self._profiles.list_inventory(account.id, self._world_id)),
                    account=current,
                    replayed=True,
                )
            stack = self._profiles.get_inventory_stack(account.id, self._world_id, stack_id)
            if stack is None:
                raise ValueError("You do not have that pack in your inventory.")
            sealed = self.openable_definition(stack.card_def_id)
            if sealed is None or sealed.opens_pack is None:
                raise ValueError("That is not a sealed card pack.")
            pack = self._catalog.packs.get(sealed.opens_pack)
            if pack is None:
                raise ValueError("Unknown card pack.")
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            draws = self.draw(pack, self._rng)
            owned_ids = {
                entry.card_def_id
                for entry in self._profiles.list_inventory(current.id, self._world_id)
            }
            self._apply_guaranteed(pack, draws, owned_ids)
            self._profiles.remove_inventory_quantity(
                connection,
                account_id=current.id,
                world_id=self._world_id,
                stack_id=stack.stack_id,
                quantity=1,
            )
            for definition in draws:
                grant_card_to_inventory(
                    self._profiles,
                    connection,
                    account_id=account.id,
                    definition=definition,
                    world_id=self._world_id,
                )
            connection.execute(
                """
                INSERT INTO pack_opens (operation_id, account_id, pack_id, results_json, created_at)
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
            return OpenResult(
                pack=pack,
                cards=tuple(draws),
                stacks=tuple(self._profiles.list_inventory(account.id, self._world_id)),
                account=current,
                replayed=False,
            )

    def swap_sticker(
        self,
        account: AccountRecord,
        sticker_name: str,
        valid_stickers: set[str],
        *,
        sticker_design: str | None = None,
    ) -> AccountRecord:
        """Charge for and persist a sticker swap, free when unchanged.

        A custom render passes its canonical design string; its ``sticker_name``
        is server-derived and therefore exempt from the preset whitelist.
        """

        if sticker_design is None and sticker_name not in valid_stickers:
            raise ValueError("That sticker does not exist.")
        cost = self._content.bops.sticker_swap_cost
        target_identity = sticker_identity(sticker_name, sticker_design)
        with self._hub.transaction() as connection:
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            if sticker_identity(current.sticker, current.sticker_design) == target_identity:
                return current
            if current.bops < cost:
                raise ValueError(f"You need {cost - current.bops} more Bops to swap your sticker.")
            connection.execute(
                "UPDATE accounts SET sticker = ?, sticker_design = ?, updated_at = ? WHERE id = ?",
                (sticker_name, sticker_design, utc_now().isoformat(), account.id),
            )
            updated = self._profiles.update_progress(
                connection,
                current,
                bops=current.bops - cost,
            )
        return updated
