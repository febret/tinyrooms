"""Phone message inbox: friend SMS, NPC texts, and gameplay mail.

Threads live in the shared profile database so the phone follows the player
across worlds. Each participant stores their own rows: a friend send writes an
outbox row for the sender and an inbox row for the recipient, while NPC and
system messages write a single inbox row for the owner.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from server.profiles import AccountRecord, ProfileRepository
from server.security import utc_now
from server.state.migrations import DatabaseHub


MAX_MESSAGE_BODY = 160
MAX_MESSAGES_PER_THREAD = 40
MAX_THREADS = 80


def friend_thread_key(account_id: str) -> str:
    """Return the thread key shared by two player phones."""

    return f"player:{account_id}"


def npc_thread_key(world_id: str, npc_id: str) -> str:
    """Return the thread key for messages from one NPC peep."""

    return f"npc:{world_id}:{npc_id}"


def system_thread_key(source_id: str) -> str:
    """Return the thread key for one gameplay message source."""

    return f"system:{source_id}"


def parse_thread_key(thread_key: str) -> tuple[str, str] | None:
    """Split a thread key into (kind, peer) without trusting its shape."""

    key = str(thread_key or "")
    if key.startswith("player:") and len(key) > len("player:"):
        return ("player", key[len("player:"):])
    if key.startswith("npc:"):
        rest = key[len("npc:"):]
        world_id, separator, npc_id = rest.partition(":")
        if separator and world_id and npc_id:
            return ("npc", f"{world_id}:{npc_id}")
    if key.startswith("system:") and len(key) > len("system:"):
        return ("system", key[len("system:"):])
    return None


def npc_ids_from_thread_key(thread_key: str) -> tuple[str, str] | None:
    """Split an NPC thread key into (world_id, npc_id)."""

    parsed = parse_thread_key(thread_key)
    if parsed is None or parsed[0] != "npc":
        return None
    world_id, _, npc_id = parsed[1].partition(":")
    if not world_id or not npc_id:
        return None
    return (world_id, npc_id)


def clean_body(body: str) -> str:
    """Trim and validate player-authored message text."""

    text = " ".join(str(body or "").split())
    if not text:
        raise ValueError("Message text cannot be empty.")
    if len(text) > MAX_MESSAGE_BODY:
        raise ValueError(f"Messages can be at most {MAX_MESSAGE_BODY} characters.")
    return text


@dataclass(frozen=True, slots=True)
class MessageView:
    """One serialized phone message."""

    message_id: str
    direction: str
    sender_name: str
    body: str
    created_at: str
    read: bool

    def to_payload(self) -> dict[str, object]:
        """Serialize the message for the client."""

        return {
            "message_id": self.message_id,
            "direction": self.direction,
            "sender_name": self.sender_name,
            "body": self.body,
            "created_at": self.created_at,
            "read": self.read,
        }


@dataclass(frozen=True, slots=True)
class ThreadView:
    """One serialized message thread."""

    thread_key: str
    kind: str
    peer_name: str
    preview: str
    last_at: str
    unread: int

    def to_payload(self) -> dict[str, object]:
        """Serialize the thread for the client."""

        return {
            "thread_key": self.thread_key,
            "kind": self.kind,
            "peer_name": self.peer_name,
            "preview": self.preview,
            "last_at": self.last_at,
            "unread": self.unread,
        }


def _row_to_message(row: sqlite3.Row) -> MessageView:
    return MessageView(
        message_id=row["message_id"],
        direction=row["direction"],
        sender_name=row["sender_name"],
        body=row["body"],
        created_at=row["created_at"],
        read=row["read_at"] is not None,
    )


class PhoneMessageService:
    """Owns phone inbox rows and the friend-text lifecycle."""

    def __init__(self, hub: DatabaseHub, profiles: ProfileRepository) -> None:
        self._hub = hub
        self._profiles = profiles

    def _insert(
        self,
        connection: sqlite3.Connection,
        owner_id: str,
        thread_key: str,
        direction: str,
        sender_name: str,
        body: str,
        world_id: str,
        meta: dict[str, object] | None,
    ) -> MessageView:
        created_at = utc_now().isoformat()
        message_id = f"pmsg:{uuid.uuid4().hex}"
        meta_json = json.dumps(dict(meta or {}))
        connection.execute(
            "INSERT INTO phone_messages (message_id, owner_account_id, thread_key, direction,"
            " sender_name, body, created_at, read_at, world_id, meta_json)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                message_id,
                owner_id,
                thread_key,
                direction,
                sender_name,
                body,
                created_at,
                world_id,
                meta_json,
            ),
        )
        self._trim_thread(connection, owner_id, thread_key)
        self._trim_threads(connection, owner_id, keep=thread_key)
        return MessageView(
            message_id=message_id,
            direction=direction,
            sender_name=sender_name,
            body=body,
            created_at=created_at,
            read=direction == "out",
        )

    @staticmethod
    def _trim_thread(connection: sqlite3.Connection, owner_id: str, thread_key: str) -> None:
        connection.execute(
            "DELETE FROM phone_messages WHERE owner_account_id = ? AND thread_key = ?"
            " AND rowid NOT IN (SELECT rowid FROM phone_messages"
            " WHERE owner_account_id = ? AND thread_key = ?"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?)",
            (owner_id, thread_key, owner_id, thread_key, MAX_MESSAGES_PER_THREAD),
        )

    @staticmethod
    def _trim_threads(connection: sqlite3.Connection, owner_id: str, keep: str) -> None:
        rows = connection.execute(
            "SELECT thread_key, MAX(created_at) AS last_at FROM phone_messages"
            " WHERE owner_account_id = ? GROUP BY thread_key ORDER BY last_at DESC, thread_key",
            (owner_id,),
        ).fetchall()
        doomed = [str(row["thread_key"]) for row in rows[MAX_THREADS:] if str(row["thread_key"]) != keep]
        for thread_key in doomed:
            connection.execute(
                "DELETE FROM phone_messages WHERE owner_account_id = ? AND thread_key = ?",
                (owner_id, thread_key),
            )

    def send_to_friend(
        self,
        sender: AccountRecord,
        target: AccountRecord,
        body: str,
        world_id: str,
    ) -> tuple[MessageView, MessageView]:
        """Write a friend text to both phones in one transaction."""

        if target.id == sender.id:
            raise ValueError("You cannot text yourself.")
        text = clean_body(body)
        sender_profile = self._profiles.get_user_profile(sender.id)
        if sender_profile is None or target.id not in sender_profile.friends:
            raise ValueError("You can only text friends.")
        if self._profiles.get_account_by_id(target.id) is None:
            raise ValueError("That peep could not be found.")
        thread_key = friend_thread_key(target.id)
        sender_thread = friend_thread_key(sender.id)
        with self._hub.transaction() as connection:
            outgoing = self._insert(
                connection,
                sender.id,
                thread_key,
                "out",
                sender.username_display,
                text,
                world_id,
                {"peer_name": target.username_display},
            )
            incoming = self._insert(
                connection,
                target.id,
                sender_thread,
                "in",
                sender.username_display,
                text,
                world_id,
                None,
            )
        return (outgoing, incoming)

    def store_outbound(
        self,
        owner: AccountRecord,
        thread_key: str,
        body: str,
        world_id: str,
        *,
        peer_name: str = "",
    ) -> MessageView:
        """Keep a player reply to an NPC or system thread on their own phone."""

        text = clean_body(body)
        if parse_thread_key(thread_key) is None:
            raise ValueError("Unknown message thread.")
        meta = {"peer_name": peer_name} if peer_name else None
        with self._hub.transaction() as connection:
            return self._insert(
                connection, owner.id, thread_key, "out", owner.username_display, text, world_id, meta
            )

    def deliver_inbound(
        self,
        owner_account_id: str,
        thread_key: str,
        sender_name: str,
        body: str,
        world_id: str,
        meta: dict[str, object] | None = None,
    ) -> MessageView:
        """Write one NPC or system text to the owner's phone.

        Friendship and mute checks do not apply: the phone owner never authored
        this text, so moderated players still receive roommate mail.
        """

        text = clean_body(body)
        if parse_thread_key(thread_key) is None:
            raise ValueError("Unknown message thread.")
        name = str(sender_name or "").strip() or "Unknown"
        with self._hub.transaction() as connection:
            return self._insert(
                connection, owner_account_id, thread_key, "in", name, text, world_id, meta
            )

    def append_npc_exchange(
        self,
        owner: AccountRecord,
        thread_key: str,
        *,
        outbound_body: str,
        inbound_body: str,
        inbound_sender: str,
        world_id: str,
        peer_name: str = "",
        meta: dict[str, object] | None = None,
    ) -> tuple[MessageView, MessageView]:
        """Store a player text plus its canned NPC reply on the owner's phone."""

        outgoing_text = clean_body(outbound_body)
        incoming_text = clean_body(inbound_body)
        if parse_thread_key(thread_key) is None:
            raise ValueError("Unknown message thread.")
        with self._hub.transaction() as connection:
            outgoing = self._insert(
                connection,
                owner.id,
                thread_key,
                "out",
                owner.username_display,
                outgoing_text,
                world_id,
                {"peer_name": peer_name} if peer_name else None,
            )
            incoming = self._insert(
                connection,
                owner.id,
                thread_key,
                "in",
                str(inbound_sender or "").strip() or "Unknown",
                incoming_text,
                world_id,
                meta,
            )
        return (outgoing, incoming)

    def _peer_name(self, owner_id: str, thread_key: str, kind: str, peer: str) -> str:
        if kind == "player":
            target = self._profiles.get_account_by_id(peer)
            if target is not None:
                return target.username_display
        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT sender_name FROM phone_messages WHERE owner_account_id = ?"
                " AND thread_key = ? AND direction = 'in' ORDER BY created_at DESC LIMIT 1",
                (owner_id, thread_key),
            ).fetchone()
            if row is not None:
                return str(row["sender_name"])
            meta_row = connection.execute(
                "SELECT meta_json FROM phone_messages WHERE owner_account_id = ?"
                " AND thread_key = ? ORDER BY created_at DESC LIMIT 1",
                (owner_id, thread_key),
            ).fetchone()
        if meta_row is not None:
            try:
                meta = json.loads(str(meta_row["meta_json"]))
            except ValueError:
                meta = None
            if isinstance(meta, dict) and str(meta.get("peer_name") or "").strip():
                return str(meta["peer_name"])
        return peer

    def list_threads(self, owner_id: str) -> list[ThreadView]:
        """Return every thread with its latest preview and unread count."""

        with self._hub.locked() as connection:
            rows = connection.execute(
                "SELECT thread_key, MAX(created_at) AS last_at,"
                " SUM(CASE WHEN read_at IS NULL AND direction = 'in' THEN 1 ELSE 0 END) AS unread"
                " FROM phone_messages WHERE owner_account_id = ?"
                " GROUP BY thread_key ORDER BY last_at DESC",
                (owner_id,),
            ).fetchall()
            previews = {
                str(row["thread_key"]): str(row["body"])
                for row in connection.execute(
                    "SELECT thread_key, body FROM phone_messages WHERE owner_account_id = ?"
                    " AND rowid IN (SELECT MAX(rowid) FROM phone_messages"
                    " WHERE owner_account_id = ? GROUP BY thread_key)",
                    (owner_id, owner_id),
                ).fetchall()
            }
        threads: list[ThreadView] = []
        for row in rows:
            thread_key = str(row["thread_key"])
            parsed = parse_thread_key(thread_key)
            if parsed is None:
                continue
            kind, peer = parsed
            body = previews.get(thread_key, "")
            threads.append(
                ThreadView(
                    thread_key=thread_key,
                    kind=kind,
                    peer_name=self._peer_name(owner_id, thread_key, kind, peer),
                    preview=body[:48],
                    last_at=str(row["last_at"]),
                    unread=int(row["unread"] or 0),
                )
            )
        return threads

    def open_thread(
        self, owner_id: str, thread_key: str, *, limit: int = MAX_MESSAGES_PER_THREAD
    ) -> tuple[ThreadView | None, list[MessageView]]:
        """Mark a thread read and return its latest messages, oldest first."""

        if parse_thread_key(thread_key) is None:
            raise ValueError("Unknown message thread.")
        now = utc_now().isoformat()
        with self._hub.transaction() as connection:
            connection.execute(
                "UPDATE phone_messages SET read_at = COALESCE(read_at, ?) WHERE owner_account_id = ?"
                " AND thread_key = ?",
                (now, owner_id, thread_key),
            )
            rows = connection.execute(
                "SELECT message_id, direction, sender_name, body, created_at, read_at"
                " FROM phone_messages WHERE owner_account_id = ? AND thread_key = ?"
                " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (owner_id, thread_key, max(1, min(int(limit), MAX_MESSAGES_PER_THREAD))),
            ).fetchall()
        messages = [_row_to_message(row) for row in reversed(rows)]
        threads = [thread for thread in self.list_threads(owner_id) if thread.thread_key == thread_key]
        if not messages:
            return (threads[0] if threads else None, [])
        last = messages[-1]
        if threads:
            return (threads[0], messages)
        parsed = parse_thread_key(thread_key)
        kind, peer = parsed if parsed is not None else ("player", thread_key)
        return (
            ThreadView(
                thread_key=thread_key,
                kind=kind,
                peer_name=self._peer_name(owner_id, thread_key, kind, peer),
                preview=last.body[:48],
                last_at=last.created_at,
                unread=0,
            ),
            messages,
        )

    def mark_read(self, owner_id: str, thread_key: str) -> None:
        """Mark every message in a thread read without returning rows."""

        if parse_thread_key(thread_key) is None:
            raise ValueError("Unknown message thread.")
        with self._hub.transaction() as connection:
            connection.execute(
                "UPDATE phone_messages SET read_at = COALESCE(read_at, ?) WHERE owner_account_id = ?"
                " AND thread_key = ?",
                (utc_now().isoformat(), owner_id, thread_key),
            )

    def unread_count(self, owner_id: str) -> int:
        """Count unread inbound messages across every thread."""

        with self._hub.locked() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM phone_messages WHERE owner_account_id = ?"
                " AND direction = 'in' AND read_at IS NULL",
                (owner_id,),
            ).fetchone()
        return int(row["total"] if row is not None else 0)
