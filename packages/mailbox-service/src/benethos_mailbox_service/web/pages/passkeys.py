"""Passkeys on the pages: a challenge offered where a code of the second
factor is asked, and the browser's answer taken from the form that sends
it (docs/AUTHENTICATION.md 4, 5). The script ``static/js/passkey.js``
asks the browser, a page without it takes a code alone.

A challenge counts once: the next form that answers it takes it, right
or wrong, and the next page offers a new one.
"""

from __future__ import annotations

from fastapi import Request

from ...data.secrets import Begun
from ...domain.auth import Answer
from ..services import get_auth
from ..urls import passkey_party, passkeys_work
from .session import session_of


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
    when the form carries none, as one with a code does."""
    if not passkey:
        return None
    return Answer(passkey_party(request), kept or "", passkey)


def answered(request: Request, passkey: str) -> Answer | None:
    """The answer of a form of the signed-in user, to the challenge its
    session kept. The challenge is gone after."""
    session = session_of(request)
    kept, session.challenge = session.challenge, None
    return answer(request, kept, passkey)
