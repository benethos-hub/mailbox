"""How a Microsoft account signs in: the Microsoft identity platform v2.0
endpoints of a tenant, and the permissions this adapter needs of Graph.
"""

from __future__ import annotations

import re

from ....errors import BadRequestError
from ..protocols.oauth import Endpoints

# Who may sign in. A tenant id or domain names one organisation.
AUDIENCES = ("common", "consumers", "organizations")
_TENANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,254}$")

SCOPES = (
    # Who signed in, for the account's address.
    "openid",
    "email",
    "profile",
    # A refresh token, so the service keeps access.
    "offline_access",
    # What the adapter does. Mail.ReadWrite: read, flag, move, delete, draft.
    # Mail.Send: send.
    "https://graph.microsoft.com/Mail.ReadWrite",
    "https://graph.microsoft.com/Mail.Send",
)


def endpoints(tenant: str | None = None) -> Endpoints:
    """``common`` lets in personal and work or school accounts."""
    tenant = tenant or "common"
    if tenant not in AUDIENCES and not _TENANT.match(tenant):
        raise BadRequestError(f"not a Microsoft tenant: {tenant}")
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    return Endpoints(
        provider="microsoft",
        authorize_url=f"{base}/authorize",
        token_url=f"{base}/token",
        scopes=SCOPES,
    )
