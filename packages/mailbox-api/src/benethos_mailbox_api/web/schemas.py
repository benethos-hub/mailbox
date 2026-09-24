"""Request and response shapes that exist only at the HTTP boundary.

The mail types themselves come from ``data.models`` and are served as they
are. What lives here is what only a caller of the API sends or receives.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..data.models import ProviderType


class AccountCreate(BaseModel):
    provider: ProviderType
    email: str
    display_name: str | None = None
    # Provider-specific connection settings (host, port, ...). Credentials are
    # accepted here once and never returned.
    settings: dict[str, str | int | bool] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """The body of every error the API raises itself."""

    error: ErrorDetail
