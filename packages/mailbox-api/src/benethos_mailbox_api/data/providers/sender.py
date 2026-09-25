"""Sending for adapters without sending of their own, such as IMAP and POP3.

An adapter holds one ``SmtpSender``, or none when the account has no SMTP
server. The sender reads the ``smtp_*`` settings, logs in with the account's
credential and goes through the account's ``Guard``. What the adapter does
after a send, such as a copy in the sent folder, stays with the adapter.
"""

from __future__ import annotations

from collections.abc import Callable

from . import rules
from .base import ProviderSettings
from .guard import Guard
from .protocols.smtp import DEFAULT_PORTS, SmtpLogin, SmtpServer, SmtpSession

SmtpFactory = Callable[[SmtpServer], SmtpSession]


class SmtpSender:
    def __init__(
        self,
        session: SmtpSession,
        username: str,
        auth: str,
        secret: Callable[[], str],
        guard: Guard,
    ) -> None:
        self._session = session
        self._username = username
        self._auth = auth
        self._secret = secret
        self._guard = guard

    @classmethod
    def from_settings(
        cls,
        settings: ProviderSettings,
        username: str,
        auth: str,
        secret: Callable[[], str],
        guard: Guard,
        factory: SmtpFactory = SmtpSession,
    ) -> SmtpSender | None:
        """From ``smtp_host``, ``smtp_port``, ``smtp_security`` and
        ``smtp_username`` (else ``username``). None when the account has no
        SMTP server: it cannot send."""
        host = settings.get("smtp_host")
        if not host:
            return None
        security = rules.encrypted(settings, "smtp_security", "SMTP")
        port = rules.port_of(settings, "smtp_port", DEFAULT_PORTS[security])
        server = SmtpServer(host=str(host), port=port, security=security)
        return cls(
            factory(server),
            str(settings.get("smtp_username") or username),
            auth,
            secret,
            guard,
        )

    def send(self, raw: bytes, sender: str, recipients: list[str]) -> list[str]:
        """Send, blocking. The recipients the server refused."""
        # The same credential as the mailbox: no new attempt until it changes.
        return self._guard.once(
            lambda: self._session.send(self._login(), sender, recipients, raw)
        )

    def verify(self) -> None:
        """Log in and out, blocking."""
        self._guard.once(lambda: self._session.verify(self._login()))

    def _login(self) -> SmtpLogin:
        """The credential, decrypted for this one use."""
        return SmtpLogin(self._username, self._secret(), self._auth)
