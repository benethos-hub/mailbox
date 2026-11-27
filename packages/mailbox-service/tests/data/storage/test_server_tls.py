"""What libpq is told of TLS, by the setting and the host: a host other
than this one only with a checked certificate and name, this one where
the server offers it, and none when it is switched off. Against the
server in tests/postgres/test_server_tls.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_service.data.storage.sql.server_engine import tls_arguments


@pytest.mark.parametrize("host", ["db.example.org", "192.0.2.7", "::ffff:192.0.2.7"])
def test_another_host_only_with_a_checked_certificate(host: str) -> None:
    assert tls_arguments(host, "verify", None) == {
        "sslmode": "verify-full",
        "sslrootcert": "system",
    }
    ca = Path("ca.pem")
    assert tls_arguments(host, "verify", ca) == {
        "sslmode": "verify-full",
        "sslrootcert": str(ca),
    }


@pytest.mark.parametrize(
    "host", ["localhost", "LOCALHOST", "127.0.0.1", "127.8.0.1", "::1"]
)
def test_this_host_where_the_server_offers_it(host: str) -> None:
    assert tls_arguments(host, "verify", None) == {"sslmode": "prefer"}


@pytest.mark.parametrize("host", ["db.example.org", "127.0.0.1"])
def test_off_never(host: str) -> None:
    assert tls_arguments(host, "off", Path("ca.pem")) == {"sslmode": "disable"}
