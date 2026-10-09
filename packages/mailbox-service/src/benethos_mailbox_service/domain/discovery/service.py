"""Autodiscovery: from an address to ranked ways of connecting it (CONCEPT 5.8).

The sources in ``data/discovery`` only look up. Decided here:

- **Trust.** Presets are confirmed. An autoconfig or JMAP answer from the
  address's own domain is confirmed. Otherwise an ISPDB or autoconfig answer is
  confirmed only when every server lies in the address's registrable domain
  or is a server of a preset. What MX points to is never confirmed.
- **Safety.** Before a server is probed, its host must resolve to public
  addresses. A candidate whose server does not is dropped. The probe
  connects anonymously and sends no credential. A JMAP server is not
  probed: the source that found it has asked it already.
- **Ranking.** Confirmed before unconfirmed, reachable before unreachable,
  JMAP before the rest, then the order of the sources. Duplicates are
  merged into the first.
- **Limits.** Per user a number of discoveries per minute, and each domain's
  findings are cached for a day.
- **What can be connected.** Which candidates this service connects today,
  and which sign in with an OAuth app the deployment has.

What a candidate is made of, merged and filled in, and what can be
connected are ``candidates``.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

import anyio

from ...common.bounded import trim
from ...common.hosts import unicode_host
from ...data.discovery import (
    DiscoverySource,
    Finding,
    Query,
    registrable_domain,
)
from ...data.models import (
    Candidate,
    Discovery,
    DiscoverySourceName,
    Hint,
    MailServer,
    ProviderType,
    ServerProtocol,
    SourceOutcome,
    SourceReport,
)
from ...data.protocols import HostCheck
from ...data.providers import ServerProbe
from ...errors import MailboxServiceError, RateLimitedError
from ..activity import ActivityLog, Actor
from ..activity import discovery as said
from ..rights import Access
from .candidates import (
    incoming,
    merge,
    pop3_only_alone,
    query_of,
    replace_incoming,
    unreachable,
    with_settings,
)

Clock = Callable[[], float]

SOURCE_TIMEOUT = 10.0
PROBE_TIMEOUT = 12.0
MAX_PROBES = 4
CACHE_SECONDS = 24 * 3600
PER_USER = 10
PER_SECONDS = 60.0
# How many domains' findings and how many callers' counts are kept at
# most, so that whoever may discover cannot grow the memory without bound.
MAX_CACHED = 1000
MAX_CALLERS = 10_000

# The servers a candidate reads mail from that are probed before they
# are offered.
_PROBED = (ServerProtocol.IMAP, ServerProtocol.POP3)


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
        activity: ActivityLog | None = None,
        offered: Iterable[ProviderType] | None = None,
    ) -> None:
        """``offered``: the kinds of account that can be connected here,
        None for every kind. Candidates of other kinds are left out."""
        self._activity = activity or ActivityLog()
        self._offered = frozenset(offered) if offered is not None else None
        # Per user, the first call of the window whose limit was logged.
        self._told: dict[str, float] = {}
        self._sources = list(sources)
        self._order = {source.name: i for i, source in enumerate(self._sources)}
        self._probe = probe
        self._check_host = check_host
        self._trusted_hosts = frozenset(trusted_hosts)
        self._clock = clock
        self._per_user = per_user
        self._calls: dict[str, deque[float]] = {}
        self._cache: dict[str, tuple[float, list[_Result]]] = {}

    @property
    def per_user(self) -> int:
        """Discoveries a user may ask for in any minute."""
        return self._per_user

    @property
    def sources(self) -> list[DiscoverySourceName]:
        """The sources asked, in the order their answers are ranked."""
        return [source.name for source in self._sources]

    async def discover(self, access: Access, email: str) -> Discovery:
        access.require("discover_account")
        query = query_of(email)
        self._count(access)
        results = await self._lookup(query)

        candidates: list[Candidate] = []
        hints: list[Hint] = []
        for result in results:
            if result.finding is None:
                continue
            hints += [h for h in result.finding.hints if h not in hints]
            for candidate in result.finding.candidates:
                if self._offered is None or candidate.provider in self._offered:
                    merge(candidates, self._judged(candidate, result.finding, query))
        candidates = await self._probed(pop3_only_alone(candidates))
        candidates.sort(
            key=lambda c: (
                not c.confirmed,
                unreachable(c),
                c.provider is not ProviderType.JMAP,
                self._order.get(c.source, len(self._order)),
            )
        )
        domain = unicode_host(query.domain)
        self._activity.record(
            said.Discovered(
                by=Actor.of(access),
                domain=domain,
                candidates=len(candidates),
                sources=sum(1 for r in results if r.finding is not None),
            )
        )
        return Discovery(
            email=query.email,
            domain=domain,
            candidates=[with_settings(c, query) for c in candidates],
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
            except MailboxServiceError as exc:
                results[index] = _Result(source.name, error=exc.message)
            else:
                results[index] = _Result(source.name, finding=found)

        async with anyio.create_task_group() as group:
            for index, source in enumerate(self._sources):
                group.start_soon(run, index, source)
        done = [r for r in results if r is not None]
        if all(r.error is None for r in done):
            self._cache[query.domain] = (now + CACHE_SECONDS, done)
            self._trim_cache(now)
        return done

    def _trim_cache(self, now: float) -> None:
        """Expired findings go first, then the ones expiring soonest."""
        trim(
            self._cache,
            MAX_CACHED,
            gone=lambda cached: cached[0] <= now,
            age=lambda cached: cached[0],
        )

    def _count(self, access: Access) -> None:
        user_id = access.user_id
        now = self._clock()
        calls = self._calls.setdefault(user_id, deque())
        while calls and calls[0] <= now - PER_SECONDS:
            calls.popleft()
        if len(calls) >= self._per_user:
            wait = int(calls[0] + PER_SECONDS - now) + 1
            if self._told.get(user_id) != calls[0]:
                # Once per window, not for every refused call.
                self._told[user_id] = calls[0]
                self._activity.record(
                    said.DiscoveryLimitReached(
                        by=Actor.of(access), limit=self._per_user
                    )
                )
            raise RateLimitedError(
                f"too many discoveries, try again in {wait} seconds", wait
            )
        calls.append(now)
        # Callers whose calls all left the window are forgotten, then the
        # ones whose last call is longest ago.
        trim(
            self._calls,
            MAX_CALLERS,
            gone=lambda made: made[-1] <= now - PER_SECONDS,
            age=lambda made: made[-1],
            dropped=lambda user: self._told.pop(user, None),
        )

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
            candidate.source
            in (DiscoverySourceName.AUTOCONFIG, DiscoverySourceName.JMAP)
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
                (s.protocol, s.host, s.port, s.security)
                for c in candidates
                if (s := incoming(c)) is not None and s.protocol in _PROBED
            )
        )[:MAX_PROBES]
        outcome: dict[tuple[ServerProtocol, str, int, str], MailServer | None] = {}

        async def run(key: tuple[ServerProtocol, str, int, str]) -> None:
            outcome[key] = await self._probe_one(*key)

        async with anyio.create_task_group() as group:
            for key in servers:
                group.start_soon(run, key)

        kept = []
        for candidate in candidates:
            server = incoming(candidate)
            if server is None:
                kept.append(candidate)
                continue
            key = (server.protocol, server.host, server.port, server.security)
            if key not in outcome:
                kept.append(candidate)
            elif (probed := outcome[key]) is not None:
                kept.append(replace_incoming(candidate, server, probed))
        return kept

    async def _probe_one(
        self, protocol: ServerProtocol, host: str, port: int, security: str
    ) -> MailServer | None:
        """The server with what the probe found, None when it must not be
        contacted."""
        template = MailServer(
            protocol=protocol, host=host, port=port, security=security
        )
        try:
            address = await self._check_host(host, port)
        except MailboxServiceError:
            return None
        if address is None:
            return template.model_copy(update={"reachable": False})
        try:
            with anyio.fail_after(PROBE_TIMEOUT):
                capabilities = await self._probe(
                    protocol, host, port, template.security, address
                )
        except (MailboxServiceError, TimeoutError):
            return template.model_copy(update={"reachable": False})
        return template.model_copy(
            update={"reachable": True, "capabilities": sorted(capabilities)}
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
