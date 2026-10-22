"""Account serialization shared by the game server and mission control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.profiles import AccountRecord
from server.services.stickers import decode_design


if TYPE_CHECKING:
    from server.app import RuntimeState


def serialize_account(runtime: RuntimeState, account: AccountRecord) -> dict[str, object]:
    """Build the full client-facing user payload for *account*."""

    user_profile = runtime.profiles.get_user_profile(account.id) if runtime.config.mc_instance_id else None
    if user_profile is None:
        user_profile = runtime.profiles.user_profile_for(account.id, runtime.world.id, runtime.world.entry_room_id)
    activity = runtime.activities.get(account.id)
    if not account.initial_sticker_complete:
        activity = runtime.activities.ensure_initial_sticker(account.id)
    snapshot = runtime.stats.view(account.id)
    level_definition = runtime.content.levels.get(account.level)
    skills = runtime.progression.skill_slots(account, user_profile)
    friends = runtime.friends.serialize(account.id)
    beacons = runtime.beacons.serialize(account.id, runtime.world.id)
    return {
        "id": account.id,
        "username": account.username_display,
        "sticker": account.sticker,
        # Editable custom-sticker recipe, or null for a preset/absent design.
        "sticker_design": decode_design(account.sticker_design),
        # Persistent onboarding gate: world entry requires first sticker confirmation.
        "initial_sticker_complete": account.initial_sticker_complete,
        # Ownership comes from the account-wide user profile, not room presence.
        "owned_rooms": list(user_profile.owned_rooms),
        "unlocked_props": sorted(runtime.prop_shop.unlocked(account.id)),
        "level": account.level,
        "level_label": level_definition.label,
        "kudos": account.kudos,
        "kudos_to_next": level_definition.kudos_to_next,
        "max_equipped": level_definition.max_equipped,
        "bops": account.bops,
        "sticker_swap_cost": runtime.content.bops.sticker_swap_cost,
        # Current authoritative energy from the stats view, not the raw account row.
        "shared_energy": snapshot.energy,
        "counters": snapshot.payload(),
        "stats": snapshot.effective.stats,
        "statuses": list(snapshot.statuses),
        "status_definitions": {
            status_id: {
                "label": definition.label,
                "description": definition.description,
                "icon": definition.icon,
            }
            for status_id, definition in runtime.content.statuses.items()
        },
        "skills": [
            {"index": slot.index, "rank": slot.rank, "unlocked": slot.unlocked, "stack_id": slot.stack_id}
            for slot in skills
        ],
        "pinned_peeps": list(user_profile.pinned_peeps),
        "friends": friends.as_dict(),
        "beacons": beacons,
        "starred_tracks": runtime.chiptune_stars.starred(account.id),
        "packs": [preview.as_dict() for preview in runtime.shop.packs()],
        # Persisted user-profile preference for displaying the action log.
        "show_activity_log": user_profile.show_activity_log,
        # This payload's loaded world; remembered_room is nullable saved navigation
        # context from the profile, not proof of a live connection in that room.
        "world_id": runtime.world.id,
        "remembered_room": user_profile.remembered_room,
        "inventory": runtime.cards.list_inventory_payload(account.id),
        # Non-transferable navigation/view card definitions in cards.yaml order,
        # separate from owned inventory stacks (Room, Emotes, Inventory, etc.).
        "core_cards": runtime.cards.serialize_core_cards(),
        # Current in-memory activity or null; incomplete onboarding ensures a designer.
        "activity": runtime.activities.serialize(activity),
        "tasks": runtime.tasks.view_payload(account.id),
        "journal": runtime.memories.journal_payload(account.id),
        "powers": sorted(runtime.powers.effective(account)),
    }
