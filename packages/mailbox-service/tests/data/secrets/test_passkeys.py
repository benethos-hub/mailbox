"""Passkeys, the ceremonies of a relying party (docs/AUTHENTICATION.md 4,
5): what the service checks in a browser's answer."""

from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from benethos_mailbox_service.data.secrets import passkeys
from benethos_mailbox_service.data.secrets.passkeys import Party, PasskeyError

from ...passkey_fake import Authenticator, challenge_of

PARTY = Party("mail.example.org", "https://mail.example.org")


def _created(device: Authenticator) -> passkeys.Credential:
    begun = passkeys.registration(PARTY, "usr_1", "anna", [])
    return passkeys.registered(PARTY, begun.challenge, device.create(begun.options))


def test_a_registration_asks_the_user_to_be_verified() -> None:
    begun = passkeys.registration(PARTY, "usr_1", "anna", [b"\x01" * 16])
    options = json.loads(begun.options)
    assert options["rp"] == {"name": "Mailbox", "id": "mail.example.org"}
    assert options["user"]["name"] == "anna"
    # A digest of the id: WebAuthn takes 64 bytes at most.
    assert len(passkeys.from_base64url(options["user"]["id"])) == 32
    assert options["authenticatorSelection"]["userVerification"] == "required"
    assert options["excludeCredentials"] == [
        {"type": "public-key", "id": passkeys.to_base64url(b"\x01" * 16)}
    ]
    assert challenge_of(begun.options) == passkeys.from_base64url(begun.challenge)


def test_a_created_passkey_signs_in() -> None:
    device = Authenticator()
    credential = _created(device)
    assert credential.credential_id == device.credential_id
    begun = passkeys.authentication(PARTY, [credential.credential_id])
    assert json.loads(begun.options)["userVerification"] == "required"
    proved = passkeys.asserted(
        PARTY, begun.challenge, [credential], device.get(begun.options)
    )
    assert proved == passkeys.Asserted(device.credential_id, 1)


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "https://sub.mail.example.org", "http://mail.example.org"],
)
def test_another_origin_creates_and_signs_nothing(origin: str) -> None:
    good = Authenticator()
    credential = _created(good)
    begun = passkeys.registration(PARTY, "usr_1", "anna", [])
    with pytest.raises(PasskeyError):
        passkeys.registered(
            PARTY, begun.challenge, Authenticator(origin=origin).create(begun.options)
        )
    begun = passkeys.authentication(PARTY, [credential.credential_id])
    good.origin = origin
    with pytest.raises(PasskeyError):
        passkeys.asserted(PARTY, begun.challenge, [credential], good.get(begun.options))


def test_an_answer_to_another_challenge_proves_nothing() -> None:
    device = Authenticator()
    credential = _created(device)
    first = passkeys.authentication(PARTY, [credential.credential_id])
    second = passkeys.authentication(PARTY, [credential.credential_id])
    with pytest.raises(PasskeyError):
        passkeys.asserted(
            PARTY, second.challenge, [credential], device.get(first.options)
        )


def test_a_user_not_verified_creates_and_signs_nothing() -> None:
    begun = passkeys.registration(PARTY, "usr_1", "anna", [])
    with pytest.raises(PasskeyError):
        passkeys.registered(
            PARTY, begun.challenge, Authenticator(verifies=False).create(begun.options)
        )
    device = Authenticator()
    credential = _created(device)
    device.verifies = False
    begun = passkeys.authentication(PARTY, [credential.credential_id])
    with pytest.raises(PasskeyError):
        passkeys.asserted(
            PARTY, begun.challenge, [credential], device.get(begun.options)
        )


def test_a_signature_of_another_key_proves_nothing() -> None:
    device = Authenticator()
    credential = _created(device)
    begun = passkeys.authentication(PARTY, [credential.credential_id])
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(PasskeyError):
        passkeys.asserted(
            PARTY, begun.challenge, [credential], device.get(begun.options, key=other)
        )


def test_a_passkey_the_user_does_not_have_proves_nothing() -> None:
    device = Authenticator()
    _created(device)
    stranger = Authenticator()
    stranger_credential = _created(stranger)
    begun = passkeys.authentication(PARTY, [stranger_credential.credential_id])
    credential = _created(Authenticator())
    with pytest.raises(PasskeyError):
        passkeys.asserted(
            PARTY, begun.challenge, [credential], device.get(begun.options)
        )


@pytest.mark.parametrize(
    "answer",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"id": "AA", "rawId": "AA", "type": "public-key", "response": {}}',
        '{"id": 1, "rawId": [], "response": "x"}',
        "x" * (passkeys.MAX_ANSWER + 1),
    ],
)
def test_a_broken_answer_is_refused(answer: str) -> None:
    credential = _created(Authenticator())
    begun = passkeys.authentication(PARTY, [credential.credential_id])
    with pytest.raises(PasskeyError):
        passkeys.asserted(PARTY, begun.challenge, [credential], answer)
    begun = passkeys.registration(PARTY, "usr_1", "anna", [])
    with pytest.raises(PasskeyError):
        passkeys.registered(PARTY, begun.challenge, answer)
