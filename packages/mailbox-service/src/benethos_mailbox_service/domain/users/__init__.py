"""Users, roles, tokens, passwords and second factors as records, under
the caller's rights (docs/mailbox-service/PERMISSIONS.md). One service each, the rules
they share in ``rules``, what a user may do in effect in ``effective``.
"""

from __future__ import annotations

from .effective import AccountRights, Effective, EffectiveRights, Sending
from .factors import DeviceAdded, SecondFactorService
from .passkeys import PasskeyService, PasskeySetup
from .passwords import OneTimePassword, PasswordService
from .roles import RoleService
from .rules import UserRules
from .service import BATCH_ACTIONS, BatchOutcome, Refused, UserService
from .tokens import TokenService
from .totp import TotpService, TotpSetup

__all__ = [
    "BATCH_ACTIONS",
    "AccountRights",
    "BatchOutcome",
    "DeviceAdded",
    "Effective",
    "EffectiveRights",
    "OneTimePassword",
    "PasskeyService",
    "PasskeySetup",
    "PasswordService",
    "Refused",
    "RoleService",
    "SecondFactorService",
    "Sending",
    "TokenService",
    "TotpService",
    "TotpSetup",
    "UserRules",
    "UserService",
]
