"""Addresses: this service's as the outside sees it, and the caller's,
and the path of a request as the log names it."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from ..data.models import ProviderType
from .state import app_settings

# Where a link to an attachment is used: ``api.PREFIX`` and the router of
# ``api/routes/links.py``, which a test holds to this.
LINKS = "/v1/links/"


def public_base(request: Request) -> str:
    """``MAILBOX_SERVICE_PUBLIC_URL``, else the address the request came to."""
    base = app_settings(request.app).public_url or str(request.base_url)
    return base.rstrip("/")


def public_host(request: Request) -> str:
    """The host name of ``public_base``, without scheme and port."""
    return urlsplit(public_base(request)).hostname or "localhost"


def client_address(request: Request) -> str:
    """Where the request came from, as the server sees it. Behind a proxy
    that is the proxy, unless ``MAILBOX_SERVICE_FORWARDED_ALLOW_IPS`` names
    it and it sends ``X-Forwarded-For``."""
    return request.client.host if request.client else "unknown"


def link_url(request: Request, secret: str) -> str:
    """The URL of a link to an attachment, at ``public_base``."""
    return f"{public_base(request)}{LINKS}{secret}"


def logged_path(path: str) -> str:
    """A path as a line of the log names it: a link's secret masked, since
    whoever holds it fetches the attachment."""
    if path.startswith(LINKS) and len(path) > len(LINKS):
        return f"{LINKS}…"
    return path


def oauth_callback(request: Request, provider: ProviderType) -> str:
    """Where a provider sends the browser back after a sign-in: a page of
    the UI. It must be registered with the provider exactly so."""
    return f"{public_base(request)}/ui/oauth/{provider.value}/callback"
