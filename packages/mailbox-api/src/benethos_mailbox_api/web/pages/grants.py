"""Grants in a form: the rows of the grant editor, read back into grants.

A row ``i`` carries ``g<i>_accounts`` (account ids or ``*``),
``g<i>_allow`` (groups or ``admin``), ``g<i>_more`` (further operation
names), ``g<i>_recipients`` (one pattern per line), ``g<i>_max`` (sends per
day) and ``g<i>_remove``. ``grants`` says how many rows the form has. A row
with neither accounts nor rights is the empty one for adding and is left
out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ...data.models import Account, Grant
from ...domain import permissions
from .forms import FormError, first_problem

GROUP_NAMES = (permissions.ADMIN, *permissions.GROUPS)
_SPLIT = re.compile(r"[\s,;]+")


class GrantFormError(FormError):
    """A grant row that is not a valid grant."""


@dataclass(frozen=True)
class GrantRow:
    """One grant as the editor shows it."""

    accounts: list[str]
    groups: list[str]
    more: str
    recipients: str
    max_sends_per_day: int | None


def rows_of(grants: list[Grant]) -> list[GrantRow]:
    """The editor's rows for ``grants``, and an empty one to add a grant."""
    rows = [
        GrantRow(
            accounts=list(grant.accounts),
            groups=[name for name in grant.allow if name in GROUP_NAMES],
            more=" ".join(name for name in grant.allow if name not in GROUP_NAMES),
            recipients="\n".join(grant.recipients or []),
            max_sends_per_day=grant.max_sends_per_day,
        )
        for grant in grants
    ]
    return [*rows, GrantRow([], [], "", "", None)]


def account_choices(accounts: list[Account], rows: list[GrantRow]) -> list[Any]:
    """The accounts a grant may name: every account the caller sees, and
    ids an existing grant names that it does not see (kept as they are)."""
    known = {account.id: account.email for account in accounts}
    for row in rows:
        for account_id in row.accounts:
            if account_id != "*" and account_id not in known:
                known[account_id] = account_id
    return sorted(known.items(), key=lambda item: item[1].lower())


def read_grants(form: Any) -> list[Grant]:
    """The grants a submitted editor holds."""
    try:
        count = int(str(form.get("grants") or "0"))
    except ValueError:
        count = 0
    grants = []
    for index in range(count):
        prefix = f"g{index}_"
        if form.get(prefix + "remove"):
            continue
        accounts = [str(v) for v in form.getlist(prefix + "accounts") if v]
        allow = [str(v) for v in form.getlist(prefix + "allow") if v]
        allow += [v for v in _SPLIT.split(str(form.get(prefix + "more") or "")) if v]
        if not accounts and not allow:
            continue
        recipients = [
            v for v in _SPLIT.split(str(form.get(prefix + "recipients") or "")) if v
        ]
        limit = str(form.get(prefix + "max") or "").strip()
        if limit and not limit.isdigit():
            raise GrantFormError(f"grant {index + 1}: sends per day must be a number")
        try:
            grants.append(
                Grant(
                    accounts=accounts,
                    allow=allow,
                    recipients=recipients or None,
                    max_sends_per_day=int(limit) if limit else None,
                )
            )
        except ValidationError as exc:
            problem = exc.errors()[0]
            if problem["loc"][0] == "recipients" and len(problem["loc"]) > 1:
                reason = f"{problem['input']} is not an address, *@domain or *"
            else:
                reason = first_problem(exc)
            raise GrantFormError(f"grant {index + 1}: {reason}") from None
    return grants
