"""Sending over SMTP. The only module that imports ``smtplib``.

Used through ``sender.SmtpSender`` by the adapters that have no sending of
their own: IMAP, and later POP3. One connection per send: a session is not
kept open between sends. Every library error leaves this module as a
``MailboxServiceError``.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ....errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)
from ...mail.fields import ascii_domain
from .transport import transport_errors

DEFAULT_PORTS = {"tls": 465, "starttls": 587}

ConnectionFactory = Callable[["SmtpServer", float], Any]


@dataclass(frozen=True)
class SmtpServer:
    host: str
    port: int
    security: str  # "tls" or "starttls"


@dataclass(frozen=True)
class SmtpLogin:
    username: str
    secret: str
    auth: str = "password"  # or "xoauth2"


def _default_connection(server: SmtpServer, timeout: float) -> Any:
    context = ssl.create_default_context()
    if server.security == "tls":
        return smtplib.SMTP_SSL(
            server.host, server.port, context=context, timeout=timeout
        )
    connection = smtplib.SMTP(server.host, server.port, timeout=timeout)
    try:
        connection.starttls(context=context)
    except BaseException:
        connection.close()
        raise
    return connection


class SmtpSession:
    def __init__(
        self,
        server: SmtpServer,
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
        envelope = [_on_the_wire(sender), *(_on_the_wire(r) for r in recipients)]
        options = ["SMTPUTF8"] if any(not a.isascii() for a in envelope) else []
        with self._connected(login) as connection, _errors():
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
        with _errors():
            connection = self._factory(self._server, self._timeout)
        try:
            with _errors():
                if login.auth == "xoauth2":
                    # SASL XOAUTH2: user, bearer token, separated by ^A.
                    answer = f"user={login.username}\1auth=Bearer {login.secret}\1\1"
                    connection.ehlo_or_helo_if_needed()
                    connection.auth(
                        "XOAUTH2",
                        lambda challenge=None: answer,
                        initial_response_ok=True,
                    )
                else:
                    connection.login(login.username, login.secret)
            yield connection
        finally:
            try:
                connection.quit()
            except (smtplib.SMTPException, OSError):
                pass


def _on_the_wire(address: str) -> str:
    try:
        return ascii_domain(address)
    except UnicodeError:
        raise BadRequestError(f"the domain of {address} cannot be encoded") from None


@contextmanager
def _errors() -> Iterator[None]:
    with transport_errors():
        try:
            yield
        except (BadRequestError, ProviderAuthError, ProviderError):
            raise
        except UnicodeError as exc:
            raise BadRequestError(f"an address cannot go on the wire: {exc}") from None
        except smtplib.SMTPAuthenticationError:
            raise ProviderAuthError("the mail server rejected the login") from None
        except smtplib.SMTPServerDisconnected as exc:
            raise ProviderUnavailableError(
                f"the mail server dropped the connection: {exc}"
            ) from None
        except (smtplib.SMTPDataError, smtplib.SMTPResponseException) as exc:
            text = (
                exc.smtp_error.decode(errors="replace")
                if isinstance(exc.smtp_error, bytes)
                else str(exc.smtp_error)
            )
            raise ProviderError(
                f"the mail server answered {exc.smtp_code}: {text}"
            ) from None
        except smtplib.SMTPException as exc:
            raise ProviderError(f"the mail server failed: {exc}") from None
