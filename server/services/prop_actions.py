"""Shared quick-action assembly for room snapshots and layout broadcasts."""

from __future__ import annotations

from server.content.worlds import (
    PropDefinition,
    PropInstanceDefinition,
    QuickAction,
    RoomDefinition,
    resolve_default_prop_actions,
)


def exit_command(exit_id: str) -> str:
    """Return the canonical command for an authored room exit."""

    return f".go @way:{exit_id}"


def canonical_action_command(room: RoomDefinition, command: str) -> str:
    """Normalize legacy ``.go <exit>`` commands for deduplication."""

    if not command.startswith(".go "):
        return command
    remainder = command[4:].strip()
    exit_id = remainder[len("@way:"):] if remainder.startswith("@way:") else remainder
    return exit_command(exit_id) if exit_id in room.exits else command


def merged_prop_actions(
    room: RoomDefinition,
    prop: PropInstanceDefinition,
    definition: PropDefinition,
) -> tuple[QuickAction, ...]:
    """Combine instance custom actions, an exit action, and definition defaults."""

    merged = list(prop.actions)
    seen = {canonical_action_command(room, action.command) for action in merged}
    if prop.exit_to:
        exit_definition = room.exits.get(prop.exit_to)
        if exit_definition is not None:
            command = exit_command(prop.exit_to)
            if command not in seen:
                seen.add(command)
                merged.append(
                    QuickAction(
                        label=exit_definition.label or prop.exit_to,
                        command=command,
                        default=True,
                    )
                )
    for action in resolve_default_prop_actions(definition, prop.id):
        command = canonical_action_command(room, action.command)
        if command in seen:
            continue
        seen.add(command)
        merged.append(action)
    return tuple(merged)


def surface_actions(
    prop: PropInstanceDefinition,
    definition: PropDefinition,
) -> tuple[QuickAction, ...]:
    """Return the editor action for a sign or whiteboard prop."""

    if definition.render_kind == "sign":
        return (QuickAction(label="Edit sign", command=f".sign {prop.id}", default=True),)
    if definition.render_kind == "whiteboard":
        return (QuickAction(label="Open whiteboard", command=f".play {prop.id}", default=True),)
    return ()


def normalize_quick_action(
    room: RoomDefinition,
    action: QuickAction,
    *,
    environment: object | None,
    allowed_verbs: set[str] | frozenset[str] | None,
) -> dict[str, object] | None:
    """Normalize one quick action, dropping disabled or unsupported commands."""

    command = action.command
    is_default = action.default
    if command.startswith(".go "):
        remainder = command[4:].strip()
        exit_id = remainder[len("@way:"):] if remainder.startswith("@way:") else remainder
        if exit_id in room.exits:
            if environment is not None and not environment.is_exit_enabled(room.id, exit_id):
                return None
            command = exit_command(exit_id)
            is_default = True
    verb = command.split(maxsplit=1)[0]
    if allowed_verbs is not None and verb not in allowed_verbs:
        return None
    if environment is not None and not environment.is_action_enabled(room.id, verb):
        return None
    normalized: dict[str, object] = {"label": action.label, "command": command}
    if is_default:
        normalized["default"] = True
    return normalized


def visible_prop_actions(
    room: RoomDefinition,
    actions: tuple[QuickAction, ...],
    *,
    environment: object | None,
    allowed_verbs: set[str] | frozenset[str] | None,
) -> list[dict[str, object]]:
    """Normalize a sequence of quick actions and drop unavailable ones."""

    return [
        normalized
        for action in actions
        if (
            normalized := normalize_quick_action(
                room,
                action,
                environment=environment,
                allowed_verbs=allowed_verbs,
            )
        )
        is not None
    ]
