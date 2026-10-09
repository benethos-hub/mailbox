"""The way out to mail servers and providers: the guard of every
connection to a host a user typed, the adapters' factory, the OAuth apps,
the kinds of account offered, and autodiscovery."""

from __future__ import annotations

from functools import partial

import anyio

from ..common import redact
from ..config import Settings
from ..data.discovery import default_sources, preset_hosts
from ..data.models import ProviderType
from ..data.protocols import (
    ApiClient,
    Lookup,
    Resolve,
    SafeFetcher,
    WebhookPoster,
    host_addresses,
    host_addresses_now,
)
from ..data.providers import (
    App,
    OAuthClient,
    Pace,
    ProviderFactory,
    build_provider,
    probe_server,
    project_client_id,
    sign_in,
)
from ..domain.activity import ActivityLog
from ..domain.discovery import DiscoveryService
from ..errors import BadRequestError


def guard(
    settings: Settings, resolve: Resolve | None, lookup: Lookup | None
) -> SafeFetcher:
    """One guard for every connection the service makes to a host a user
    typed: the lookups of autodiscovery and the servers of an account.
    ``resolve`` and ``lookup`` answer DNS in its place, for tests."""
    return SafeFetcher(
        resolve=resolve or host_addresses,
        internal_hosts=settings.discovery_internal_hosts,
        lookup=lookup or host_addresses_now,
    )


def poster(settings: Settings, resolve: Resolve | None) -> WebhookPoster:
    """What posts the webhooks, with the same check of their hosts."""
    return WebhookPoster(
        resolve=resolve or host_addresses, timeout=settings.webhook_timeout
    )


def provider_factory(settings: Settings, fetcher: SafeFetcher) -> ProviderFactory:
    """The adapters, each connection checked by ``fetcher``, paced as the
    settings say."""
    return partial(
        build_provider,
        pick=fetcher.connect_address,
        watchers=anyio.CapacityLimiter(settings.sync_watchers),
        pace=Pace(
            settings.imap_requests_per_minute,
            settings.imap_burst,
            attempts=settings.imap_attempts,
            first_pause=settings.imap_first_pause,
            longest_pause=settings.imap_longest_pause,
        ),
    )


def build_oauth(settings: Settings) -> dict[ProviderType, OAuthClient]:
    """The OAuth apps the settings name, one per provider. Without one,
    the project's app, a public client (CONCEPT 5.4), where there is one:
    Google has none (CONCEPT 5.5)."""
    clients: dict[ProviderType, OAuthClient] = {}
    google = settings.oauth_google_client_id
    google_secret = settings.oauth_google_secret()
    if google and google_secret is not None:
        redact.note(google_secret.get_secret_value())
        app = App(
            endpoints=sign_in(ProviderType.GMAIL),
            client_id=google,
            client_secret=google_secret,
        )
        clients[ProviderType.GMAIL] = OAuthClient(app, ApiClient())
    own = settings.oauth_microsoft_client_id
    client_id = own or project_client_id(ProviderType.MICROSOFT)
    if client_id:
        secret = settings.oauth_microsoft_secret() if own else None
        if secret is not None:
            redact.note(secret.get_secret_value())
        app = App(
            endpoints=sign_in(ProviderType.MICROSOFT, settings.oauth_microsoft_tenant),
            client_id=client_id,
            client_secret=secret,
            loopback_only=not own,
        )
        clients[ProviderType.MICROSOFT] = OAuthClient(app, ApiClient())
    return clients


def offered_providers(settings: Settings) -> frozenset[ProviderType] | None:
    """The kinds of account the settings let be connected, None for every
    kind."""
    if not settings.providers:
        return None
    offered = set()
    for name in settings.providers:
        try:
            offered.add(ProviderType(name.strip().lower()))
        except ValueError:
            known = ", ".join(p.value for p in ProviderType)
            raise BadRequestError(
                f"MAILBOX_SERVICE_PROVIDERS names {name!r}, not a kind of "
                f"account: {known}"
            ) from None
    return frozenset(offered)


def build_discovery(
    settings: Settings,
    fetcher: SafeFetcher,
    activity: ActivityLog | None = None,
    offered: frozenset[ProviderType] | None = None,
) -> DiscoveryService:
    return DiscoveryService(
        default_sources(fetcher, ispdb=settings.discovery_ispdb),
        probe=probe_server,
        check_host=fetcher.checked_address,
        trusted_hosts=preset_hosts(),
        per_user=settings.discovery_per_minute,
        activity=activity,
        offered=offered,
    )
