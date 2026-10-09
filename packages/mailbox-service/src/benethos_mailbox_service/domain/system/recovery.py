"""The recovery key in the UI (docs/UI.md, 6.5).

The recovery key is the master key written out: whoever holds it opens
every stored secret. So only ``admin`` on every account sees it, and
only after typing the password again, and a code when the user has a
second factor (docs/AUTHENTICATION.md 7). It is never stored or logged.
The log says that it was shown, and to whom.
"""

from __future__ import annotations

from ...data.secrets import CredentialVault, encode_recovery
from ..activity import Actor
from ..activity import system as said
from ..auth import AuthService
from ..rights import Access


class RecoveryKey:
    def __init__(self, auth: AuthService, vault: CredentialVault) -> None:
        self._auth = auth
        self._vault = vault

    def needs_code(self, access: Access) -> bool:
        """Whether the caller confirms with a code of its second factor."""
        factors = self._auth.factors
        return factors is not None and factors.has(access.user_id)

    async def show(self, access: Access, password: str, code: str = "") -> str:
        access.require("show_recovery_key")
        await self._auth.confirm(access, password)
        if self.needs_code(access):
            self._auth.confirm_code(access, code)
        recovery = encode_recovery(self._vault.master_key())
        self._auth.activity.record(said.RecoveryKeyShown(by=Actor.of(access)))
        return recovery
