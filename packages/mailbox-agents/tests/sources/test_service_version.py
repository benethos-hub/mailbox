"""The version of the mailbox service: the agents take the service of
their own version, the check before every pass and every backfill, and
what the commands say. See docs/mailbox-agents/concept/mailbox-service.md."""

from __future__ import annotations

import asyncio
import re

import pytest

from benethos_mailbox_agents import __version__
from benethos_mailbox_agents.cli import PROG, main
from benethos_mailbox_agents.errors import (
    MailboxUnavailableError,
    ServiceVersionError,
)
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.sources.versions import matches, taken

from ..agents_fake import ACCOUNT, FakeService, wire_message
from ..agents_helpers import PACKAGE_DIR, ROOT, Wired, configure, worker

# -- the rule -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.10.0", True),
        ("0.10.1", True),
        ("0.10.12", True),
        ("0.10.0+local", True),
        ("0.10.1+build.1", True),
        ("0.10.0rc1", False),
        ("0.10.1.dev3", False),
        ("0.10.0a1", False),
        ("0.10.0-beta", False),
        ("0.10.0+", False),
        ("0.10.0 ", False),
        ("0.9.9", False),
        ("0.11.0", False),
        ("1.10.0", False),
        ("10.0", False),
        ("v0.10.0", False),
        ("unknown", False),
        ("", False),
    ],
)
def test_before_1_0_the_service_has_the_agents_minor_version(
    version: str, expected: bool
) -> None:
    """With another patch, and never as a pre-release."""
    assert matches(version, "0.10.2") is expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.0", True),
        ("1.2.5", True),
        ("1.9.0", True),
        ("1.1.9", False),
        ("2.2.0", False),
        ("0.2.0", False),
        ("1.3.0rc1", False),
    ],
)
def test_from_1_0_the_service_has_the_agents_major_version_and_no_older_minor(
    version: str, expected: bool
) -> None:
    assert matches(version, "1.2.0") is expected


def test_a_pre_release_of_the_agents_takes_the_releases_of_its_minor() -> None:
    assert matches("0.11.0", "0.11.0rc1")
    assert matches("0.11.3", "0.11.0.dev2")
    assert not matches("0.10.9", "0.11.0rc1")


def test_what_the_agents_take_is_named_in_words() -> None:
    assert taken("0.10.0") == "0.10"
    assert taken("0.10.0rc1") == "0.10"
    assert taken("1.2.3") == "1 from 1.2"


def test_by_default_the_agents_compare_their_own_version() -> None:
    major, minor = __version__.split(".")[:2]
    assert matches(f"{major}.{minor}.0")
    assert not matches(f"{major}.{int(minor) + 1}.0")
    assert taken() == taken(__version__)


# -- the check ----------------------------------------------------------------------


async def test_a_service_that_matches_is_answered_with_its_version(
    world: Wired,
) -> None:
    assert await world.mailbox.ensure_matching() == world.service.version
    assert matches(world.service.version)


def test_the_fake_service_runs_the_agents_minor_version() -> None:
    assert FakeService().version == ".".join(__version__.split(".")[:2]) + ".0"


async def test_a_service_that_does_not_match_is_refused_by_name(world: Wired) -> None:
    world.service.version = "0.99.0"

    with pytest.raises(ServiceVersionError) as raised:
        await world.mailbox.ensure_matching()

    assert "'0.99.0'" in raised.value.message
    assert f"take the service {taken()}" in raised.value.message
    assert raised.value.code == "service_version"


async def test_a_version_that_is_no_version_is_refused_and_cut(world: Wired) -> None:
    world.service.version = "x" * 500

    with pytest.raises(ServiceVersionError) as raised:
        await world.mailbox.ensure_matching()

    assert "x" * 40 in raised.value.message
    assert "x" * 41 not in raised.value.message


async def test_every_pass_asks_the_service_for_its_version(world: Wired) -> None:
    run = worker(world)

    await run.run_pass()
    await run.run_pass()

    assert world.service.health_asked == 2


async def test_a_pass_against_another_version_reads_nothing_and_changes_nothing(
    world: Wired,
) -> None:
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.version = "0.99.0"

    with pytest.raises(ServiceVersionError):
        await worker(world).run_pass()

    assert world.service.requests == []
    assert world.store.cursor() is None
    assert world.store.progress() is None


async def test_a_service_replaced_between_two_passes_is_seen(world: Wired) -> None:
    run = worker(world)
    await run.run_pass()
    world.service.add(wire_message("m1", subject="Your invoice"))
    asked = len(world.service.requests)
    world.service.version = "0.99.0"

    with pytest.raises(ServiceVersionError):
        await run.run_pass()

    assert len(world.service.requests) == asked
    assert world.store.message(MessageRef(account_id=ACCOUNT, message_id="m1")) is None


async def test_a_backfill_against_another_version_takes_nothing_up(
    world: Wired,
) -> None:
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.version = "0.99.0"

    with pytest.raises(ServiceVersionError):
        await worker(world).backfill(30)

    assert world.service.requests == []
    assert world.store.counts()["pending"] == 0


