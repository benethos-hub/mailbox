"""The recovery key in the UI (docs/UI.md, 6.5).

The recovery key is the master key written out: whoever holds it opens
every stored secret. So only ``admin`` on every account sees it, and
only after typing the password again. It is never stored or logged. The
log says that it was shown, and to whom.
"""

from __future__ import annotations

from ..data.secrets import CredentialVault, encode_recovery
from .activity import Actor
from .activity.catalogue.service import RecoveryKeyShown
from .auth import AuthService
from .rights import Access


class RecoveryKey:
    def __init__(self, auth: AuthService, vault: CredentialVault) -> None:
        self._auth = auth
        self._vault = vault

    async def show(self, access: Access, password: str) -> str:
        access.require("show_recovery_key")
        await self._auth.confirm(access, password)
        recovery = encode_recovery(self._vault.master_key())
        self._auth.activity.record(RecoveryKeyShown(by=Actor.of(access)))
        return recovery
