"""Users, roles and tokens as records, under the caller's rights
(docs/PERMISSIONS.md).
"""

from __future__ import annotations

from .service import AccountRights, EffectiveRights, Sending, UserService

__all__ = [
    "AccountRights",
    "EffectiveRights",
    "Sending",
    "UserService",
]
