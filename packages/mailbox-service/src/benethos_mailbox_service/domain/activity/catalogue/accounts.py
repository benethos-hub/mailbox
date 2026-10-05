"""Accounts and OAuth (docs/LOGGING.md 5.4). An account is named by its
address and its id. Never a credential, never the ``state`` or the code
of a sign-in."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import ClassVar

from ....data.models import Account
from ..base import Activity, Failure, account


@dataclass(frozen=True, kw_only=True)
class AccountConnected(Activity):
    name: ClassVar[str] = "connected"
    audited: ClassVar[bool] = True

    account: Account
    host: str | None

    def says(self) -> str:
        where = f" at {self.host}" if self.host else ""
        return (
            f"connected account {account(self.account)}: "
            f"{self.account.provider.value}{where}"
        )

    def touched(self) -> str | None:
        return self.account.id


@dataclass(frozen=True, kw_only=True)
class ConnectFailed(Failure):
    """The address as typed: the account was not stored."""

    name: ClassVar[str] = "connect_failed"
    audited: ClassVar[bool] = True

    address: str
    provider: str

    def says(self) -> str:
        return f"could not connect {self.address} ({self.provider})"


@dataclass(frozen=True, kw_only=True)
class AccountChanged(Activity):
    name: ClassVar[str] = "changed"
    audited: ClassVar[bool] = True

    account: Account
    # What changed: the display name, settings, the names of credentials.
    changed: tuple[str, ...]

    def says(self) -> str:
        return f"changed account {account(self.account)}: {', '.join(self.changed)}"

    def touched(self) -> str | None:
        return self.account.id


@dataclass(frozen=True, kw_only=True)
class AccountVerified(Activity):
    name: ClassVar[str] = "verified"
    audited: ClassVar[bool] = True

    account: Account

    def says(self) -> str:
        return f"verified account {account(self.account)}"

    def touched(self) -> str | None:
        return self.account.id


@dataclass(frozen=True, kw_only=True)
class AccountRemoved(Activity):
    name: ClassVar[str] = "removed"
    audited: ClassVar[bool] = True

    account: Account

    def says(self) -> str:
        return f"removed account {account(self.account)}"

    def touched(self) -> str | None:
        return self.account.id


@dataclass(frozen=True, kw_only=True)
class AccountReachable(Activity):
    """The account works again after it needed a sign-in or was
    unreachable. Logged when the status changes, not on every call."""

    name: ClassVar[str] = "reachable"

    account: Account

    def says(self) -> str:
        return f"reached account {account(self.account)} again"


@dataclass(frozen=True, kw_only=True)
class AccountNeedsSignIn(Activity):
    """A login or a token refresh was refused. Logged when the status
    changes."""

    name: ClassVar[str] = "needs_sign_in"
    level: ClassVar[int] = logging.WARNING

    account: Account
    reason: str | None

    def says(self) -> str:
        return f"found that account {account(self.account)} needs a new sign-in"

    def why(self) -> str | None:
        return self.reason


@dataclass(frozen=True, kw_only=True)
class AccountUnreachable(Activity):
    """Logged when the status changes, not on every failed call."""

    name: ClassVar[str] = "unreachable"
    level: ClassVar[int] = logging.WARNING

    account: Account
    reason: str | None

    def says(self) -> str:
        return f"could not reach account {account(self.account)}"

    def why(self) -> str | None:
        return self.reason


@dataclass(frozen=True, kw_only=True)
class OAuthStarted(Activity):
    name: ClassVar[str] = "oauth_started"
    audited: ClassVar[bool] = True

    provider: str
    # None to connect a new account.
    account: Account | None

    def says(self) -> str:
        if self.account is None:
            return f"started a sign-in with {self.provider} to connect an account"
        return f"started a sign-in with {self.provider} for {account(self.account)}"

    def touched(self) -> str | None:
        return self.account.id if self.account else None


@dataclass(frozen=True, kw_only=True)
class OAuthFinished(Activity):
    name: ClassVar[str] = "oauth_finished"
    audited: ClassVar[bool] = True

    provider: str
    account: Account
    # True when an existing account signed in again.
    again: bool

    def says(self) -> str:
        done = "signed in again" if self.again else "connected"
        return (
            f"finished the sign-in with {self.provider}: {account(self.account)} {done}"
        )

    def touched(self) -> str | None:
        return self.account.id


@dataclass(frozen=True, kw_only=True)
class OAuthFailed(Failure):
    name: ClassVar[str] = "oauth_failed"
    audited: ClassVar[bool] = True

    provider: str

    def says(self) -> str:
        return f"could not finish a sign-in with {self.provider}"


@dataclass(frozen=True, kw_only=True)
class TokenRefreshed(Activity):
    name: ClassVar[str] = "token_renewed"
    level: ClassVar[int] = logging.DEBUG

    account: Account

    def says(self) -> str:
        return f"refreshed the access token of {account(self.account)}"
