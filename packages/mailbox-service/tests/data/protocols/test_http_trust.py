"""Every HTTP client of the service trusts the CAs of the system,
``SSL_CERT_FILE`` included, as the mail protocols do (review 2026-11-17,
finding 7)."""

from __future__ import annotations

import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from benethos_mailbox_service.data.protocols.http.base import new_client
from benethos_mailbox_service.data.protocols.http.server import ServerClient

NAME = "Mailbox trust test CA"


def _ca(folder: Path) -> Path:
    """A CA certificate of its own, in a PEM file."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, NAME)])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = folder / "ca.pem"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return path


def _context(client: httpx.AsyncClient) -> ssl.SSLContext:
    context = client._transport._pool._ssl_context  # type: ignore[attr-defined]
    assert isinstance(context, ssl.SSLContext)
    return context


def _trusts(context: ssl.SSLContext) -> bool:
    return any(
        ("commonName", NAME) in (pair for part in cert["subject"] for pair in part)
        for cert in context.get_ca_certs()
    )


async def test_every_http_client_trusts_ssl_cert_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(_ca(tmp_path)))
    shared = new_client(None, 5.0)
    server = ServerClient()
    try:
        assert _trusts(_context(shared))
        assert _trusts(_context(server._client))
    finally:
        await shared.aclose()
        await server.close()
