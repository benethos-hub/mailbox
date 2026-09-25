"""Addresses: this service's as the outside sees it, and the caller's."""

from __future__ import annotations

from fastapi import Request

from ..config import Settings
from ..data.models import ProviderType


def public_base(request: Request) -> str:
    """``MAILBOX_SERVICE_PUBLIC_URL``, else the address the request came to."""
    settings: Settings = request.app.state.settings
    base = settings.public_url or str(request.base_url)
    return base.rstrip("/")


def client_address(request: Request) -> str:
    """Where the request came from, as the server sees it. Behind a proxy
    that is the proxy, unless ``MAILBOX_SERVICE_FORWARDED_ALLOW_IPS`` names
    it and it sends ``X-Forwarded-For``."""
    return request.client.host if request.client else "unknown"


def oauth_callback(request: Request, provider: ProviderType) -> str:
    """Where a provider sends the browser back after a sign-in: a page of
    the UI. It must be registered with the provider exactly so."""
    return f"{public_base(request)}/ui/oauth/{provider.value}/callback"
