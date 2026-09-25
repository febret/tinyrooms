"""Account serialization shared by the game server and mission control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.profiles import AccountRecord
from server.services.stickers import decode_design


if TYPE_CHECKING:
    from server.app import RuntimeState


def serialize_account(runtime: RuntimeState, account: AccountRecord) -> dict[str, object]:
    """Build the full client-facing user payload for *account*."""

    user_profile = runtime.profiles.user_profile_for(account.id, runtime.world.id, runtime.world.entry_room_id)
    activity = runtime.activities.get(account.id)
    if not account.initial_sticker_complete:
        activity = runtime.activities.ensure_initial_sticker(account.id)
    snapshot = runtime.stats.view(account.id)
    level_definition = runtime.content.levels.get(account.level)
    skills = runtime.progression.skill_slots(account, user_profile)
    friends = runtime.friends.serialize(account.id)
    return {
        "id": account.id,
        "username": account.username_display,
        "sticker": account.sticker,
        "sticker_design": decode_design(account.sticker_design),
        "initial_sticker_complete": account.initial_sticker_complete,
        "owned_rooms": list(user_profile.owned_rooms),
        "unlocked_props": sorted(runtime.prop_shop.unlocked(account.id)),
        "level": account.level,
        "level_label": level_definition.label,
        "kudos": account.kudos,
        "kudos_to_next": level_definition.kudos_to_next,
        "max_equipped": level_definition.max_equipped,
        "bops": account.bops,
        "sticker_swap_cost": runtime.content.bops.sticker_swap_cost,
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
        "packs": [preview.as_dict() for preview in runtime.shop.packs()],
        "show_activity_log": user_profile.show_activity_log,
        "world_id": runtime.world.id,
        "remembered_room": user_profile.remembered_room,
        "inventory": runtime.cards.list_inventory_payload(account.id),
        "core_cards": runtime.cards.serialize_core_cards(),
        "activity": runtime.activities.serialize(activity),
        "tasks": runtime.tasks.view_payload(account.id),
        "journal": runtime.memories.journal_payload(account.id),
        "powers": sorted(runtime.powers.effective(account)),
    }
