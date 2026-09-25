"""Active WebSocket connection registry."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from contextlib import suppress

from fastapi import WebSocket

from server.protocol import MAX_SEND_QUEUE, session_replaced_envelope


@dataclass(slots=True)
class LiveConnection:
    """A single authenticated live WebSocket connection."""

    websocket: WebSocket
    account_id: str
    username: str
    generation: int
    room_id: str | None = None
    audio_enabled: bool = False
    queue: asyncio.Queue[dict[str, object] | None] = field(default_factory=lambda: asyncio.Queue(MAX_SEND_QUEUE))
    sender_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background sender loop."""

        self.sender_task = asyncio.create_task(self._sender_loop())

    async def _sender_loop(self) -> None:
        while True:
            payload = await self.queue.get()
            if payload is None:
                return
            await self.websocket.send_json(payload)

    async def send(self, payload: dict[str, object]) -> None:
        """Enqueue an outbound payload for delivery."""

        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull as exc:
            raise RuntimeError("Connection send queue is full.") from exc

    async def close(self) -> None:
        """Close the sender loop and the underlying socket."""

        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if self.sender_task is not None:
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self.sender_task, timeout=1)
        await self.websocket.close()


@dataclass(slots=True)
class SyntheticConnection:
    """A connection stand-in for out-of-band command dispatch (mission control).

    Handlers read ``account_id``/``username``/``generation``/``room_id``; the
    send/close methods are no-ops because there is no live socket.
    """

    account_id: str
    username: str
    generation: int = 0
    room_id: str | None = None

    async def send(self, payload: dict[str, object]) -> None:  # noqa: ARG002
        return None

    async def close(self) -> None:
        return None


class ConnectionRegistry:
    """Tracks active users and room membership."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_account: dict[str, LiveConnection] = {}
        self._rooms: dict[str, set[str]] = {}

    async def register(self, connection: LiveConnection) -> LiveConnection | None:
        """Register a new connection and return any replaced connection."""

        async with self._lock:
            replaced = self._by_account.get(connection.account_id)
            self._by_account[connection.account_id] = connection
            return replaced

    def _discard_from_room(self, room_id: str, account_id: str) -> None:
        room_members = self._rooms.get(room_id)
        if room_members is None:
            return
        room_members.discard(account_id)
        if not room_members:
            self._rooms.pop(room_id, None)

    async def unregister(
        self,
        account_id: str,
        expected: LiveConnection | None = None,
    ) -> None:
        """Remove the current connection, optionally only when it matches *expected*."""

        async with self._lock:
            connection = self._by_account.get(account_id)
            if connection is None:
                return
            if expected is not None and connection is not expected:
                return
            self._by_account.pop(account_id)
            if connection.room_id is not None:
                self._discard_from_room(connection.room_id, account_id)

    async def set_room(self, account_id: str, room_id: str | None) -> None:
        """Update room membership for the given connection."""

        async with self._lock:
            connection = self._by_account.get(account_id)
            if connection is None:
                return
            previous_room = connection.room_id
            if previous_room == room_id:
                return
            if previous_room is not None:
                self._discard_from_room(previous_room, account_id)
            connection.room_id = room_id
            if room_id is not None:
                self._rooms.setdefault(room_id, set()).add(account_id)

    async def get(self, account_id: str) -> LiveConnection | None:
        """Fetch a live connection by account ID."""

        async with self._lock:
            return self._by_account.get(account_id)

    async def set_audio(self, account_id: str, enabled: bool) -> None:
        """Update the audio chat flag for a live connection."""

        async with self._lock:
            connection = self._by_account.get(account_id)
            if connection is not None:
                connection.audio_enabled = enabled

    async def count_audio(self, room_id: str, *, exclude_account_id: str | None = None) -> int:
        """Count connections with audio chat enabled in a room."""

        async with self._lock:
            account_ids = self._rooms.get(room_id, set())
            count = 0
            for account_id in account_ids:
                if account_id == exclude_account_id:
                    continue
                connection = self._by_account.get(account_id)
                if connection is not None and connection.audio_enabled:
                    count += 1
            return count

    def is_online(self, account_id: str) -> bool:
        """Return whether an account currently has a live connection."""

        return account_id in self._by_account

    def list_all(self) -> list[LiveConnection]:
        """Return every live connection."""

        return list(self._by_account.values())

    async def broadcast(self, payload: dict[str, object]) -> int:
        """Send a payload to every live connection and return the count sent."""

        connections = self.list_all()
        sent = 0
        for connection in connections:
            try:
                await connection.send(payload)
            except RuntimeError:
                continue
            sent += 1
        return sent

    async def list_room(self, room_id: str) -> list[LiveConnection]:
        """List live connections currently in a room."""

        async with self._lock:
            account_ids = list(self._rooms.get(room_id, set()))
            return [self._by_account[account_id] for account_id in account_ids if account_id in self._by_account]

    async def send_session_replaced(
        self,
        connection: LiveConnection,
        message: str = "Your session was replaced by a newer login.",
    ) -> None:
        """Notify a revoked gameplay session and close it."""

        try:
            await connection.websocket.send_json(session_replaced_envelope(message))
        finally:
            await self.unregister(connection.account_id, connection)
            await connection.close()
