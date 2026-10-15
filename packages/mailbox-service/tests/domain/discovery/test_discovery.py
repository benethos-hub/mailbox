"""Autodiscovery with fake sources: trust, ranking, failures and the cache.
The fakes here serve the other discovery tests too."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.discovery import (
    Finding,
)
from benethos_mailbox_service.data.models import (
    CredentialKind,
    DiscoverySourceName,
    Hint,
)
from benethos_mailbox_service.domain.discovery import service as discovery_module
from benethos_mailbox_service.errors import (
    ProviderUnavailableError,
)

from ...clocks import Seconds
from ...conftest import admin_access
from ..discovery_fake import (
    ADMIN,
    AUTOCONFIG,
    ISPDB,
    MX,
    PRESET,
    FakeSource,
    Network,
    found,
    imap,
    service,
)

# --- trust and ranking ----------------------------------------------------------


async def test_preset_is_confirmed_and_ready_to_use() -> None:
    network = Network()
    s = service(
        FakeSource(PRESET, found(imap("imap.bigmail.example", PRESET, smtp="smtp.x"))),
        network=network,
    )
    result = await s.discover(ADMIN, " Me@Firma.example ")
    assert result.email == "Me@Firma.example"
    assert result.domain == "firma.example"
    [candidate] = result.candidates
    assert candidate.confirmed
    imap_server, smtp_server = candidate.servers
    assert imap_server.username == "Me@Firma.example"
    assert smtp_server.username == "Me@Firma.example"
    assert imap_server.reachable is True
    assert imap_server.capabilities == ["IDLE", "IMAP4REV1"]
    assert smtp_server.reachable is None
    assert candidate.settings == {
        "host": "imap.bigmail.example",
        "port": 993,
        "security": "tls",
        "username": "Me@Firma.example",
        "auth": "password",
        # Sending: the SMTP server, with the same login.
        "smtp_host": "smtp.x",
        "smtp_port": 465,
        "smtp_security": "tls",
    }
    assert [(r.source, r.outcome) for r in result.sources] == [(PRESET, "found")]
    assert network.probed == ["imap.bigmail.example"]


@pytest.mark.parametrize(
    ("source", "host", "answered_by", "confirmed"),
    [
        # Autoconfig from the address's own domain: confirmed, wherever it points.
        (AUTOCONFIG, "mail.hoster.example", "autoconfig.firma.example", True),
        # Redirected to another domain: judged by the servers.
        (AUTOCONFIG, "mail.hoster.example", "config.hoster.example", False),
        (AUTOCONFIG, "imap.firma.example", "config.hoster.example", True),
        # ISPDB: servers in the address's domain or known from a preset.
        (ISPDB, "imap.firma.example", "autoconfig.thunderbird.net", True),
        (ISPDB, "imap.bigmail.example", "autoconfig.thunderbird.net", True),
        (ISPDB, "mail.hoster.example", "autoconfig.thunderbird.net", False),
        # MX: never, not even for a preset host.
        (MX, "imap.bigmail.example", "mx.bigmail.example", False),
    ],
)
async def test_trust_follows_the_source(
    source: DiscoverySourceName, host: str, answered_by: str, confirmed: bool
) -> None:
    s = service(FakeSource(source, found(imap(host, source), by=answered_by)))
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.confirmed is confirmed


async def test_ranking_confirmed_then_reachable_then_source_order() -> None:
    network = Network()
    network.down.add("imap.down.firma.example")
    s = service(
        FakeSource(
            AUTOCONFIG,
            found(imap("imap.down.firma.example", AUTOCONFIG), by="firma.example"),
        ),
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))),
        FakeSource(MX, found(imap("imap.hoster.example", MX))),
        network=network,
    )
    result = await s.discover(ADMIN, "me@firma.example")
    assert [c.servers[0].host for c in result.candidates] == [
        "imap.firma.example",
        "imap.down.firma.example",
        "imap.hoster.example",
    ]
    assert result.candidates[1].servers[0].reachable is False


async def test_duplicates_are_merged_into_the_better_one() -> None:
    mx_candidate = imap("imap.firma.example", MX).model_copy(
        update={"hints": [Hint(text="from mx")]}
    )
    ispdb = imap("imap.firma.example", ISPDB, credential=CredentialKind.APP_PASSWORD)
    s = service(FakeSource(ISPDB, found(ispdb)), FakeSource(MX, found(mx_candidate)))
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.source is ISPDB
    assert candidate.credential is CredentialKind.APP_PASSWORD
    assert candidate.confirmed
    assert candidate.hints == [Hint(text="from mx")]


async def test_merge_keeps_a_confirmation_from_a_later_source() -> None:
    s = service(
        FakeSource(MX, found(imap("imap.firma.example", MX))),
        FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB))),
    )
    [candidate] = (await s.discover(ADMIN, "me@firma.example")).candidates
    assert candidate.source is MX
    assert candidate.confirmed


# --- sources: failures, hints, cache ---------------------------------------------


async def test_failures_and_timeouts_are_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_module, "SOURCE_TIMEOUT", 0.01)
    s = service(
        FakeSource(PRESET),
        FakeSource(
            AUTOCONFIG,
            ProviderUnavailableError("autoconfig.firma.example is not reachable"),
        ),
        FakeSource(ISPDB, delay=1),
        FakeSource(MX, found(imap("imap.hoster.example", MX))),
    )
    result = await s.discover(ADMIN, "me@firma.example")
    assert [(r.source, r.outcome, r.message) for r in result.sources] == [
        (PRESET, "nothing", None),
        (AUTOCONFIG, "failed", "autoconfig.firma.example is not reachable"),
        (ISPDB, "failed", "no answer in time"),
        (MX, "found", None),
    ]
    assert len(result.candidates) == 1


async def test_hints_about_the_address() -> None:
    hint = Hint(text="Tuta offers no access for other mail programs.")
    s = service(
        FakeSource(PRESET, Finding(hints=(hint,))),
        FakeSource(MX, Finding(hints=(hint,))),
    )
    result = await s.discover(ADMIN, "me@tuta.example")
    assert result.candidates == []
    assert result.hints == [hint]
    assert result.sources[0].outcome == "found"


async def test_findings_are_cached_per_domain_for_a_day() -> None:
    clock = Seconds()
    source = FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB)))
    s = service(source, clock=clock, per_user=100)
    first = await s.discover(ADMIN, "a@firma.example")
    second = await s.discover(ADMIN, "b@firma.example")
    assert len(source.queries) == 1
    assert first.candidates[0].settings["username"] == "a@firma.example"
    assert second.candidates[0].settings["username"] == "b@firma.example"
    clock.now += 24 * 3600
    await s.discover(ADMIN, "a@firma.example")
    assert len(source.queries) == 2


async def test_the_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery_module, "MAX_CACHED", 2)
    clock = Seconds()
    source = FakeSource(ISPDB, found(imap("imap.firma.example", ISPDB)))
    s = service(source, clock=clock, per_user=100)
    for domain in ("one", "two", "three"):
        clock.now += 1
        await s.discover(ADMIN, f"a@{domain}.example")
    assert len(s._cache) == 2
    assert "one.example" not in s._cache
    # A finding that expired goes before a fresh one.
    clock.now += 24 * 3600 - 2
    await s.discover(ADMIN, "a@four.example")
    assert set(s._cache) == {"three.example", "four.example"}


async def test_the_callers_counted_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_module, "MAX_CALLERS", 2)
    clock = Seconds()
    s = service(FakeSource(ISPDB), clock=clock, per_user=100)
    for user in ("a", "b", "c"):
        clock.now += 1
        await s.discover(admin_access(f"usr_{user}", user), "x@firma.example")
    assert set(s._calls) == {"usr_b", "usr_c"}
    clock.now += 60
    await s.discover(admin_access("usr_d", "d"), "x@firma.example")
    assert set(s._calls) == {"usr_d"}


async def test_a_failed_lookup_is_not_cached() -> None:
    source = FakeSource(ISPDB, ProviderUnavailableError("down"))
    s = service(source)
    await s.discover(ADMIN, "a@firma.example")
    await s.discover(ADMIN, "a@firma.example")
    assert len(source.queries) == 2
