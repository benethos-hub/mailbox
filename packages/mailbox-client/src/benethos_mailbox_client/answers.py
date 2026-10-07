"""How an answer of the API, or a failure on the way to it, is read: the
JSON of an answer, the error envelope as an ``ApiError``, a service that
cannot be reached or does not answer in time. The same for both
clients."""

from __future__ import annotations

from typing import Any

import httpx

from .calls import Call, T
from .errors import ApiError, MailboxError, ServiceTimeoutError, ServiceUnavailableError


def answer(response: httpx.Response) -> Any:
    """The JSON of a read answer, None for no content. Raises ``ApiError``
    for an error and for an answer that is not JSON."""
    if response.is_error:
        raise api_error(response)
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError:
        raise ApiError(
            response.status_code, "unexpected_response", "the answer is not JSON"
        ) from None


def read(call: Call[T], response: httpx.Response) -> T:
    """What the caller gets of ``response``. An answer of another shape
    than the API describes, such as one without a field the call reads, is
    an ``ApiError`` too, not an error deep inside the reading."""
    found = answer(response)
    try:
        return call.read(found)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ApiError(
            response.status_code,
            "unexpected_response",
            "the answer is not what the API describes",
        ) from None


def api_error(response: httpx.Response) -> ApiError:
    """The error envelope as an ApiError. A validation failure (422) has no
    envelope but a list of what was wrong where, which is what a caller
    needs to correct the call."""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        error = body["error"]
        if "code" in error and "message" in error:
            code, message = str(error["code"]), str(error["message"])
            return ApiError(response.status_code, code, message)
    if isinstance(body, dict) and isinstance(body.get("detail"), list):
        reasons = [
            f"{'.'.join(str(p) for p in item.get('loc', ()) if p != 'body')}: "
            f"{item.get('msg', '')}"
            for item in body["detail"]
            if isinstance(item, dict)
        ]
        if reasons:
            reason = "; ".join(reasons)
            return ApiError(response.status_code, "validation_error", reason)
    return ApiError(response.status_code, "unexpected_response", response.reason_phrase)


def failure(exc: httpx.TransportError, base_url: str, seconds: float) -> MailboxError:
    """What went wrong on the way: a service that answers too slowly is
    running, one that cannot be reached is not."""
    if isinstance(exc, httpx.TimeoutException) and not isinstance(
        exc, httpx.ConnectTimeout
    ):
        return ServiceTimeoutError(
            f"mailbox-service did not answer within {seconds:g} s. "
            "Try a narrower request."
        )
    return ServiceUnavailableError(
        f"mailbox-service is not reachable at {base_url}. "
        "Start it with `benethos-mailbox-service serve`."
    )
