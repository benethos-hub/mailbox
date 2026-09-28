"""What every wire protocol's wrapper meets below its library: the server
it connects to, a timeout, TLS that fails, a socket that is not there, a
value beyond ASCII. Translated once, here."""

from __future__ import annotations

import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from ...errors import BadRequestError, ProviderError, ProviderUnavailableError

# The address a connection to a host goes to, checked when it is made.
# Raises when the host may not be connected to.
Pick = Callable[[str, int], str]


class _NamedContext(ssl.SSLContext):
    """Verifies the certificate against one host name, whatever address
    the library connected to and hands on as the name."""

    name: str

    def wrap_socket(self, sock: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["server_hostname"] = self.name
        return super().wrap_socket(sock, *args, **kwargs)


def tls_context(host: str) -> ssl.SSLContext:
    """A client context as ``ssl.create_default_context`` makes it, that
    checks the certificate of ``host`` even on a connection to an address."""
    context = _NamedContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_default_certs()
    context.name = host
    return context


def connect_to(host: str, port: int, pick: Pick | None) -> str:
    """Where a connection to ``host`` goes: the address ``pick`` checked,
    or the name itself without a check."""
    return pick(host, port) if pick is not None else host


@dataclass(frozen=True)
class Server:
    """A mail server, as IMAP and SMTP connect to it."""

    host: str
    port: int
    security: str  # "tls" or "starttls"
    # Checks the host at each connection. Without: connect by name.
    pick: Pick | None = field(default=None, compare=False)

    def endpoint(self) -> tuple[str, ssl.SSLContext]:
        """The address to connect to, checked now, and the TLS context
        that verifies the certificate of the host."""
        return connect_to(self.host, self.port, self.pick), tls_context(self.host)


@contextmanager
def transport_errors() -> Iterator[None]:
    """The failures of the transport as this project's errors. A wrapper
    handles its library's own exceptions inside, this the rest."""
    try:
        yield
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
    except UnicodeError:
        # The libraries write commands in ASCII. Never the error's text: it
        # quotes the character, which may be part of a secret.
        raise BadRequestError(
            "a value beyond ASCII cannot go to the mail server"
        ) from None
