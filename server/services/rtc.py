"""Peer-to-peer audio chat presence and WebRTC signaling relay."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from server.broadcast import broadcast_room_event
from server.protocol import (
    error_envelope,
    presence_audio_event,
    rtc_signal_envelope,
)
from server.security import RateLimitError, RateLimiter


if TYPE_CHECKING:
    from server.app import RuntimeState
    from server.connections import LiveConnection


MAX_AUDIO_PARTICIPANTS = 6
SIGNAL_RATE_LIMIT = 240
SIGNAL_RATE_WINDOW_SECONDS = 10


_signal_limiter = RateLimiter()


async def set_audio_presence(
    runtime: RuntimeState,
    connection: LiveConnection,
    *,
    enabled: bool,
) -> None:
    """Record an audio chat toggle and announce it to the room."""

    room_id = connection.room_id
    if room_id is None:
        return
    if enabled and not connection.audio_enabled:
        current = await runtime.connections.count_audio(
            room_id,
            exclude_account_id=connection.account_id,
        )
        if current >= MAX_AUDIO_PARTICIPANTS:
            await connection.send(
                error_envelope("audio_full", "Audio chat is full in this room.")
            )
            return
    await runtime.connections.set_audio(connection.account_id, enabled)
    await broadcast_room_event(
        runtime,
        room_id=room_id,
        event=presence_audio_event(
            account_id=connection.account_id,
            username=connection.username,
            room_id=room_id,
            enabled=enabled,
        ),
    )


async def relay_signal(
    runtime: RuntimeState,
    connection: LiveConnection,
    *,
    target_id: str,
    signal: dict[str, object],
) -> None:
    """Forward a WebRTC signaling payload to one audio peer in the same room."""

    room_id = connection.room_id
    if room_id is None or not connection.audio_enabled:
        await connection.send(
            error_envelope("rtc_rejected", "Enable audio chat before signaling.")
        )
        return
    target = await runtime.connections.get(target_id)
    if target is None or target.room_id != room_id or not target.audio_enabled:
        await connection.send(
            error_envelope("rtc_rejected", "That peer is not available for audio chat.")
        )
        return
    try:
        _signal_limiter.check(
            connection.account_id,
            limit=SIGNAL_RATE_LIMIT,
            window_seconds=SIGNAL_RATE_WINDOW_SECONDS,
            now_ts=time.monotonic(),
        )
    except RateLimitError:
        await connection.send(
            error_envelope("rtc_throttled", "Too many audio signals. Try again shortly.")
        )
        return
    await target.send(
        rtc_signal_envelope(
            from_account_id=connection.account_id,
            from_username=connection.username,
            signal=signal,
        )
    )
