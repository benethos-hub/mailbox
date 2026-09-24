"""Sending over SMTP. The only module that imports ``smtplib``.

Used by the adapters that have no sending of their own: IMAP, and later
POP3. One connection per send; a session is not kept open between sends.
Every library error leaves this module as a ``MailboxApiError``.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ...errors import (
    BadRequestError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

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
    connection.starttls(context=context)
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
        while it accepted others; if it accepts none, raises."""
        with self._connected(login) as connection, _errors():
            try:
                refused = connection.sendmail(sender, recipients, raw)
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


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (BadRequestError, ProviderAuthError, ProviderError):
        raise
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
    except TimeoutError:
        raise ProviderUnavailableError(
            "the mail server did not answer in time"
        ) from None
    except (ssl.SSLError, ssl.CertificateError) as exc:
        raise ProviderError(f"TLS with the mail server failed: {exc}") from None
    except OSError as exc:
        raise ProviderUnavailableError(
            f"the mail server is not reachable: {exc}"
        ) from None
