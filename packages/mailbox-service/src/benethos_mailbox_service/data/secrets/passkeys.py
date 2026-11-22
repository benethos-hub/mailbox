"""Passkeys, WebAuthn Level 2: the two ceremonies of a relying party
(docs/mailbox-service/AUTHENTICATION.md 4, 5).

A registration hands the browser a challenge and keeps the public key it
answers with. An authentication hands it a challenge for the keys a user
has and checks the signature it answers with. Both ask the authenticator
to verify its user, by a PIN or a fingerprint.

``fido2`` is imported here only. The rest of the service sees the records
of this module: the party, a ceremony begun, a credential as stored and
what an authentication proved.
"""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass

from fido2.server import Fido2Server
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialType,
    PublicKeyCredentialUserEntity,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

# Longer than any answer of a browser: a key, a signature and the client
# data. More is not read.
MAX_ANSWER = 16_384
# What a broken answer raises inside the library.
_BROKEN = (ValueError, KeyError, TypeError, AttributeError, IndexError, struct.error)


class PasskeyError(ValueError):
    """An answer that proves nothing: broken, for another challenge or
    origin, without the user verified, or with a wrong signature."""


@dataclass(frozen=True, slots=True)
class Party:
    """The relying party, the service as the browser reaches it: its host
    and its origin. A passkey works at this host only."""

    id: str
    origin: str
    name: str = "Mailbox"


@dataclass(frozen=True, slots=True)
class Begun:
    """A ceremony begun: the options the browser takes, as JSON, and the
    challenge the server keeps until the answer comes."""

    options: str
    challenge: str


@dataclass(frozen=True, slots=True)
class Credential:
    """A passkey as stored: its id, the attested credential data with its
    public key, and the counter of its last signature."""

    credential_id: bytes
    data: bytes
    sign_count: int = 0


@dataclass(frozen=True, slots=True)
class Asserted:
    """What an authentication proved: which passkey signed, and its
    counter now."""

    credential_id: bytes
    sign_count: int


def registration(
    party: Party, user_id: str, user_name: str, existing: Sequence[bytes]
) -> Begun:
    """The options to create a passkey for this user. A passkey of the
    user on the same authenticator is refused by the browser. The user's
    handle is the SHA-256 of its id: at most 64 bytes, as WebAuthn
    allows, and nothing a person typed."""
    handle = hashlib.sha256(user_id.encode()).digest()
    options, state = _server(party).register_begin(
        PublicKeyCredentialUserEntity(
            name=user_name, id=handle, display_name=user_name
        ),
        [_descriptor(c) for c in existing],
        resident_key_requirement=ResidentKeyRequirement.PREFERRED,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Begun(json.dumps(dict(options)["publicKey"]), state["challenge"])


def registered(party: Party, challenge: str, answer: str) -> Credential:
    """The passkey the browser created for ``challenge``."""
    response = _read(answer)
    try:
        data = _server(party).register_complete(_state(challenge), response)
    except _BROKEN as exc:
        raise PasskeyError("the passkey was not created") from exc
    created = data.credential_data
    if created is None:
        raise PasskeyError("the passkey was not created")
    return Credential(created.credential_id, bytes(created), data.counter)


def authentication(party: Party, credential_ids: Sequence[bytes]) -> Begun:
    """The options to sign in with one of these passkeys."""
    options, state = _server(party).authenticate_begin(
        [_descriptor(c) for c in credential_ids],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Begun(json.dumps(dict(options)["publicKey"]), state["challenge"])


def asserted(
    party: Party, challenge: str, credentials: Sequence[Credential], answer: str
) -> Asserted:
    """Which of ``credentials`` signed ``challenge``. Its counter is for the
    caller to compare: the library leaves it out."""
    response = _read(answer)
    known = [AttestedCredentialData(c.data) for c in credentials]
    try:
        _server(party).authenticate_complete(_state(challenge), known, response)
        read = AuthenticationResponse.from_dict(response)
    except _BROKEN as exc:
        raise PasskeyError("the passkey was not accepted") from exc
    return Asserted(read.raw_id, read.response.authenticator_data.counter)


def _server(party: Party) -> Fido2Server:
    # The origin must be the service's own, never a host below it.
    return Fido2Server(
        PublicKeyCredentialRpEntity(name=party.name, id=party.id),
        verify_origin=lambda origin: origin == party.origin,
    )


def _state(challenge: str) -> dict[str, object]:
    return {
        "challenge": challenge,
        "user_verification": UserVerificationRequirement.REQUIRED,
    }


def _descriptor(credential_id: bytes) -> PublicKeyCredentialDescriptor:
    return PublicKeyCredentialDescriptor(
        type=PublicKeyCredentialType.PUBLIC_KEY, id=credential_id
    )


def _read(answer: str) -> dict[str, object]:
    if len(answer) > MAX_ANSWER:
        raise PasskeyError("the answer of the browser is too long")
    try:
        found = json.loads(answer)
    except ValueError as exc:
        raise PasskeyError("the answer of the browser is no JSON") from exc
    if not isinstance(found, dict):
        raise PasskeyError("the answer of the browser is no object")
    return found
