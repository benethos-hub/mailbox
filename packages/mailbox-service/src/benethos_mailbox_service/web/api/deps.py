"""Dependencies shared by the routers: who is calling, the services (from
``web.services``) and the search parameters.

The web layer only establishes the caller. What the caller may do is decided
in the domain.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AwareDatetime

from ...data.models import (
    SEARCH_TEXT_PATTERN,
    MessageFilter,
    SendFilter,
    SendOutcome,
)
from ...domain.rights import Access
from ..limits import signed_in
from ..services import (
    Accounts,
    Auth,
    Discoverer,
    Mailbox,
    Passwords,
    Roles,
    Tokens,
    Users,
    Webhooks,
)
from ..urls import client_address

__all__ = [
    "Accounts",
    "Caller",
    "Discoverer",
    "Limit",
    "Mailbox",
    "Passwords",
    "Roles",
    "Search",
    "SendSearch",
    "Since",
    "Tokens",
    "Users",
    "Webhooks",
    "authenticate",
]

# How many items a list answers with at most. The default is 50.
Limit = Annotated[int, Query(ge=1, le=200)]

# A point in the change feed, from the ``state`` of an earlier answer.
Since = Annotated[
    str | None,
    Query(
        description=(
            "The `state` of an earlier answer. Without it the answer holds "
            "no changes, only the current state to start from."
        )
    ),
]

_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


async def authenticate(
    request: Request,
    auth: Auth,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Access:
    # On the event loop, not in a worker thread: two requests never check
    # a token and count a failed attempt at the same time.
    presented = credentials.credentials if credentials else None
    access = auth.authenticate(presented, source=client_address(request))
    signed_in(request, f"token:{access.credential_id}", access)
    return access


Caller = Annotated[Access, Depends(authenticate)]


# --- search parameters, shared by the lists ----------------------------------------


def message_filter(
    q: Annotated[
        str | None,
        Query(
            pattern=SEARCH_TEXT_PATTERN,
            description="Text anywhere: headers and body",
        ),
    ] = None,
    sender: Annotated[
        str | None,
        Query(
            alias="from",
            pattern=SEARCH_TEXT_PATTERN,
            description="Part of the sender's address or name",
        ),
    ] = None,
    to: Annotated[
        str | None,
        Query(pattern=SEARCH_TEXT_PATTERN, description="Part of a To address"),
    ] = None,
    subject: Annotated[
        str | None,
        Query(pattern=SEARCH_TEXT_PATTERN, description="Part of the subject"),
    ] = None,
    after: Annotated[
        date | None, Query(description="From this day on, e.g. 2026-09-01")
    ] = None,
    before: Annotated[
        date | None, Query(description="Up to this day, not including it")
    ] = None,
    unread: bool | None = None,
    starred: bool | None = None,
    has_attachments: bool | None = None,
) -> MessageFilter:
    return MessageFilter(
        text=q,
        sender=sender,
        to=to,
        subject=subject,
        after=after,
        before=before,
        unread=unread,
        starred=starred,
        has_attachments=has_attachments,
    )


Search = Annotated[MessageFilter, Depends(message_filter)]


def send_filter(
    user: Annotated[
        str | None, Query(description="A user id: the sends of that user")
    ] = None,
    outcome: SendOutcome | None = None,
    recipient: Annotated[
        str | None,
        Query(description="Part of a recipient's address, regardless of case"),
    ] = None,
    after: Annotated[
        AwareDatetime | None, Query(description="At or after this time")
    ] = None,
    before: Annotated[
        AwareDatetime | None, Query(description="Before this time")
    ] = None,
) -> SendFilter | None:
    """None when nothing narrows the list."""
    wanted = {
        "user_id": user,
        "outcome": outcome,
        "recipient": recipient,
        "after": after,
        "before": before,
    }
    if all(value is None for value in wanted.values()):
        return None
    return SendFilter.model_validate(wanted)


SendSearch = Annotated[SendFilter | None, Depends(send_filter)]
