"""Sending over SMTP. The only module that imports ``smtplib``.

Used through ``sender.SmtpSender`` by the adapters that have no sending of
their own: IMAP and POP3. One connection per send: a session is not
kept open between sends. Every library error leaves this module as a
``MailboxServiceError``.
"""

from __future__ import annotations

import re
import smtplib
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Any

from ...errors import (
    BadRequestError,
    MailboxServiceError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ..mail import fields
from . import transport
from .transport import Server, refuse_line_ends, text

DEFAULT_PORTS = {"tls": 465, "starttls": 587}
# What no address in MAIL FROM or RCPT TO may hold: a blank, which ends
# the path, or a control character. smtplib raises a ValueError for CR LF.
_NOT_IN_ADDRESS = re.compile(r"[\s\x00-\x1f\x7f]")

ConnectionFactory = Callable[[Server, float], Any]


@dataclass(frozen=True, slots=True)
class SmtpLogin:
    username: str
    secret: str
    auth: str = "password"  # or "xoauth2"


def _default_connection(server: Server, timeout: float) -> Any:
    address, context = server.endpoint()
    if server.security == "tls":
        return smtplib.SMTP_SSL(address, server.port, context=context, timeout=timeout)
    connection = smtplib.SMTP(address, server.port, timeout=timeout)
    try:
        connection.starttls(context=context)
    except BaseException:
        connection.close()
        raise
    return connection


class SmtpSession:
    def __init__(
        self,
        server: Server,
        timeout: float = 30.0,
        connection_factory: ConnectionFactory = _default_connection,
    ) -> None:
        self._server = server
        self._timeout = timeout
        self._factory = connection_factory

    def verify(self, login: SmtpLogin) -> None:
        """Log in and out again. Raises ``ProviderAuthError`` if the server
        rejects the credential."""
        with self._connected(login):
            pass

    def send(
        self, login: SmtpLogin, sender: str, recipients: list[str], raw: bytes
    ) -> list[str]:
        """Hand one message to the server. Returns the recipients it refused
        while it accepted others. If it accepts none, it raises.

        Domains go in punycode. A local part beyond ASCII needs SMTPUTF8
        of the server, else the message is refused before it is sent."""
        for address in (sender, *recipients):
            if _NOT_IN_ADDRESS.search(address):
                raise BadRequestError(
                    f"{address!r} is no address the mail server can take"
                )
        envelope = [fields.wire_address(a) for a in (sender, *recipients)]
        options = ["SMTPUTF8"] if any(not a.isascii() for a in envelope) else []
        with self._connected(login) as connection, translated():
            if options:
                connection.ehlo_or_helo_if_needed()
                if not connection.has_extn("smtputf8"):
                    raise BadRequestError(
                        "an address is not ASCII and the mail server does not "
                        "support SMTPUTF8"
                    )
            try:
                refused = connection.sendmail(
                    envelope[0], envelope[1:], raw, mail_options=options
                )
            except smtplib.SMTPRecipientsRefused as exc:
                raise BadRequestError(
                    "the mail server refused every recipient: "
                    + ", ".join(sorted(exc.recipients))
                ) from None
            except smtplib.SMTPSenderRefused as exc:
                raise BadRequestError(
                    f"the mail server refused the sender {exc.sender!r}"
                ) from None
        return sorted(refused)

    @contextmanager
    def _connected(self, login: SmtpLogin) -> Iterator[Any]:
        with translated():
            connection = self._factory(self._server, self._timeout)
        try:
            with translated():
                if login.auth == "xoauth2":
                    # SASL XOAUTH2: user, bearer token, separated by ^A,
                    # which neither may hold.
                    refuse_line_ends(
                        login.username, login.secret, what="the user name or token"
                    )
                    if "\1" in login.username + login.secret:
                        raise BadRequestError(
                            "the user name or token holds a control character"
                        )
                    answer = f"user={login.username}\1auth=Bearer {login.secret}\1\1"
                    connection.ehlo_or_helo_if_needed()
                    # A server that refuses the token sends a challenge with
                    # the reason and wants an empty line back (RFC 7628
                    # 3.2.2), then answers 535.
                    connection.auth(
                        "XOAUTH2",
                        lambda challenge=None: answer if challenge is None else "",
                        initial_response_ok=True,
                    )
                else:
                    if not (login.username + login.secret).isascii():
                        # smtplib writes AUTH in ASCII alone.
                        raise BadRequestError(
                            "the user name or password goes beyond ASCII, "
                            "which the login to the mail server cannot carry"
                        )
                    connection.login(login.username, login.secret)
            yield connection
        finally:
            try:
                connection.quit()
            except (smtplib.SMTPException, OSError):
                pass


def translated() -> AbstractContextManager[None]:
    """SMTP's errors as this project's."""
    return transport.translated(
        (smtplib.SMTPAuthenticationError, _login_refused),
        (
            smtplib.SMTPServerDisconnected,
            lambda exc: ProviderUnavailableError(
                f"the mail server dropped the connection: {exc}"
            ),
        ),
        (smtplib.SMTPResponseException, _answered),
        (
            smtplib.SMTPException,
            lambda exc: ProviderError(f"the mail server failed: {exc}"),
        ),
    )


def _login_refused(exc: smtplib.SMTPAuthenticationError) -> MailboxServiceError:
    if 400 <= exc.smtp_code < 500:
        # 454 4.7.0 and the like: try again later.
        return ProviderUnavailableError(
            f"the mail server refused the login for now ({exc.smtp_code})"
        )
    return ProviderAuthError("the mail server rejected the login")


def _answered(exc: smtplib.SMTPResponseException) -> MailboxServiceError:
    said = (
        text(exc.smtp_error)
        if isinstance(exc.smtp_error, bytes)
        else str(exc.smtp_error)
    )
    return ProviderError(f"the mail server answered {exc.smtp_code}: {said}")
