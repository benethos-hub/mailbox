"""The recovery key in the UI (docs/UI.md, 6.5).

The recovery key is the master key written out: whoever holds it opens
every stored secret. So only ``admin`` on every account sees it, and
only after typing the password again. It is never stored or logged. The
log says that it was shown, and to whom.
"""

from __future__ import annotations

import logging

from ..data.secrets import CredentialVault, encode_recovery
from .access import Access
from .auth import AuthService

log = logging.getLogger(__name__)


class RecoveryKey:
    def __init__(self, auth: AuthService, vault: CredentialVault) -> None:
        self._auth = auth
        self._vault = vault

    def may_show(self, access: Access) -> bool:
        return access.allows("show_recovery_key")

    async def show(self, access: Access, password: str) -> str:
        access.require("show_recovery_key")
        await self._auth.confirm(access, password)
        recovery = encode_recovery(self._vault.master_key())
        log.warning(
            "the recovery key was shown in the UI to %s (%s)",
            access.name,
            access.user_id,
        )
        return recovery
