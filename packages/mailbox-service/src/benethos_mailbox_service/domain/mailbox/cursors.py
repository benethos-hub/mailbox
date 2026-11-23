"""The cursors of the mail lists, sealed by the service.

A provider's cursor names what it lists next, for Microsoft a path of
Graph. One the caller made up could name another folder, past what the
caller may reach. So each cursor a list hands out carries an HMAC under a
key of the running service, and a list takes back only a cursor whose
HMAC holds. The key is made at start and kept in memory alone: a list
works before the keys of the vault exist, and a cursor from before a
restart is refused, so its list starts again.
"""

from __future__ import annotations

import secrets
from typing import Any, TypeVar

from benethos_mailbox_common.values import secret as secret_values

from ...data.models import Page
from ...errors import BadRequestError

# What is kept of the HMAC, in hex: 128 bits.
MAC_CHARS = 32

P = TypeVar("P", bound=Page[Any])


class Cursors:
    def __init__(self) -> None:
        self._key = secrets.token_hex(32)

    def seal(self, cursor: str | None) -> str | None:
        """``cursor`` with its HMAC, as a list hands it out."""
        if cursor is None:
            return None
        return f"{cursor}.{self._mac(cursor)}"

    def sealed(self, page: P) -> P:
        """``page`` with its next cursor sealed."""
        return page.model_copy(update={"next_cursor": self.seal(page.next_cursor)})

    def open(self, sealed: str | None) -> str | None:
        """The cursor ``seal`` made. One made up or changed is refused."""
        if sealed is None:
            return None
        cursor, dot, mac = sealed.rpartition(".")
        held = dot and cursor and secret_values.same(mac, self._mac(cursor))
        if not held:
            raise BadRequestError("invalid cursor")
        return cursor

    def _mac(self, cursor: str) -> str:
        return secret_values.hmac_hex(self._key, cursor.encode())[:MAC_CHARS]
