"""Room broadcast fanout cost as occupancy grows.

Every room event -- chat, presence, card pickup, layout save -- fans out to
every live connection in the room. Two things make that cost grow that were
worth pinning down:

* the envelope used to be re-serialised once per recipient, so a broadcast to
  *N* clients cost *N* JSON encodes of the same bytes;
* one client with a full send queue raised out of the broadcast loop and
  silently cancelled delivery to every client after it in the room.

Both are invisible in a functional test with two clients, so they are pinned
here with structural assertions rather than timings.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

from server.broadcast import broadcast_room_event
from server.connections import ConnectionRegistry, LiveConnection
from server.protocol import MAX_SEND_QUEUE, encode_envelope, room_event_envelope
from tests.perf.perfkit import PerfCase

ROOMS = ("hub", "playroom")


class RecordingSocket:
    """A WebSocket stand-in that records the frames written to the wire."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.jsons: list[dict[str, Any]] = []
        self.closed = False

    async def send_text(self, payload: str) -> None:
        self.texts.append(payload)

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.jsons.append(payload)

    async def close(self) -> None:
        self.closed = True


def _connection(account_id: str, room_id: str) -> tuple[LiveConnection, RecordingSocket]:
    socket = RecordingSocket()
    return (
        LiveConnection(
            websocket=socket,  # type: ignore[arg-type]
            account_id=account_id,
            username=account_id,
            generation=1,
        ),
        socket,
    )


class _SeededRegistry(ConnectionRegistry):
    """A registry pre-populated with connections all in one room."""

    def __init__(self, connections: list[LiveConnection], room_id: str = ROOMS[0]) -> None:
        self._lock = asyncio.Lock()
        self._by_account = {connection.account_id: connection for connection in connections}
        self._rooms = {room_id: set(self._by_account)}

    async def list_room(self, room_id: str) -> list[LiveConnection]:
        return [self._by_account[a] for a in self._rooms.get(room_id, set())]


def _runtime(connections: list[LiveConnection]) -> SimpleNamespace:
    return SimpleNamespace(connections=_SeededRegistry(connections))


class BroadcastFanoutTests(PerfCase):
    """A broadcast must serialise once, share the frame, and isolate failures."""

    async def _populate(self, count: int) -> tuple[list[LiveConnection], SimpleNamespace]:
        connections: list[LiveConnection] = []
        for index in range(count):
            connection, _socket = _connection(f"user{index:04d}", ROOMS[0])
            connections.append(connection)
        return connections, _runtime(connections)

    async def test_broadcast_encodes_once_and_shares_the_frame(self) -> None:
        """All recipients must queue the identical object, not a re-encoded copy."""

        connections, runtime = await self._populate(25)
        event = {"type": "chat.message", "room_id": ROOMS[0], "text": "hello world"}
        await broadcast_room_event(runtime, room_id=ROOMS[0], event=event)

        frames = [connection.queue.get_nowait() for connection in connections]
        for frame in frames:
            self.assertIsInstance(
                frame,
                str,
                "broadcast re-encodes per recipient; queue a pre-encoded frame instead",
            )
        first = frames[0]
        for frame in frames[1:]:
            self.assertIs(
                frame,
                first,
                "each recipient received a separately encoded frame instead of a shared one",
            )
        self.assertEqual(
            json.loads(first),
            room_event_envelope(event),
            "the shared frame does not match the expected envelope",
        )

    async def test_broadcast_encodes_exactly_once(self) -> None:
        """Count serialisations directly rather than inferring them from identity."""

        import server.protocol as protocol_module

        original = protocol_module.json.dumps
        calls: list[str] = []

        def counting_dumps(*args: Any, **kwargs: Any) -> str:
            calls.append(str(args[0])[:40] if args else "")
            return original(*args, **kwargs)

        connections, runtime = await self._populate(40)
        event = {"type": "chat.message", "room_id": ROOMS[0], "text": "counted"}
        protocol_module.json.dumps = counting_dumps
        try:
            await broadcast_room_event(runtime, room_id=ROOMS[0], event=event)
        finally:
            protocol_module.json.dumps = original

        self.assertEqual(
            len(calls),
            1,
            f"one broadcast to 40 clients ran {len(calls)} serialisations; it must run exactly one",
        )
        self.measure("server/broadcast/encodes", len(calls), unit="encodes", ceiling=1)

    async def test_a_full_queue_does_not_cancel_the_rest_of_the_room(self) -> None:
        """One stalled client must not stop delivery to the clients behind it."""

        connections, runtime = await self._populate(10)
        stalled = connections[0]
        for _ in range(MAX_SEND_QUEUE):
            stalled.queue.put_nowait("filler")

        event = {"type": "chat.message", "room_id": ROOMS[0], "text": "after the stall"}
        await broadcast_room_event(runtime, room_id=ROOMS[0], event=event)

        for index, connection in enumerate(connections[1:], start=1):
            frame = connection.queue.get_nowait()
            self.assertIsInstance(
                frame,
                str,
                f"client {index} never received the broadcast because an earlier client stalled",
            )
        self.assertEqual(stalled.queue.qsize(), MAX_SEND_QUEUE, "the stalled queue was drained")

    async def test_excluded_recipients_receive_nothing(self) -> None:
        connections, runtime = await self._populate(5)
        event = {"type": "chat.message", "room_id": ROOMS[0], "text": "not for you"}
        await broadcast_room_event(
            runtime, room_id=ROOMS[0], event=event, exclude_account_id="user0000"
        )
        self.assertEqual(connections[0].queue.qsize(), 0, "the excluded client was sent the event")
        for connection in connections[1:]:
            self.assertEqual(connection.queue.qsize(), 1)


class SenderLoopTests(PerfCase):
    """The sender loop must write a pre-encoded frame as-is."""

    async def test_sender_loop_writes_pre_encoded_frames_verbatim(self) -> None:
        connection, socket = _connection("solo", ROOMS[0])
        await connection.start()
        payload = {"v": 1, "type": "room.event", "event": {"type": "chat.message"}}
        await connection.send(encode_envelope(room_event_envelope(payload["event"])))
        await connection.send({"v": 1, "type": "raw.dict"})
        for _ in range(200):
            if len(socket.texts) + len(socket.jsons) >= 2:
                break
            await asyncio.sleep(0.01)
        await connection.close()

        self.assertEqual(len(socket.texts), 1, "the pre-encoded frame was not sent as text")
        self.assertEqual(len(socket.jsons), 1, "a dict payload should still use send_json")
        self.assertEqual(json.loads(socket.texts[0]), room_event_envelope(payload["event"]))
        self.assertTrue(socket.closed, "close() did not close the socket")
