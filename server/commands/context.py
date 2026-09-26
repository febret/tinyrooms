"""Factory for building a command context from runtime state."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from server.commands.outcomes import CommandContext
from server.profiles import AccountRecord


if TYPE_CHECKING:
    from server.app import RuntimeState


def build_command_context(
    runtime: RuntimeState,
    *,
    account: AccountRecord,
    connection: object,
    serialize_user: Callable[[AccountRecord], dict[str, object]],
) -> CommandContext:
    """Build a fully-populated command context for *account*.

    The connection may be a live socket or a synthetic stand-in used by
    out-of-band dispatch (mission control); handlers read ``room_id`` and
    ``account_id``/``username``/``generation`` from it.
    """

    return CommandContext(
        account=account,
        connection=connection,
        profiles=runtime.profiles,
        world_state=runtime.world_state,
        rooms=runtime.rooms,
        cards=runtime.cards,
        activities=runtime.activities,
        activity_results=runtime.activity_results,
        registry=runtime.registry,
        stats=runtime.stats,
        inventory=runtime.inventory,
        progression=runtime.progression,
        actions=runtime.actions,
        friends=runtime.friends,
        shop=runtime.shop,
        prop_shop=runtime.prop_shop,
        pricing=runtime.pricing,
        content=runtime.content,
        world=runtime.world,
        valid_stickers=frozenset(runtime.accounts.list_stickers()),
        serialize_user=serialize_user,
        behaviors=runtime.behaviors,
        dialogs=runtime.dialogs,
        tasks=runtime.tasks,
        memories=runtime.memories,
        powers=runtime.powers,
        ownership=runtime.ownership,
        environment=runtime.environment,
        audit=runtime.audit,
        connections=runtime.connections,
        mods=runtime.mods,
        dispensers=runtime.dispensers,
        crafting=runtime.crafting,
        recipes=runtime.world.recipes,
        reload_world=runtime.reload_world,
    )
