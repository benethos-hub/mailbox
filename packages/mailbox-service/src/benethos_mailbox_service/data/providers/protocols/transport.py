"""What every wire protocol's wrapper meets below its library: a timeout,
TLS that fails, a socket that is not there. Translated once, here."""

from __future__ import annotations

import ssl
from collections.abc import Iterator
from contextlib import contextmanager

from ....errors import ProviderError, ProviderUnavailableError


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
