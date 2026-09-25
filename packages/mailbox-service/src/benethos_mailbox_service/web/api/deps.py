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

from ...data.models import MessageFilter
from ...data.models.messages import SEARCH_TEXT_PATTERN
from ...domain.access import Access
from ..services import Accounts, Auth, Discoverer, Mailbox, Users
from ..urls import client_address

__all__ = [
    "Accounts",
    "Caller",
    "Discoverer",
    "Limit",
    "Mailbox",
    "Search",
    "Users",
    "authenticate",
]

# How many items a list answers with at most. The default is 50.
Limit = Annotated[int, Query(ge=1, le=200)]

_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth")


def authenticate(
    request: Request,
    auth: Auth,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Access:
    presented = credentials.credentials if credentials else None
    return auth.authenticate(presented, source=client_address(request))


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
