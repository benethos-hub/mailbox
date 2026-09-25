"""Autodiscovery: from an address to ranked ways of connecting it (CONCEPT 5.8).

The sources in ``data/discovery`` only look up. Decided here:

- **Trust.** Presets are confirmed. An autoconfig answer from the address's
  own domain is confirmed. Otherwise an ISPDB or autoconfig answer is
  confirmed only when every server lies in the address's registrable domain
  or is a server of a preset. What MX points to is never confirmed.
- **Safety.** Before a server is probed, its host must resolve to public
  addresses; a candidate whose server does not is dropped. The probe
  connects anonymously and sends no credential.
- **Ranking.** Confirmed before unconfirmed, reachable before unreachable,
  then the order of the sources. Duplicates are merged into the first.
- **Limits.** Per user a number of discoveries per minute, and each domain's
  findings are cached for a day.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import anyio

from ..data.discovery import DiscoverySource, Finding, Query
from ..data.discovery.suffix import registrable_domain
from ..data.models import (
    Candidate,
    CredentialKind,
    Discovery,
    DiscoverySourceName,
    Hint,
    MailServer,
    ProviderType,
    ServerProtocol,
    SourceOutcome,
    SourceReport,
)
from ..data.providers import ServerProbe
from ..errors import BadRequestError, MailboxApiError, RateLimitedError
from .access import Access
from .accounts import HostCheck

# Resolves a host and returns an address to connect to, None when it does
# not resolve. Raises when the host must not be contacted.
Clock = Callable[[], float]

SOURCE_TIMEOUT = 10.0
PROBE_TIMEOUT = 12.0
MAX_PROBES = 4
CACHE_SECONDS = 24 * 3600
PER_USER = 10
PER_SECONDS = 60.0


@dataclass(frozen=True)
class _Result:
    source: DiscoverySourceName
    finding: Finding | None = None
    error: str | None = None


class DiscoveryService:
    def __init__(
        self,
        sources: Sequence[DiscoverySource],
        probe: ServerProbe,
        check_host: HostCheck,
        trusted_hosts: Iterable[str] = (),
        clock: Clock = time.monotonic,
        per_user: int = PER_USER,
    ) -> None:
        self._sources = list(sources)
        self._order = {source.name: i for i, source in enumerate(self._sources)}
        self._probe = probe
        self._check_host = check_host
        self._trusted_hosts = frozenset(trusted_hosts)
        self._clock = clock
        self._per_user = per_user
        self._calls: dict[str, deque[float]] = {}
        self._cache: dict[str, tuple[float, list[_Result]]] = {}

    async def discover(self, access: Access, email: str) -> Discovery:
        access.require("discover_account")
        query = _query(email)
        self._count(access.user_id)
        results = await self._lookup(query)

        candidates: list[Candidate] = []
        hints: list[Hint] = []
        for result in results:
            if result.finding is None:
                continue
            hints += [h for h in result.finding.hints if h not in hints]
            for candidate in result.finding.candidates:
                _merge(candidates, self._judged(candidate, result.finding, query))
        candidates = await self._probed(candidates)
        candidates.sort(
            key=lambda c: (
                not c.confirmed,
                _unreachable(c),
                self._order.get(c.source, len(self._order)),
            )
        )
        return Discovery(
            email=query.email,
            domain=query.domain.encode("ascii").decode("idna"),
            candidates=[_with_settings(c, query) for c in candidates],
            hints=hints,
            sources=[_report(r) for r in results],
        )

    # --- lookups ------------------------------------------------------------

    async def _lookup(self, query: Query) -> list[_Result]:
        cached = self._cache.get(query.domain)
        now = self._clock()
        if cached is not None and cached[0] > now:
            return cached[1]
        results: list[_Result | None] = [None] * len(self._sources)

        async def run(index: int, source: DiscoverySource) -> None:
            try:
                with anyio.fail_after(SOURCE_TIMEOUT):
                    found = await source.lookup(query)
            except TimeoutError:
                results[index] = _Result(source.name, error="no answer in time")
            except MailboxApiError as exc:
                results[index] = _Result(source.name, error=exc.message)
            else:
                results[index] = _Result(source.name, finding=found)

        async with anyio.create_task_group() as group:
            for index, source in enumerate(self._sources):
                group.start_soon(run, index, source)
        done = [r for r in results if r is not None]
        if all(r.error is None for r in done):
            self._cache[query.domain] = (now + CACHE_SECONDS, done)
        return done

    def _count(self, user_id: str) -> None:
        now = self._clock()
        calls = self._calls.setdefault(user_id, deque())
        while calls and calls[0] <= now - PER_SECONDS:
            calls.popleft()
        if len(calls) >= self._per_user:
            wait = int(calls[0] + PER_SECONDS - now) + 1
            raise RateLimitedError(
                f"too many discoveries, try again in {wait} seconds", wait
            )
        calls.append(now)

    # --- trust --------------------------------------------------------------

    def _judged(
        self, candidate: Candidate, finding: Finding, query: Query
    ) -> Candidate:
        own = registrable_domain(query.domain)
        if candidate.source is DiscoverySourceName.PRESET:
            confirmed = True
        elif candidate.source is DiscoverySourceName.MX:
            confirmed = False
        elif (
            candidate.source is DiscoverySourceName.AUTOCONFIG
            and finding.answered_by is not None
            and registrable_domain(finding.answered_by) == own
        ):
            confirmed = True
        else:
            confirmed = bool(candidate.servers) and all(
                s.host in self._trusted_hosts or registrable_domain(s.host) == own
                for s in candidate.servers
            )
        return candidate.model_copy(update={"confirmed": confirmed})

    # --- probing ------------------------------------------------------------

    async def _probed(self, candidates: list[Candidate]) -> list[Candidate]:
        servers = list(
            dict.fromkeys(
                (s.host, s.port, s.security)
                for c in candidates
                if (s := _imap(c)) is not None
            )
        )[:MAX_PROBES]
        outcome: dict[tuple[str, int, str], MailServer | None] = {}

        async def run(key: tuple[str, int, str]) -> None:
            outcome[key] = await self._probe_one(*key)

        async with anyio.create_task_group() as group:
            for key in servers:
                group.start_soon(run, key)

        kept = []
        for candidate in candidates:
            imap = _imap(candidate)
            if imap is None:
                kept.append(candidate)
                continue
            key = (imap.host, imap.port, imap.security)
            if key not in outcome:
                kept.append(candidate)
            elif (probed := outcome[key]) is not None:
                kept.append(_replace_imap(candidate, imap, probed))
        return kept

    async def _probe_one(
        self, host: str, port: int, security: str
    ) -> MailServer | None:
        """The server with what the probe found, None when it must not be
        contacted."""
        template = MailServer(
            protocol=ServerProtocol.IMAP, host=host, port=port, security=security
        )
        try:
            address = await self._check_host(host, port)
        except MailboxApiError:
            return None
        if address is None:
            return template.model_copy(update={"reachable": False})
        try:
            with anyio.fail_after(PROBE_TIMEOUT):
                capabilities = await self._probe(
                    ServerProtocol.IMAP, host, port, template.security
                )
        except (MailboxApiError, TimeoutError):
            return template.model_copy(update={"reachable": False})
        return template.model_copy(
            update={"reachable": True, "capabilities": sorted(capabilities)}
        )


def _query(email: str) -> Query:
    email = email.strip()
    local, at, domain = email.rpartition("@")
    if not at or not local or not domain or len(email) > 254 or " " in email:
        raise BadRequestError("not a valid email address")
    try:
        ascii_domain = domain.lower().rstrip(".").encode("idna").decode("ascii")
    except UnicodeError:
        raise BadRequestError("not a valid email domain") from None
    if registrable_domain(ascii_domain) is None:
        raise BadRequestError(f"{domain} is a public suffix, not a mail domain")
    return Query(email=email, domain=ascii_domain)


def _imap(candidate: Candidate) -> MailServer | None:
    return next(
        (s for s in candidate.servers if s.protocol is ServerProtocol.IMAP), None
    )


def _unreachable(candidate: Candidate) -> bool:
    imap = _imap(candidate)
    return imap is not None and imap.reachable is False


def _replace_imap(
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


def _merge(candidates: list[Candidate], new: Candidate) -> None:
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


def _key(candidate: Candidate) -> tuple[object, ...]:
    imap = _imap(candidate)
    server = (imap.host, imap.port, imap.security) if imap else None
    return (candidate.provider, server)


def _with_settings(candidate: Candidate, query: Query) -> Candidate:
    """Fill in the login name and the settings for POST /v1/accounts."""
    servers = [
        s.model_copy(update={"username": _username(s.username, query)})
        for s in candidate.servers
    ]
    settings: dict[str, str | int | bool] = {}
    imap = next((s for s in servers if s.protocol is ServerProtocol.IMAP), None)
    if candidate.provider is ProviderType.IMAP and imap is not None:
        settings = {
            "host": imap.host,
            "port": imap.port,
            "security": str(imap.security),
            "username": imap.username or query.email,
            "auth": "xoauth2"
            if candidate.credential is CredentialKind.OAUTH
            else "password",
        }
        smtp = next((s for s in servers if s.protocol is ServerProtocol.SMTP), None)
        if smtp is not None:
            settings["smtp_host"] = smtp.host
            settings["smtp_port"] = smtp.port
            settings["smtp_security"] = str(smtp.security)
            if smtp.username and smtp.username != settings["username"]:
                settings["smtp_username"] = smtp.username
    return candidate.model_copy(update={"servers": servers, "settings": settings})


def _username(template: str | None, query: Query) -> str:
    if template is None:
        return query.email
    local = query.email.rpartition("@")[0]
    domain = query.email.rpartition("@")[2]
    return (
        template.replace("%EMAILADDRESS%", query.email)
        .replace("%EMAILLOCALPART%", local)
        .replace("%EMAILDOMAIN%", domain)
    )


def _report(result: _Result) -> SourceReport:
    if result.error is not None:
        return SourceReport(
            source=result.source, outcome=SourceOutcome.FAILED, message=result.error
        )
    found = result.finding is not None and bool(
        result.finding.candidates or result.finding.hints
    )
    return SourceReport(
        source=result.source,
        outcome=SourceOutcome.FOUND if found else SourceOutcome.NOTHING,
    )
