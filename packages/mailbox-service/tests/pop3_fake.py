"""A stand-in for ``poplib.POP3``: the calls the POP3 module makes,
answered from memory, in the shapes poplib hands out, with its own
exception.

Like a real server, a session sees the mailbox as it was at the login,
and deletions take effect at QUIT.
"""

from __future__ import annotations

import poplib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakePop3Server:
    """One fake server, shared by every connection of a test.

    ``messages`` maps the unique id (UIDL) to the message, oldest first.
    ``calls`` records what the clients asked, e.g. ``("retr", 2)``.
    """

    password: str = "secret"
    messages: dict[str, bytes] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=lambda: ["TOP", "UIDL", "USER"])
    uidl: bool = True
    top: bool = True
    # The answer to a login, whatever the password, e.g. b"-ERR [IN-USE] busy".
    login_refusal: bytes | None = None
    # Raised by the next connection, e.g. ConnectionRefusedError.
    failure: Exception | None = None
    # A QUIT the server does not confirm.
    quit_refusal: bytes | None = None
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    connections: int = 0

    # the connection factory signature Pop3Session expects
    def __call__(self, server: Any, timeout: float) -> FakePop3Connection:
        self.calls.append(("connect", server.host, server.port, server.security))
        if self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure
        self.connections += 1
        return FakePop3Connection(self)

    def add(self, uid: str, raw: bytes) -> None:
        self.messages[uid] = raw


class FakePop3Connection:
    def __init__(self, server: FakePop3Server) -> None:
        self._server = server
        self._user: str | None = None
        # The mailbox as at the login: number -> (unique id, message).
        self._snapshot: dict[int, tuple[str, bytes]] = {}
        self._deleted: set[int] = set()
        self.closed = False

    # --- what poplib.POP3 offers ---------------------------------------------

    def capa(self) -> dict[str, list[str]]:
        self._call("capa")
        if not self._server.capabilities:
            raise poplib.error_proto(b"-ERR unknown command")
        return {name: [] for name in self._server.capabilities}

    def stls(self, context: Any = None) -> bytes:
        self._call("stls")
        return b"+OK begin TLS"

    def user(self, user: str) -> bytes:
        self._call("user", user)
        self._user = user
        return b"+OK"

    def pass_(self, password: str) -> bytes:
        self._call("pass")
        if self._server.login_refusal is not None:
            raise poplib.error_proto(self._server.login_refusal)
        if password != self._server.password:
            raise poplib.error_proto(b"-ERR [AUTH] invalid credentials")
        self._snapshot = {
            number: (uid, raw)
            for number, (uid, raw) in enumerate(self._server.messages.items(), start=1)
        }
        return b"+OK logged in"

    def uidl(self, which: int | None = None) -> tuple[bytes, list[bytes], int]:
        self._call("uidl")
        if not self._server.uidl:
            raise poplib.error_proto(b"-ERR unknown command")
        lines = [
            f"{number} {uid}".encode() for number, (uid, _) in self._live().items()
        ]
        return b"+OK", lines, sum(len(line) for line in lines)

    def list(self, which: int | None = None) -> Any:
        self._call("list", which)
        live = self._live()
        if which is not None:
            if which not in live:
                raise poplib.error_proto(b"-ERR no such message")
            return f"+OK {which} {len(live[which][1])}".encode()
        lines = [f"{n} {len(raw)}".encode() for n, (_, raw) in live.items()]
        return b"+OK", lines, sum(len(line) for line in lines)

    def top(self, which: int, howmuch: int) -> tuple[bytes, list[bytes], int]:
        self._call("top", which)
        if not self._server.top:
            raise poplib.error_proto(b"-ERR unknown command")
        raw = self._message(which)
        head = (
            raw.split(b"\r\n\r\n", 1)[0]
            if b"\r\n\r\n" in raw
            else raw.split(b"\n\n", 1)[0]
        )
        lines = head.replace(b"\r\n", b"\n").split(b"\n")
        return b"+OK", lines, len(head)

    def retr(self, which: int) -> tuple[bytes, list[bytes], int]:
        self._call("retr", which)
        raw = self._message(which)
        lines = raw.replace(b"\r\n", b"\n").split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        return b"+OK", lines, len(raw)

    def dele(self, which: int) -> bytes:
        self._call("dele", which)
        self._message(which)
        self._deleted.add(which)
        return b"+OK marked"

    def rset(self) -> bytes:
        self._call("rset")
        self._deleted.clear()
        return b"+OK"

    def quit(self) -> bytes:
        self._call("quit")
        if self.closed:
            raise OSError("closed")
        self.closed = True
        if self._server.quit_refusal is not None:
            raise poplib.error_proto(self._server.quit_refusal)
        for number in self._deleted:
            self._server.messages.pop(self._snapshot[number][0], None)
        return b"+OK bye"

    def close(self) -> None:
        self.closed = True

    # --- helpers --------------------------------------------------------------

    def _live(self) -> dict[int, tuple[str, bytes]]:
        return {n: m for n, m in self._snapshot.items() if n not in self._deleted}

    def _message(self, which: int) -> bytes:
        live = self._live()
        if which not in live:
            raise poplib.error_proto(b"-ERR no such message")
        return live[which][1]

    def _call(self, *call: Any) -> None:
        self._server.calls.append(call)
