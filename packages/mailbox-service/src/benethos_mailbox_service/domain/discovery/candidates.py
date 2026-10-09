"""Candidates of a discovery, each a way to connect an address: the
address read into a query, the server a candidate reads mail from,
duplicates merged, the settings filled in, and what can be connected.

No lookup and no probe: those are ``DiscoveryService``'s.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...common.hosts import address_problem, ascii_host
from ...data.discovery import Query, placeholders, registrable_domain
from ...data.models import (
    Candidate,
    CredentialKind,
    MailServer,
    ProviderType,
    ServerProtocol,
)
from ...data.providers import settings_from_servers
from ...errors import BadRequestError

# The servers a candidate reads mail from.
_INCOMING = (ServerProtocol.JMAP, ServerProtocol.IMAP, ServerProtocol.POP3)

# What a JMAP or IMAP candidate keeps POP3 out of the list.
_BEFORE_POP3 = (ProviderType.JMAP, ProviderType.IMAP)
_PASSWORDS = (CredentialKind.PASSWORD, CredentialKind.APP_PASSWORD)
_JMAP_CREDENTIALS = (*_PASSWORDS, CredentialKind.API_TOKEN)


def query_of(email: str) -> Query:
    email = email.strip()
    # The domain goes into URLs and DNS names: a host name, nothing else,
    # so neither a port nor a path can ride along.
    problem = address_problem(email)
    if problem is not None:
        raise BadRequestError(problem)
    domain = email.rpartition("@")[2]
    ascii_domain = ascii_host(domain)
    if ascii_domain is None:
        raise BadRequestError(f"{domain} is no host name")
    if registrable_domain(ascii_domain) is None:
        raise BadRequestError(f"{domain} is a public suffix, not a mail domain")
    return Query(email=email, domain=ascii_domain)


def incoming(candidate: Candidate) -> MailServer | None:
    """The server a candidate reads mail from: JMAP, IMAP or POP3."""
    return next((s for s in candidate.servers if s.protocol in _INCOMING), None)


def unreachable(candidate: Candidate) -> bool:
    server = incoming(candidate)
    return server is not None and server.reachable is False


def replace_incoming(
    candidate: Candidate, old: MailServer, probed: MailServer
) -> Candidate:
    servers = [
        s.model_copy(
            update={"reachable": probed.reachable, "capabilities": probed.capabilities}
        )
        if s is old
        else s
        for s in candidate.servers
    ]
    update: dict[str, object] = {"servers": servers}
    # A server that refuses a password login but offers OAuth wants OAuth.
    if "LOGINDISABLED" in probed.capabilities and "AUTH=XOAUTH2" in probed.capabilities:
        update["credential"] = CredentialKind.OAUTH
    return candidate.model_copy(update=update)


def merge(candidates: list[Candidate], new: Candidate) -> None:
    """Add a candidate, or fold it into an earlier one for the same server."""
    key = _key(new)
    for index, existing in enumerate(candidates):
        if _key(existing) == key:
            candidates[index] = existing.model_copy(
                update={
                    "confirmed": existing.confirmed or new.confirmed,
                    "hints": existing.hints
                    + [h for h in new.hints if h not in existing.hints],
                    "name": existing.name or new.name,
                }
            )
            return
    candidates.append(new)


def pop3_only_alone(candidates: list[Candidate]) -> list[Candidate]:
    """POP3 only where no IMAP or JMAP is (CONCEPT 5.2)."""
    if any(c.provider in _BEFORE_POP3 for c in candidates):
        return [c for c in candidates if c.provider is not ProviderType.POP3]
    return candidates


def _key(candidate: Candidate) -> tuple[object, ...]:
    server = incoming(candidate)
    found = (
        (server.protocol, server.host, server.port, server.security) if server else None
    )
    return (candidate.provider, found)


def with_settings(candidate: Candidate, query: Query) -> Candidate:
    """Fill in the login name and the settings for POST /v1/accounts."""
    servers = [
        s.model_copy(update={"username": _username(s.username, query.email)})
        for s in candidate.servers
    ]
    settings = settings_from_servers(
        candidate.provider, servers, candidate.credential, query.email
    )
    return candidate.model_copy(update={"servers": servers, "settings": settings})


def _username(template: str | None, email: str) -> str:
    """The login name a source names, filled in. Without one, the address."""
    return placeholders.fill(template, email) if template is not None else email


def connectable(candidates: list[Candidate]) -> list[Candidate]:
    """What this service can connect today: JMAP with a password or an API
    token first, then IMAP with a password, and POP3 with a password only
    where neither is (CONCEPT 5.2)."""
    jmap = [
        c
        for c in candidates
        if c.provider is ProviderType.JMAP and c.credential in _JMAP_CREDENTIALS
    ]
    with_password = [c for c in candidates if c.credential in _PASSWORDS]
    imap = [c for c in with_password if c.provider is ProviderType.IMAP]
    if jmap or imap:
        return jmap + imap
    return [c for c in with_password if c.provider is ProviderType.POP3]


def sign_ins(candidates: list[Candidate], configured: Iterable[str]) -> list[Candidate]:
    """Candidates that sign in with a provider this deployment has an OAuth
    app for, one per provider."""
    apps = set(configured)
    found: dict[str, Candidate] = {}
    for candidate in candidates:
        name = candidate.oauth_provider
        if candidate.credential is CredentialKind.OAUTH and name in apps:
            found.setdefault(name, candidate)
    return list(found.values())
