"""Rights in a form: the service rights and the rows of the grant editor,
read back into a list of names and into grants.

The service rights are ``service`` (groups or ``admin``) and
``service_more`` (further operation names). A grant row ``i`` carries
``g<i>_accounts`` (account ids or ``*``), ``g<i>_allow`` (groups),
``g<i>_more`` (further operation names), ``g<i>_recipients`` (one pattern
per line), ``g<i>_max`` (sends per day), ``g<i>_expires`` (a local date and
time, empty for never) and ``g<i>_remove``. ``grants``
says how many rows the form has. A row with neither accounts nor rights
is the empty one for adding and is left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from ...data.models import Account, Grant
from ...domain.rights import permissions
from .forms import FormError, first_problem

# The groups a grant names, and the rights of the service.
GROUP_NAMES = tuple(
    name for name in permissions.GROUPS if name not in permissions.SERVICE_GROUPS
)
SERVICE_NAMES = (permissions.ADMIN, *permissions.SERVICE_GROUPS)

# The groups the MCP server works with, and the tools each opens there, as
# the tool table of the MCP server's README documents them. A test compares
# the two, and the MCP server's tests compare that table with its tools.
MCP_TOOLS: dict[str, tuple[str, ...]] = {
    "mail.read": (
        "list_folders",
        "search_messages",
        "get_message",
        "get_attachment",
        "whats_new",
    ),
    "mail.write": ("update_messages", "create_folder"),
    "drafts": ("list_drafts", "create_draft", "update_draft", "delete_draft"),
    "send": ("send_message", "send_draft"),
}

# The rows of the rights in the editor: a caption and its groups.
GROUP_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Used by the MCP server", tuple(MCP_TOOLS)),
    (
        "Not used by the MCP server",
        tuple(name for name in GROUP_NAMES if name not in MCP_TOOLS),
    ),
)


def group_hint(name: str) -> str:
    """The tooltip of a group: its operations, and its MCP tools if any."""
    hint = ", ".join(permissions.GROUPS.get(name, ("every right on every account",)))
    if name in MCP_TOOLS:
        hint += ". MCP tools: " + ", ".join(MCP_TOOLS[name])
    elif name == "accounts.read":
        hint += ". The MCP server does not need it: it reads its accounts from /v1/me"
    return hint


_SPLIT = re.compile(r"[\s,;]+")

# Rows one editor may hold. The count comes from the form, so it is
# checked before anything loops over it.
MAX_ROWS = 100


class GrantFormError(FormError):
    """A grant row that is not a valid grant."""


@dataclass(frozen=True)
class GrantRow:
    """One grant as the editor shows it."""

    accounts: list[str]
    groups: list[str]
    more: str
    recipients: str
    # As the field shows it, empty for no limit.
    max_per_day: str
    # As the field shows it, local time to the minute, empty for never.
    expires: str = ""


EMPTY_ROW = GrantRow([], [], "", "", "")

# How a local date and time comes from and goes to the field.
EXPIRES_FORMAT = "%Y-%m-%dT%H:%M"


@dataclass(frozen=True)
class ServiceRow:
    """The service rights as the editor shows them: groups to tick, the
    rest as single operations."""

    groups: list[str]
    more: str


def service_of(names: list[str]) -> ServiceRow:
    """The editor's service rights for ``names``."""
    return ServiceRow(
        groups=[name for name in names if name in SERVICE_NAMES],
        more=" ".join(name for name in names if name not in SERVICE_NAMES),
    )


def read_service(form: Any) -> list[str]:
    """The service rights a submitted editor holds."""
    names = [str(v) for v in form.getlist("service") if v]
    names += [v for v in _SPLIT.split(str(form.get("service_more") or "")) if v]
    return list(dict.fromkeys(names))


def typed_service(form: Any) -> ServiceRow:
    """The service rights as they were submitted, unchecked."""
    return service_of(read_service(form))


def rows_of(grants: list[Grant]) -> list[GrantRow]:
    """The editor's rows for ``grants``, and an empty one to add a grant."""
    rows = [
        GrantRow(
            accounts=list(grant.accounts),
            groups=[name for name in grant.allow if name in GROUP_NAMES],
            more=" ".join(name for name in grant.allow if name not in GROUP_NAMES),
            recipients="\n".join(grant.recipients or []),
            max_per_day=(
                str(grant.max_sends_per_day)
                if grant.max_sends_per_day is not None
                else ""
            ),
            expires=(
                grant.expires_at.astimezone().strftime(EXPIRES_FORMAT)
                if grant.expires_at is not None
                else ""
            ),
        )
        for grant in grants
    ]
    return [*rows, EMPTY_ROW]


def typed_rows(form: Any) -> list[GrantRow]:
    """The rows as they were submitted, unchecked: a refused editor shows
    them again. Removed and empty rows are left out."""
    rows = []
    for index in range(min(_count(form), MAX_ROWS)):
        prefix = f"g{index}_"
        if form.get(prefix + "remove"):
            continue
        accounts = [str(v) for v in form.getlist(prefix + "accounts") if v]
        groups = [str(v) for v in form.getlist(prefix + "allow") if v]
        more = str(form.get(prefix + "more") or "").strip()
        if not accounts and not groups and not more:
            continue
        rows.append(
            GrantRow(
                accounts=accounts,
                groups=groups,
                more=more,
                recipients=str(form.get(prefix + "recipients") or "").strip(),
                max_per_day=str(form.get(prefix + "max") or "").strip(),
                expires=str(form.get(prefix + "expires") or "").strip(),
            )
        )
    return [*rows, EMPTY_ROW]


def _count(form: Any) -> int:
    """How many rows the form says it has."""
    try:
        return int(str(form.get("grants") or "0"))
    except ValueError:
        return 0


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
    count = _count(form)
    if count > MAX_ROWS:
        raise GrantFormError(f"an editor holds {MAX_ROWS} grants at most")
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
        expires = str(form.get(prefix + "expires") or "").strip()
        try:
            # The browser sends local time without a zone: the service's.
            expires_at = (
                datetime.fromisoformat(expires).astimezone() if expires else None
            )
        except ValueError:
            raise GrantFormError(
                f"grant {index + 1}: valid until must be a date and a time"
            ) from None
        try:
            grants.append(
                Grant(
                    accounts=accounts,
                    allow=allow,
                    recipients=recipients or None,
                    max_sends_per_day=int(limit) if limit else None,
                    expires_at=expires_at,
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
