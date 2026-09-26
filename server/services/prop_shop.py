"""Prop marketplace: per-account prop unlocks bought with Bops."""

from __future__ import annotations

from dataclasses import dataclass

from server.content.worlds import PropDefinition, WorldDefinition, prop_model_url
from server.profiles import AccountRecord, ProfileRepository
from server.state.migrations import DatabaseHub


def serialize_prop_entry(
    world: WorldDefinition,
    definition: PropDefinition,
    *,
    locked: bool | None = None,
) -> dict[str, object]:
    """Serialize one prop definition for the editor library or the prop shop."""

    return {
        "prop_id": definition.id,
        "label": definition.label,
        "description": definition.description,
        "model_url": prop_model_url(world.id, definition),
        "base_scale": definition.scale,
        "scale_min": definition.editor_scale_min,
        "scale_max": definition.editor_scale_max,
        "source": definition.source,
        "tags": list(definition.tags),
        "price": definition.price,
        "locked": definition.locked if locked is None else locked,
        "effect_sets": {
            set_name: [
                world.effects[effect_id].serialize()
                for effect_id in effect_ids
                if effect_id in world.effects
            ]
            for set_name, effect_ids in definition.effect_sets.items()
        },
        "active_effect": definition.active_effect,
    }


@dataclass(frozen=True, slots=True)
class PropUnlockResult:
    """Outcome of a prop unlock purchase (or an idempotent replay)."""

    definition: PropDefinition
    bops_spent: int
    account: AccountRecord
    replayed: bool


class PropShopService:
    """Owns the purchasable prop catalog and exactly-once unlock purchases."""

    def __init__(self, hub: DatabaseHub, profiles: ProfileRepository, world: WorldDefinition) -> None:
        self._hub = hub
        self._profiles = profiles
        self._world = world

    def catalog(self) -> list[PropDefinition]:
        """Return every editable propset prop offered in the marketplace."""

        definitions = [
            definition
            for definition in self._world.props.values()
            if definition.source_kind == "propset" and definition.editable
        ]
        return sorted(definitions, key=lambda definition: (definition.source, definition.id))

    def unlocked(self, account_id: str) -> set[str]:
        """Return the prop ids this account has purchased."""

        profile = self._profiles.get_user_profile(account_id)
        if profile is None:
            return set()
        return set(profile.unlocked_props)

    def is_locked(self, definition: PropDefinition, unlocked: set[str]) -> bool:
        """Return whether *definition* is still locked for an owner with *unlocked*."""

        return definition.locked and definition.id not in unlocked

    def _for_sale(self, prop_id: str) -> PropDefinition:
        definition = self._world.props.get(prop_id)
        if definition is None or definition.source_kind != "propset" or not definition.editable:
            raise ValueError("That prop is not sold here.")
        return definition

    def purchase(self, account: AccountRecord, prop_id: str) -> PropUnlockResult:
        """Charge Bops to permanently unlock a prop for *account*."""

        definition = self._for_sale(prop_id)
        with self._hub.transaction() as connection:
            current = self._profiles.get_account_by_id(account.id)
            if current is None:
                raise ValueError("Unknown account.")
            profile = self._profiles.get_user_profile(account.id)
            owned = set(profile.unlocked_props) if profile is not None else set()
            if not definition.locked or definition.id in owned:
                return PropUnlockResult(definition=definition, bops_spent=0, account=current, replayed=True)
            if current.bops < definition.price:
                raise ValueError(
                    f"You need {definition.price - current.bops} more Bops for {definition.label}."
                )
            updated = self._profiles.update_progress(
                connection,
                current,
                bops=current.bops - definition.price,
            )
            self._profiles.update_profile_in_transaction(
                connection,
                account.id,
                lambda profile_json: _add_unlock(profile_json, definition.id),
            )
        return PropUnlockResult(
            definition=definition,
            bops_spent=definition.price,
            account=updated,
            replayed=False,
        )


def _add_unlock(profile: dict[str, object], prop_id: str) -> None:
    raw = profile.get("unlocked_props")
    owned = [str(entry) for entry in raw] if isinstance(raw, list) else []
    if prop_id not in owned:
        owned.append(prop_id)
    profile["unlocked_props"] = owned
