"""Phone text-message commands: list, peers, open, send, read."""

from __future__ import annotations

from server.commands.outcomes import CommandContext, CommandError, CommandOutcome
from server.commands.parser import ParsedCommand
from server.protocol import room_event_envelope


async def _notify(
    context: CommandContext,
    account_id: str,
    thread_key: str,
    sender_name: str,
    preview: str,
    body: str = "",
) -> None:
    """Push a new-text event to a live recipient in this world process."""

    try:
        target = await context.connections.get(account_id)
    except Exception:  # noqa: BLE001 - texts must survive push failures
        return
    if target is None:
        return
    event = {
        "type": "phone.message",
        "thread_key": thread_key,
        "sender_name": sender_name,
        "preview": preview[:48],
        "body": body,
        "unread": context.phone_messages.unread_count(account_id),
    }
    try:
        await target.send(room_event_envelope(event))
    except RuntimeError:
        return


def _threads_payload(context: CommandContext) -> dict[str, object]:
    threads = context.phone_messages.list_threads(context.account.id)
    return {
        "threads": [thread.to_payload() for thread in threads],
        "unread": context.phone_messages.unread_count(context.account.id),
    }


def _thread_payload(context: CommandContext, thread_key: str) -> dict[str, object]:
    thread, messages = context.phone_messages.open_thread(context.account.id, thread_key)
    payload = _threads_payload(context)
    payload["thread"] = thread.to_payload() if thread is not None else None
    payload["messages"] = [message.to_payload() for message in messages]
    return payload


def _npc_peer_name(context: CommandContext, thread_key: str) -> str:
    for thread in context.phone_messages.list_threads(context.account.id):
        if thread.thread_key == thread_key:
            return thread.peer_name
    return "Roommate"


async def phone_msg_command(context: CommandContext, command: ParsedCommand) -> CommandOutcome:
    """List threads, open one, or send a text to a friend, roommate, or thread."""

    if not command.args:
        raise CommandError("Use '.phone_msg <list|peers|open|send|read> [thread] [text]'.")
    from server.services.phone_messages import parse_thread_key

    action = command.args[0].lower()
    service = context.phone_messages
    if action == "list":
        return CommandOutcome(payload={"phone_messages": _threads_payload(context)}, toast=False, log=False)
    if action == "peers":
        friends = context.friends.serialize(context.account.id)
        peers = [
            {"thread_key": f"player:{entry.account_id}", "name": entry.username}
            for entry in friends.friends
        ]
        mod = context.mods.get("tinytown")
        rooms = getattr(mod, "phone_peers", None) if mod is not None else None
        if callable(rooms):
            try:
                for peer in rooms(context.account.id) or []:
                    peers.append(
                        {"thread_key": str(peer["thread_key"]), "name": str(peer["name"])}
                    )
            except Exception:  # noqa: BLE001 - peers must never break the inbox
                pass
        return CommandOutcome(
            payload={"phone_messages": {"peers": peers}}, toast=False, log=False
        )
    if action == "open":
        if len(command.args) < 2:
            raise CommandError("Choose a message thread to open.")
        thread_key = command.args[1]
        if parse_thread_key(thread_key) is None:
            raise CommandError("Unknown message thread.")
        return CommandOutcome(
            payload={"phone_messages": _thread_payload(context, thread_key)}, toast=False, log=False
        )
    if action == "read":
        if len(command.args) < 2:
            raise CommandError("Choose a message thread to mark read.")
        thread_key = command.args[1]
        if parse_thread_key(thread_key) is None:
            raise CommandError("Unknown message thread.")
        service.mark_read(context.account.id, thread_key)
        return CommandOutcome(payload={"phone_messages": _threads_payload(context)}, toast=False, log=False)
    if action == "send":
        if len(command.args) < 3:
            raise CommandError("Use '.phone_msg send <thread> <text>'.")
        thread_key = command.args[1]
        parsed = parse_thread_key(thread_key)
        if parsed is None:
            raise CommandError("Unknown message thread.")
        if context.powers.is_muted(context.account.id):
            raise CommandError("You are muted and cannot send texts right now.")
        text = " ".join(command.args[2:])
        kind, peer = parsed
        if kind == "player":
            target = context.profiles.get_account_by_id(peer)
            if target is None:
                raise CommandError("That peep could not be found.")
            service.send_to_friend(
                context.account, target, text, context.world.id
            )
            await _notify(context, target.id, f"player:{context.account.id}", context.account.username_display, text, text)
            return CommandOutcome(payload={"phone_messages": _thread_payload(context, thread_key)}, toast=False, log=False)
        if kind == "npc":
            from server.services.phone_messages import npc_ids_from_thread_key

            ids = npc_ids_from_thread_key(thread_key)
            if ids is None:
                raise CommandError("Unknown message thread.")
            world_id, npc_id = ids
            reply: tuple[str, str] | None = None
            mod = context.mods.get("tinytown")
            if mod is not None and bool(getattr(mod, "available", False)):
                handler = getattr(mod, "roommate_reply_text", None)
                if callable(handler):
                    try:
                        reply = handler(context.account, npc_id, text)
                    except Exception:  # noqa: BLE001 - replies must never break sending
                        reply = None
            if reply is None:
                from mods.tinytown.roommate_messages import UNREACHABLE_LINES

                peer_name = _npc_peer_name(context, thread_key)
                service.append_npc_exchange(
                    context.account,
                    thread_key,
                    outbound_body=text,
                    inbound_body=UNREACHABLE_LINES[0],
                    inbound_sender=peer_name,
                    world_id=world_id,
                    peer_name=peer_name,
                )
            else:
                reply_text, peer_name = reply
                service.append_npc_exchange(
                    context.account,
                    thread_key,
                    outbound_body=text,
                    inbound_body=reply_text,
                    inbound_sender=peer_name,
                    world_id=world_id,
                    peer_name=peer_name,
                )
            return CommandOutcome(payload={"phone_messages": _thread_payload(context, thread_key)}, toast=False, log=False)
        service.store_outbound(context.account, thread_key, text, context.world.id)
        return CommandOutcome(payload={"phone_messages": _thread_payload(context, thread_key)}, toast=False, log=False)
    raise CommandError("Unknown phone message action.")
