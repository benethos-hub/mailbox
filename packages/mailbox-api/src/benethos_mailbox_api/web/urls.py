"""Addresses of this service as the outside sees them."""

from __future__ import annotations

from fastapi import Request

from ..config import Settings
from ..data.models import ProviderType


def public_base(request: Request) -> str:
    """``MAILBOX_API_PUBLIC_URL``, else the address the request came to."""
    settings: Settings = request.app.state.settings
    base = settings.public_url or str(request.base_url)
    return base.rstrip("/")


def oauth_callback(request: Request, provider: ProviderType) -> str:
    """Where a provider sends the browser back after a sign-in: a page of
    the UI. It must be registered with the provider exactly so."""
    return f"{public_base(request)}/ui/oauth/{provider.value}/callback"
