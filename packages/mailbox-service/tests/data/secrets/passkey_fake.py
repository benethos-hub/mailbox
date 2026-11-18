"""A passkey in software: it answers the options of the service as a
browser with an authenticator would, as JSON. Its switches make the
answers the service must refuse."""

from __future__ import annotations

import json
import secrets
import struct
from dataclasses import dataclass, field
from hashlib import sha256

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2 import cbor
from fido2.cose import ES256
from fido2.utils import websafe_decode, websafe_encode

# User present, user verified, attested credential data.
_PRESENT = 0x01
_VERIFIED = 0x04
_ATTESTED = 0x40


@dataclass
class Authenticator:
    """One passkey on one authenticator. ``origin`` is where the browser
    runs. A synced passkey keeps its counter at zero."""

    origin: str = "https://mail.example.org"
    verifies: bool = True
    synced: bool = False
    counter: int = 0
    credential_id: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )

    def create(self, options: str) -> str:
        """The answer to the options of a registration."""
        found = json.loads(options)
        cose = ES256.from_cryptography_key(self.key.public_key())
        attested = (
            bytes(16)
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + cbor.encode(cose)
        )
        data = self._data(found["rp"]["id"], _ATTESTED, attested)
        attestation = cbor.encode({"fmt": "none", "attStmt": {}, "authData": data})
        client = self._client("webauthn.create", found["challenge"])
        return self._answer(
            {
                "clientDataJSON": websafe_encode(client),
                "attestationObject": websafe_encode(attestation),
            }
        )

    def get(
        self, options: str, *, key: ec.EllipticCurvePrivateKey | None = None
    ) -> str:
        """The answer to the options of an authentication, signed with
        this passkey's key or with ``key``."""
        found = json.loads(options)
        if not self.synced:
            self.counter += 1
        data = self._data(found["rpId"], 0)
        client = self._client("webauthn.get", found["challenge"])
        signer = key or self.key
        signature = signer.sign(
            data + sha256(client).digest(), ec.ECDSA(hashes.SHA256())
        )
        return self._answer(
            {
                "clientDataJSON": websafe_encode(client),
                "authenticatorData": websafe_encode(data),
                "signature": websafe_encode(signature),
            }
        )

    def _data(self, rp_id: str, flags: int, attested: bytes = b"") -> bytes:
        flags |= _PRESENT | (_VERIFIED if self.verifies else 0)
        return (
            sha256(rp_id.encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.counter)
            + attested
        )

    def _client(self, kind: str, challenge: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": self.origin}
        ).encode()

    def _answer(self, response: dict[str, str]) -> str:
        return json.dumps(
            {
                "id": websafe_encode(self.credential_id),
                "rawId": websafe_encode(self.credential_id),
                "type": "public-key",
                "response": response,
                "clientExtensionResults": {},
            }
        )


def challenge_of(options: str) -> bytes:
    return websafe_decode(json.loads(options)["challenge"])
