"""The editor of rights, as the pages of a user and of a role show it."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ...data.models import Grant
from ...domain.rights import Access
from ..services import get_accounts
from .grants import (
    GROUP_NAMES,
    GROUP_SECTIONS,
    SERVICE_NAMES,
    GrantRow,
    ServiceRow,
    account_choices,
    group_hint,
    rows_of,
    service_hint,
    service_of,
    typed_rows,
    typed_service,
)

# A refused editor comes back with this status, what was typed, the reason.
REFUSED = 400


def editor(
    request: Request,
    caller: Access,
    service: list[str],
    grants: list[Grant],
    form: Any = None,
) -> dict[str, Any]:
    """What the editor of rights needs: the service rights and the grant
    rows, as ``form`` held them, else those of ``service`` and ``grants``."""
    accounts = get_accounts(request)
    rows: list[GrantRow] = typed_rows(form) if form is not None else rows_of(grants)
    held: ServiceRow = typed_service(form) if form is not None else service_of(service)
    return {
        "service": held,
        "service_names": SERVICE_NAMES,
        "rows": rows,
        "account_choices": account_choices(accounts.list(caller), rows),
        "groups": GROUP_SECTIONS,
        "group_ops": {name: group_hint(name) for name in GROUP_NAMES},
        "service_ops": {name: service_hint(name) for name in SERVICE_NAMES},
    }
