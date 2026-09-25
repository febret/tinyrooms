"""Typed WebSocket envelopes and serializer helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json


PROTOCOL_VERSION = 1
MAX_COMMAND_SIZE = 1024
MAX_CHAT_SIZE = 280
MAX_HISTORY_MESSAGES = 50
MAX_SEND_QUEUE = 128
MAX_SIGNAL_SIZE = 65536
MAX_ACCOUNT_ID_SIZE = 64
RTC_SIGNAL_KINDS = frozenset({"offer", "answer", "candidate", "bye"})


class ProtocolError(ValueError):
    """Raised when an envelope is malformed."""


@dataclass(frozen=True, slots=True)
class ClientCommandEnvelope:
    """A validated client command envelope."""

    request_id: str
    command: str


@dataclass(frozen=True, slots=True)
class ClientRtcPresenceEnvelope:
    """A validated audio chat presence toggle."""

    enabled: bool


@dataclass(frozen=True, slots=True)
class ClientRtcSignalEnvelope:
    """A validated WebRTC signaling payload addressed at one peer."""

    to: str
    signal: dict[str, object]


def _require_string(payload: dict[str, object], key: str, limit: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ProtocolError(f"'{key}' must be a string.")
    text = value.strip()
    if not text:
        raise ProtocolError(f"'{key}' must not be empty.")
    if len(text) > limit:
        raise ProtocolError(f"'{key}' exceeds maximum length {limit}.")
    return text


def _require_optional_string(payload: dict[str, object], key: str, limit: int) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProtocolError(f"'{key}' must be a string.")
    if len(value) > limit:
        raise ProtocolError(f"'{key}' exceeds maximum length {limit}.")
    return value


def _validate_rtc_signal(signal: object) -> dict[str, object]:
    if not isinstance(signal, dict):
        raise ProtocolError("'signal' must be an object.")
    kind = signal.get("kind")
    if not isinstance(kind, str) or kind not in RTC_SIGNAL_KINDS:
        raise ProtocolError("'signal.kind' must be one of offer, answer, candidate, bye.")
    if kind in {"offer", "answer"}:
        description = signal.get("sdp")
        if not isinstance(description, str) or not description:
            raise ProtocolError("'signal.sdp' must be a non-empty string.")
        if len(description) > MAX_SIGNAL_SIZE:
            raise ProtocolError("'signal.sdp' is too large.")
        return {"kind": kind, "sdp": description}
    if kind == "candidate":
        candidate = signal.get("candidate")
        if not isinstance(candidate, str):
            raise ProtocolError("'signal.candidate' must be a string.")
        if len(candidate) > MAX_SIGNAL_SIZE:
            raise ProtocolError("'signal.candidate' is too large.")
        return {
            "kind": kind,
            "candidate": candidate,
            "sdp_mid": _require_optional_string(signal, "sdp_mid", 64),
            "sdp_m_line_index": signal.get("sdp_m_line_index") if isinstance(signal.get("sdp_m_line_index"), int) else 0,
        }
    return {"kind": kind}


ParsedClientPayload = (
    ClientCommandEnvelope | ClientRtcPresenceEnvelope | ClientRtcSignalEnvelope | None
)


def parse_client_message(raw_text: str) -> tuple[str, ParsedClientPayload]:
    """Parse a raw WebSocket message and return its type and payload."""

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Envelope is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("Envelope must be a JSON object.")
    version = payload.get("v")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version '{version}'.")
    envelope_type = payload.get("type")
    if envelope_type == "command":
        request_id = _require_string(payload, "request_id", 80)
        command = _require_string(payload, "command", MAX_COMMAND_SIZE)
        return envelope_type, ClientCommandEnvelope(request_id=request_id, command=command)
    if envelope_type == "snapshot.request":
        return envelope_type, None
    if envelope_type == "rtc.presence":
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise ProtocolError("'enabled' must be a boolean.")
        return envelope_type, ClientRtcPresenceEnvelope(enabled=enabled)
    if envelope_type == "rtc.signal":
        if len(raw_text) > MAX_SIGNAL_SIZE:
            raise ProtocolError("RTC signal envelope is too large.")
        target = _require_string(payload, "to", MAX_ACCOUNT_ID_SIZE)
        signal = _validate_rtc_signal(payload.get("signal"))
        return envelope_type, ClientRtcSignalEnvelope(to=target, signal=signal)
    raise ProtocolError(f"Unsupported envelope type '{envelope_type}'.")


def result_envelope(
    request_id: str,
    *,
    ok: bool,
    code: str | None = None,
    message: str | None = None,
    payload: dict[str, object] | None = None,
    events: list[dict[str, object]] | None = None,
    toast: bool = True,
    log: bool = True,
) -> dict[str, object]:
    """Build a private command result envelope.

    ``toast`` and ``log`` are only serialized when disabled, so clients default
    to showing the acknowledgement in both places.
    """

    envelope: dict[str, object] = {
        "v": PROTOCOL_VERSION,
        "type": "result",
        "request_id": request_id,
        "ok": ok,
        "events": events or [],
    }
    if code is not None:
        envelope["code"] = code
    if message is not None:
        envelope["message"] = message
    if payload is not None:
        envelope["payload"] = payload
    if not toast:
        envelope["toast"] = False
    if not log:
        envelope["log"] = False
    return envelope


def room_snapshot_envelope(room: dict[str, object]) -> dict[str, object]:
    """Build a full room snapshot envelope."""

    return {"v": PROTOCOL_VERSION, "type": "room.snapshot", "room": room}


def room_event_envelope(event: dict[str, object]) -> dict[str, object]:
    """Build a room event envelope."""

    return {"v": PROTOCOL_VERSION, "type": "room.event", "event": event}


def session_replaced_envelope(message: str) -> dict[str, object]:
    """Build a forced sign-out envelope."""

    return {"v": PROTOCOL_VERSION, "type": "session.replaced", "message": message}


def rtc_signal_envelope(
    *,
    from_account_id: str,
    from_username: str,
    signal: dict[str, object],
) -> dict[str, object]:
    """Build a relayed WebRTC signaling envelope."""

    return {
        "v": PROTOCOL_VERSION,
        "type": "rtc.signal",
        "from": from_account_id,
        "from_username": from_username,
        "signal": signal,
    }


def presence_audio_event(
    *,
    account_id: str,
    username: str,
    room_id: str,
    enabled: bool,
) -> dict[str, object]:
    """Build the room event that announces an audio chat toggle."""

    return {
        "type": "presence.audio",
        "room_id": room_id,
        "account_id": account_id,
        "username": username,
        "enabled": enabled,
    }


def profile_resync_envelope(revision: int) -> dict[str, object]:
    """Build a profile-resync envelope instructing clients to refresh."""

    return {"v": PROTOCOL_VERSION, "type": "profile.resync", "revision": revision}


def error_envelope(code: str, message: str) -> dict[str, object]:
    """Build a protocol-level error envelope."""

    return {"v": PROTOCOL_VERSION, "type": "error", "code": code, "message": message}


def visible_rejection_event(code: str, message: str) -> dict[str, object]:
    """Build a visible rejection event payload."""

    return {"type": "visible.rejection", "code": code, "message": message}


def presence_enter_event(
    *,
    account_id: str,
    username: str,
    room_id: str,
    source_room_id: str,
    source_room_label: str | None = None,
) -> dict[str, object]:
    """Build the room presence-enter event payload."""

    event = {"type": "presence.enter", "room_id": room_id, "account_id": account_id, "username": username, "source_room_id": source_room_id}
    if source_room_label is not None:
        event["source_room_label"] = source_room_label
    return event


def presence_leave_event(
    *,
    account_id: str,
    username: str,
    room_id: str,
    destination_room_id: str | None = None,
    direction: str | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    """Build the room presence-leave event payload."""

    event = {"type": "presence.leave", "room_id": room_id, "account_id": account_id, "username": username}
    if destination_room_id is not None:
        event["destination_room_id"] = destination_room_id
    if direction is not None:
        event["direction"] = direction
    if reason is not None:
        event["reason"] = reason
    return event