async def test_another_version_ends_the_loop(world: Wired) -> None:
    """A pass after it would be refused the same way, forever."""
    world.service.version = "0.99.0"
    run = worker(world, poll_seconds=0.01)

    with pytest.raises(ServiceVersionError):
        await asyncio.wait_for(run.run(asyncio.Event()), timeout=5)

    assert world.service.health_asked == 1


@pytest.mark.parametrize("health", ["no version", "refused"])
async def test_a_service_that_names_no_version_does_not_match(
    world: Wired, health: str
) -> None:
    if health == "no version":
        world.service.version = None
    else:
        world.service.health_status = 404

    with pytest.raises(ServiceVersionError) as raised:
        await world.mailbox.ensure_matching()

    assert raised.value.message.startswith(
        "the mailbox service names no version at /health"
    )
    assert f"take the service {taken()}" in raised.value.message


async def test_a_service_that_names_no_version_ends_the_loop(world: Wired) -> None:
    world.service.version = None
    run = worker(world, poll_seconds=0.01)

    with pytest.raises(ServiceVersionError):
        await asyncio.wait_for(run.run(asyncio.Event()), timeout=5)

    assert world.service.health_asked == 1
    assert world.service.requests == []


async def test_a_service_away_is_away_and_not_another_version(world: Wired) -> None:
    world.service.down = True

    with pytest.raises(MailboxUnavailableError):
        await worker(world).run_pass()


# -- the commands -------------------------------------------------------------------


def test_run_against_another_version_is_an_error_to_correct(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.version = "0.99.0"

    assert main(["run", "--agent", "counting"]) == 2

    last = capsys.readouterr().err.splitlines()[-1]
    assert last.startswith(f"{PROG}: the mailbox service runs '0.99.0'")
    assert service.requests == []


def test_run_against_a_service_that_names_no_version_is_an_error_to_correct(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.version = None

    assert main(["run", "--agent", "counting"]) == 2

    last = capsys.readouterr().err.splitlines()[-1]
    assert last.startswith(f"{PROG}: the mailbox service names no version")
    assert service.requests == []


def test_status_names_a_service_that_names_no_version(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.version = None

    assert main(["status"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        "mailbox service names no version: no match, no agent starts "
        f"(the agents take {taken()})"
    )
    assert any(line.startswith("counting ") for line in lines)


def test_backfill_against_another_version_is_an_error_to_correct(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    service.version = "0.99.0"

    assert main(["backfill", "--agent", "counting", "--days", "1"]) == 2
    assert service.requests == []


def test_status_names_the_service_and_that_it_matches(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)

    assert main(["status"]) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == (
        f"mailbox service {service.version}: matches (the agents take {taken()})"
    )


def test_status_names_a_service_that_does_not_match(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.version = "0.99.0"

    assert main(["status"]) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == (
        f"mailbox service 0.99.0: no match, no agent starts (the agents take {taken()})"
    )


def test_status_goes_on_when_the_service_is_away(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.down = True

    assert main(["status"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("mailbox service not asked: ")
    assert any(line.startswith("counting ") for line in lines)


def test_status_without_a_service_named_asks_none(
    service: FakeService, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0

    assert "mailbox service" not in capsys.readouterr().out
    assert service.health_asked == 0


# -- the pins of the repository -----------------------------------------------------


def test_the_client_is_pinned_to_the_agents_version() -> None:
    """The agents and the client are released together, under one
    version."""
    text = (PACKAGE_DIR / "pyproject.toml").read_text("utf-8")

    assert f'"benethos-mailbox-client=={_version()}"' in text


def test_the_readme_says_which_service_the_agents_take() -> None:
    """A reader learns which service the agents need, and where it is,
    before installing anything."""
    text = " ".join((PACKAGE_DIR / "README.md").read_text("utf-8").split())

    assert "take only a service of their own version" in text
    assert "the same minor version" in text
    assert "from 1.0 the same major version" in text
    service = (
        "https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service"
    )
    assert f"({service})" in text


def _version() -> str:
    """The version of the package, as pyproject.toml names it."""
    project = (PACKAGE_DIR / "pyproject.toml").read_text("utf-8")
    found = re.search(r'^version = "([^"]+)"', project, re.MULTILINE)
    assert found is not None
    return found.group(1)


def test_the_production_example_pulls_this_release() -> None:
    example = ROOT / "containers" / "production" / "mailbox-agents" / ".env.example"

    assert f"MAILBOX_VERSION={_version()}\n" in example.read_text("utf-8")


def test_the_changelog_names_this_release_and_links_it() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text("utf-8")
    version = _version()
    released = re.findall(r"^## \[(\d[^\]]*)\]", changelog, re.MULTILINE)
    unreleased = re.search(r"^\[Unreleased\]: (\S+)$", changelog, re.MULTILINE)

    assert released[0] == version
    assert unreleased is not None
    assert unreleased.group(1).endswith(f"/compare/v{version}...HEAD")
    assert re.search(rf"^\[{re.escape(version)}\]: \S+$", changelog, re.MULTILINE)
