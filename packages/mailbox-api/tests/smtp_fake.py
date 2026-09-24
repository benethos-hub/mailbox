"""A stand-in for ``smtplib.SMTP``: the calls the SMTP module makes,
answered from memory, with smtplib's own exceptions."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Sent:
    sender: str
    recipients: list[str]
    raw: bytes


@dataclass
class FakeSmtpServer:
    """Shared by every connection of a test, like a server."""

    password: str = "secret"
    refuse: set[str] = field(default_factory=set)
    sent: list[Sent] = field(default_factory=list)
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    failure: Exception | None = None

    # the connection factory signature SmtpSession expects
    def __call__(self, server: Any, timeout: float) -> FakeSmtpConnection:
        self.calls.append(("connect", server.host, server.port, server.security))
        if self.failure is not None:
            raise self.failure
        return FakeSmtpConnection(self)


class FakeSmtpConnection:
    def __init__(self, server: FakeSmtpServer) -> None:
        self._server = server

    def login(self, username: str, password: str) -> None:
        self._server.calls.append(("login", username))
        if password != self._server.password:
            raise smtplib.SMTPAuthenticationError(535, b"authentication failed")

    def ehlo_or_helo_if_needed(self) -> None:
        return None

    def auth(self, mechanism: str, answer: Any, initial_response_ok: bool) -> None:
        self._server.calls.append(("auth", mechanism))
        if f"auth=Bearer {self._server.password}" not in answer():
            raise smtplib.SMTPAuthenticationError(535, b"invalid token")

    def sendmail(
        self, sender: str, recipients: list[str], raw: bytes
    ) -> dict[str, Any]:
        refused = {
            r: (550, b"no such user") for r in recipients if r in self._server.refuse
        }
        if len(refused) == len(recipients):
            raise smtplib.SMTPRecipientsRefused(refused)
        accepted = [r for r in recipients if r not in refused]
        self._server.sent.append(Sent(sender, accepted, raw))
        return refused

    def quit(self) -> None:
        self._server.calls.append(("quit",))
