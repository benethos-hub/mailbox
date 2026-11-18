"""Passkeys, the second method of the second factor: a user's key pairs
on its devices or in a password manager (docs/AUTHENTICATION.md 4, 5).

This module begins and checks the ceremonies and keeps the passkeys. The
frame they belong to is ``factors``, who may add or remove one
``domain/users/passkeys.py``. The browser's side is the web layer's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

# Named apart from a secret of its own.
from benethos_mailbox_common.values import secret as secret_values

from ...common.clock import utc_now
from ...data.models import Passkey, User
from ...data.secrets import Begun, Party, PasskeyError, passkeys
from ...data.storage import PasskeyRepository, StoredPasskey
from ...errors import BadRequestError
from .devices import checked_name


@dataclass(frozen=True, slots=True)
class Answer:
    """What the browser answered to a challenge the server kept: the party
    it answered, the challenge and the answer as JSON."""

    party: Party
    challenge: str
    answer: str


class Passkeys:
    """The passkeys of every user: added, checked, removed."""

    def __init__(
        self, repository: PasskeyRepository, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._repository = repository
        self._clock = clock

    def passkeys(self, user_id: str) -> list[Passkey]:
        """Oldest first, never a key."""
        return [_shown(p) for p in self._repository.passkeys(user_id)]

    def ids(self, user_id: str) -> list[str]:
        return [p.id for p in self._repository.passkeys(user_id)]

    def passkey(self, user_id: str, passkey_id: str) -> Passkey | None:
        found = [p for p in self.passkeys(user_id) if p.id == passkey_id]
        return found[0] if found else None

    def checked_name(
        self, user_id: str, name: str, passkey_id: str | None = None
    ) -> str:
        """``name`` as a passkey of the user may be called, by the rules of
        every device. A new passkey needs a free place too."""
        held = [(p.id, p.name) for p in self._repository.passkeys(user_id)]
        return checked_name(name, held, passkey_id, "passkey")

    def registration(self, user: User, party: Party) -> Begun:
        """The options to create a new passkey of ``user`` at ``party``. The
        browser refuses one on an authenticator that holds one already."""
        held = [p.credential_id for p in self._repository.passkeys(user.id)]
        return passkeys.registration(party, user.id, user.name, held)

    def add(self, user_id: str, name: str, answer: Answer) -> None:
        """Store the passkey the browser created for the challenge."""
        try:
            created = passkeys.registered(answer.party, answer.challenge, answer.answer)
        except PasskeyError as exc:
            raise BadRequestError(f"{exc}: try again") from None
        self._repository.add(
            user_id,
            StoredPasskey(
                id=secret_values.new_id("psk"),
                name=name,
                credential_id=created.credential_id,
                credential=created.data,
                created_at=self._clock(),
                sign_count=created.sign_count,
            ),
        )

    def challenge(self, user_id: str, party: Party) -> Begun | None:
        """The options to sign with one of the user's passkeys at
        ``party``. None for a user without one."""
        held = [p.credential_id for p in self._repository.passkeys(user_id)]
        return passkeys.authentication(party, held) if held else None

    def check(self, user_id: str, answer: Answer) -> str | None:
        """The name of the user's passkey that signed the challenge, its
        signature not taken before. It is used up. None for none."""
        stored = self._repository.passkeys(user_id)
        known = [
            passkeys.Credential(p.credential_id, p.credential, p.sign_count)
            for p in stored
        ]
        try:
            proved = passkeys.asserted(
                answer.party, answer.challenge, known, answer.answer
            )
        except PasskeyError:
            return None
        for passkey in stored:
            if passkey.credential_id == proved.credential_id and self._repository.used(
                user_id, passkey.id, proved.sign_count, self._clock()
            ):
                return passkey.name
        return None

    def rename(self, user_id: str, passkey_id: str, name: str) -> None:
        self._repository.rename(user_id, passkey_id, name)

    def remove(self, user_id: str, passkey_id: str) -> bool:
        return self._repository.remove(user_id, passkey_id)

    def remove_all(self, user_id: str) -> bool:
        return self._repository.remove_all(user_id)


def _shown(passkey: StoredPasskey) -> Passkey:
    return Passkey(
        id=passkey.id,
        name=passkey.name,
        created_at=passkey.created_at,
        last_used_at=passkey.last_used_at,
    )
