"""Room broadcast helpers shared by the WebSocket loop and mission control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.protocol import room_event_envelope


if TYPE_CHECKING:
    from server.app import RuntimeState


async def broadcast_room_event(
    runtime: RuntimeState,
    *,
    room_id: str,
    event: dict[str, object],
    exclude_account_id: str | None = None,
) -> None:
    """Send a room event to every live connection in *room_id*."""

    for connection in await runtime.connections.list_room(room_id):
        if exclude_account_id is not None and connection.account_id == exclude_account_id:
            continue
        await connection.send(room_event_envelope(event))


async def deliver_behavior_result(runtime: RuntimeState, result: object | None) -> None:
    """Broadcast room events and route private events produced by behaviors."""

    if result is None:
        return
    for pending in getattr(result, "room_broadcasts", []):
        await broadcast_room_event(runtime, room_id=pending.room_id, event=pending.event)
    for event in getattr(result, "private_events", []):
        account_id = event.get("account_id")
        if not isinstance(account_id, str):
            continue
        target = await runtime.connections.get(account_id)
        if target is not None:
            await target.send(room_event_envelope(event))
