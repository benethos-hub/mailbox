"""Proving who calls: tokens, passwords and the brake on guessed
credentials (CONCEPT 7.5).

``AuthService`` turns what a caller presented into an ``Access``.
"""

from __future__ import annotations

from .passwords import Passwords
from .service import MAX_NAME, AuthService, SignedIn, TokenState

__all__ = [
    "AuthService",
    "MAX_NAME",
    "Passwords",
    "SignedIn",
    "TokenState",
]
