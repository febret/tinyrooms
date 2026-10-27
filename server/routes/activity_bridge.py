"""HTTP bridge handling for signed activity results."""

from __future__ import annotations

import hmac

from fastapi.responses import JSONResponse

from server.behaviors.events import BehaviorEvent, PeepRef
from server.broadcast import deliver_behavior_result
from server.serialization import serialize_account


def _rejected(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "code": "activity_result_rejected", "message": message},
    )


async def handle_activity_result(runtime: object, session: object, activity: object, payload: dict[str, object]) -> object:
    """Validate a signed result, record it, and return the running activity.

    The signature is the session token issued to the iframe; a tampered or
    mismatched token leaves all state untouched.
    """

    token = payload.get("token")
    if not isinstance(token, str) or not hmac.compare_digest(token, activity.token):
        return _rejected("That activity result could not be verified.")
    account = runtime.profiles.get_account_by_id(session.account_id)
    if account is None:
        return _rejected("Unknown account.")
    raw_result = payload.get("result")
    try:
        outcome = runtime.activity_results.complete(
            account,
            activity.kind,
            raw_result,
            record_tasks=False,
        )
    except ValueError as exc:
        return _rejected(str(exc))
    # The dispatcher records the task trigger once and gives world scripts a
    # chance to react to the signed result (for example, awarding a quest card).
    result_fields = dict(raw_result) if isinstance(raw_result, dict) else {}
    behavior = await runtime.behaviors.dispatch(
        BehaviorEvent(
            type="activity_result",
            actor=PeepRef(kind="user", peep_id=None, account_id=account.id),
            target=None,
            room_id=activity.room_id,
            data={**result_fields, "activity": activity.kind},
        )
    )
    await deliver_behavior_result(runtime, behavior)
    response: dict[str, object] = {
        "ok": True,
        "activity": runtime.activities.serialize(activity),
        "records": outcome.records.to_payload(),
        "recorded": outcome.recorded,
        "seconds": outcome.seconds,
    }
    if getattr(behavior, "inventory_changed_for", None) == account.id:
        stacks = runtime.profiles.list_inventory(account.id, runtime.world.id)
        current = runtime.profiles.get_account_by_id(account.id) or account
        response["inventory"] = runtime.cards.serialize_inventory_stacks(stacks)
        response["user"] = serialize_account(runtime, current)
    return response
