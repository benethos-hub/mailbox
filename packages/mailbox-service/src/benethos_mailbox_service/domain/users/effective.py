"""What a user may do in effect: its direct grants and those of its
roles together, per account, with the sends left today."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ...data.models import AccountStatus, Capability
from ..accounts import Adapters
from ..rights import Access

# Read mail, and send it to any address: what an injected instruction in a
# mail needs to carry data out (CONCEPT 7.7). A warning, not a block.
READ_AND_SEND_ANYWHERE = "read_and_send_anywhere"


@dataclass(frozen=True)
class Sending:
    """One grant that allows sending from an account: to whom, how many in
    24 hours, and how many of those are left now (PERMISSIONS.md 8.8)."""

    recipients: list[str] | None  # None: to anyone
    max_sends_per_day: int | None  # None: no limit
    sends_left: int | None  # None: no limit


@dataclass(frozen=True)
class AccountRights:
    """One account the caller may act on, and what it may do there."""

    id: str
    email: str
    display_name: str | None
    operations: list[str]
    warnings: list[str]
    # One entry per grant that allows sending here. A send passes when one
    # of them allows it. Empty when no grant allows sending.
    sending: list[Sending]
    status: AccountStatus = AccountStatus.CONNECTED
    capabilities: list[Capability] = field(default_factory=list)


@dataclass(frozen=True)
class EffectiveRights:
    user_id: str
    name: str
    accounts: list[AccountRights]
    operations: list[str]
    roles: list[str] = field(default_factory=list)


class Effective:
    def __init__(
        self, adapters: Adapters, sent: Callable[[str, str], int] | None = None
    ) -> None:
        """``sent``: how many mails a user sent from an account in the last
        24 hours, by user and account id."""
        self._adapters = adapters
        self._sent = sent

    def rights(
        self, access: Access, visible_to: Access | None, roles: list[str]
    ) -> EffectiveRights:
        """What ``access`` allows, on the accounts ``visible_to`` sees,
        every account without it."""
        accounts = []
        for account_id in self._adapters.ids():
            if visible_to is not None and not visible_to.sees(account_id):
                continue
            operations = access.operations_on(account_id)
            if operations:
                account = self._adapters.record(account_id)
                accounts.append(
                    AccountRights(
                        id=account.id,
                        email=account.email,
                        display_name=account.display_name,
                        operations=sorted(operations),
                        warnings=_warnings(access, account_id, operations),
                        sending=self._sending(access, account_id),
                        status=account.status,
                        capabilities=self._adapters.offered(account_id),
                    )
                )
        return EffectiveRights(
            user_id=access.user_id,
            name=access.name,
            accounts=accounts,
            operations=sorted(access.general_operations()),
            roles=list(roles),
        )

    def _sending(self, access: Access, account_id: str) -> list[Sending]:
        limits = access.sending_limits(account_id)
        sent = (
            self._sent(access.user_id, account_id)
            if self._sent is not None and any(x.max_per_day for x in limits)
            else 0
        )
        return [
            Sending(
                recipients=list(limit.recipients)
                if limit.recipients is not None
                else None,
                max_sends_per_day=limit.max_per_day,
                sends_left=max(0, limit.max_per_day - sent)
                if limit.max_per_day is not None
                else None,
            )
            for limit in limits
        ]


def _warnings(access: Access, account_id: str, operations: frozenset[str]) -> list[str]:
    if "get_message" in operations and access.sends_anywhere(account_id):
        return [READ_AND_SEND_ANYWHERE]
    return []
