"""JMAP well-known: whether the domain runs a JMAP server (RFC 8620 2.2).

Asks ``https://{domain}/.well-known/jmap`` without a credential, then the
hosts the SRV record ``_jmap._tcp.{domain}`` names. A JMAP server answers
there with its session, or asks for a login with ``401`` and the schemes
it takes. The candidate names where the session is after the redirects,
and the schemes decide whether to ask for a password or an API token.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ...errors import MailboxServiceError
from ..models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    Hint,
    MailServer,
    ProviderType,
    Security,
    ServerProtocol,
)
from ..protocols import Answered, SafeFetcher, jmap
from .base import Finding, Query
from .dns import srv_targets

SrvLookup = Callable[[str], Awaitable[list[tuple[str, int]]]]

WELL_KNOWN = "/.well-known/jmap"
# SRV targets asked at most, the first by priority.
MAX_TARGETS = 3


class JmapSource:
    name = DiscoverySourceName.JMAP

    def __init__(
        self, fetcher: SafeFetcher, lookup_srv: SrvLookup = srv_targets
    ) -> None:
        self._fetcher = fetcher
        self._lookup_srv = lookup_srv

    async def lookup(self, query: Query) -> Finding:
        errors: list[MailboxServiceError] = []
        urls = [f"https://{query.domain}{WELL_KNOWN}"]
        try:
            targets = await self._lookup_srv(f"_jmap._tcp.{query.domain}")
        except MailboxServiceError as exc:
            errors.append(exc)
            targets = []
        urls += [
            f"https://{host}:{port}{WELL_KNOWN}" for host, port in targets[:MAX_TARGETS]
        ]
        for url in urls:
            try:
                answered = await self._fetcher.answer(url)
            except MailboxServiceError as exc:
                errors.append(exc)
                continue
            if answered is None:
                continue
            candidate = _candidate(answered)
            if candidate is not None:
                return Finding(candidates=(candidate,), answered_by=answered.host)
        if errors:
            raise errors[0]
        return Finding()


def _candidate(answered: Answered) -> Candidate | None:
    """A JMAP server where the answer is a session or asks for a login."""
    schemes = _schemes(answered.headers.get("www-authenticate", ""))
    if answered.status == 401 and schemes & {"basic", "bearer"}:
        credential = (
            CredentialKind.PASSWORD if "basic" in schemes else CredentialKind.API_TOKEN
        )
    elif answered.status == 200 and jmap.is_session(answered.body):
        credential = CredentialKind.PASSWORD
    else:
        return None
    hints = []
    if credential is CredentialKind.API_TOKEN:
        hints.append(Hint(text="Create an API token in your provider's settings."))
    return Candidate(
        provider=ProviderType.JMAP,
        credential=credential,
        servers=[
            MailServer(
                protocol=ServerProtocol.JMAP,
                host=answered.host,
                port=answered.port,
                security=Security.TLS,
                path=answered.path,
                reachable=True,
                capabilities=sorted(f"AUTH={s.upper()}" for s in schemes),
            )
        ],
        hints=hints,
        source=DiscoverySourceName.JMAP,
    )


def _schemes(header: str) -> set[str]:
    """The authentication schemes a WWW-Authenticate header offers, lower
    case. A scheme is a token before a space, or a whole challenge."""
    found = set()
    for part in header.split(","):
        word = part.strip().split(" ", 1)[0]
        if word and "=" not in word:
            found.add(word.lower())
    return found
