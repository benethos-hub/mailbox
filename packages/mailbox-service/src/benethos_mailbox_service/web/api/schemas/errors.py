"""The body of every error the API raises itself."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """The body of every error the API raises itself."""

    error: ErrorDetail
