"""Passkeys on the pages: a challenge offered where a code of the second
factor is asked, and the browser's answer taken from the form that sends
it (docs/AUTHENTICATION.md 4, 5). The script ``static/js/passkey.js``
asks the browser, a page without it takes a code alone.

A challenge counts once: the next form that answers it takes it, right
or wrong, and the next page offers a new one.

``Ways`` names the methods a page offers for the second factor, which
the template ``components/factor.html`` shows one at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ...data.secrets import Begun
from ...domain.auth import Answer
from ..services import get_auth
from ..urls import passkey_party, passkeys_work
from .session import session_of


@dataclass(frozen=True)
class Ways:
    """The methods of the second factor a page offers: a passkey, a code
    of an authenticator app, and a recovery code, which every user with
    the second factor has. ``options``: the challenge for the user's
    passkeys, None where browsers make none here. ``elsewhere``: the
    user has passkeys, which work at another address."""

    totp: bool
    options: str | None
    elsewhere: bool


def first_way(code: str, passkey: str) -> str | None:
    """The method a form refused for its second factor came by, shown
    first when it comes back: "totp" for digits alone, "recovery" for
    another code. None for a passkey or nothing."""
    if passkey or not code:
        return None
    return "totp" if code.replace(" ", "").isdigit() else "recovery"


def ways(request: Request, user_id: str, options: str | None) -> Ways:
    """The methods of the user's second factor, with ``options``, the
    challenge the page offers for its passkeys."""
    factors = get_auth(request).factors
    state = factors.state(user_id) if factors is not None else None
    return Ways(
        totp=bool(state and state.totp),
        options=options,
        elsewhere=bool(state and state.passkeys) and options is None,
    )


def offered(request: Request, user_id: str) -> Ways:
    """The methods of the signed-in user's second factor, with a new
    challenge for its passkeys that the session keeps for the next form."""
    return ways(request, user_id, offer(request, user_id))


def challenge(request: Request, user_id: str) -> Begun | None:
    """A challenge for the user's passkeys at this service. None where
    browsers make no passkeys, such as at an address alone, or for a user
    without one."""
    party = passkey_party(request)
    factors = get_auth(request).factors
    if factors is None or not passkeys_work(party):
        return None
    return factors.challenge(user_id, party)


def offer(request: Request, user_id: str) -> str | None:
    """The options of a new challenge for the signed-in user's passkeys,
    for the page to hand the script. The session keeps the challenge for
    the next form."""
    begun = challenge(request, user_id)
    session_of(request).challenge = begun.challenge if begun else None
    return begun.options if begun else None


def answer(request: Request, kept: str | None, passkey: str) -> Answer | None:
    """The browser's answer from a form, to the challenge ``kept``. None
    when the form carries none, as one with a code does, and when no
    challenge was kept: an answer to nothing is a wrong try."""
    if not passkey or kept is None:
        return None
    return Answer(passkey_party(request), kept, passkey)


def answered(request: Request, passkey: str) -> Answer | None:
    """The answer of a form of the signed-in user, to the challenge its
    session kept. The challenge is gone after."""
    session = session_of(request)
    kept, session.challenge = session.challenge, None
    return answer(request, kept, passkey)
