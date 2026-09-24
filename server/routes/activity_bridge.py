"""HTTP bridge handling for signed activity results."""

from __future__ import annotations

import hmac

from fastapi.responses import JSONResponse


def _rejected(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"ok": False, "code": "activity_result_rejected", "message": message},
    )


def handle_activity_result(runtime: object, session: object, activity: object, payload: dict[str, object]) -> object:
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
    try:
        outcome = runtime.activity_results.complete(
            account,
            activity.kind,
            payload.get("result"),
        )
    except ValueError as exc:
        return _rejected(str(exc))
    return {
        "ok": True,
        "activity": runtime.activities.serialize(activity),
        "records": outcome.records.to_payload(),
        "recorded": outcome.recorded,
        "seconds": outcome.seconds,
    }
