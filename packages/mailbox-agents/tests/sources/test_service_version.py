"""The version of the mailbox service: the tested lines, the check before
every pass and every backfill, what the commands say, and the pins of the
repository held to the lines. See docs/mailbox-agents/concept/mailbox-service.md."""

from __future__ import annotations

import asyncio
import re

import pytest

from benethos_mailbox_agents.cli import PROG, main
from benethos_mailbox_agents.errors import (
    MailboxUnavailableError,
    ServiceVersionError,
)
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.sources import mailbox as source
from benethos_mailbox_agents.sources.mailbox import TESTED, is_tested, line_names

from ..agents_fake import ACCOUNT, FakeService, wire_message
from ..agents_helpers import DOCS, PACKAGE_DIR, ROOT, Wired, configure, worker


def _numbers(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split(".")[:3])
    return major, minor, patch


# -- the lines ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.7.5", True),
        ("0.7.6", True),
        ("0.7.12", True),
        ("0.7.5+local", True),
        ("0.7.6+build.1", True),
        ("0.7.5rc1", False),
        ("0.7.6.dev3", False),
        ("0.7.5a1", False),
        ("0.7.5-beta", False),
        ("0.7.5+", False),
        ("0.7.5 ", False),
        ("0.7.4", False),
        ("0.6.9", False),
        ("0.8.0", False),
        ("1.0.0", False),
        ("7.5", False),
        ("v0.7.5", False),
        ("unknown", False),
        ("", False),
    ],
)
def test_a_version_is_tested_in_its_line_from_the_lowest_release(
    version: str, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source, "TESTED", ((0, 7, 5),))

    assert is_tested(version) is expected


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.7.5", True),
        ("0.8.0", False),
        ("1.2.0", True),
        ("1.2.3", True),
        ("1.9.0", True),
        ("1.1.9", False),
        ("2.0.0", False),
    ],
)
def test_a_line_is_the_major_version_from_1_on_and_several_can_be_tested(
    version: str, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source, "TESTED", ((0, 7, 5), (1, 2, 0)))

    assert is_tested(version) is expected
    assert line_names() == "0.7 from 0.7.5 and 1 from 1.2.0"


def test_the_lines_are_in_order_and_each_once() -> None:
    lines = [floor[:2] if floor[0] == 0 else floor[:1] for floor in TESTED]

    assert TESTED
    assert list(TESTED) == sorted(TESTED)
    assert len(set(lines)) == len(lines)


# -- the check ----------------------------------------------------------------------


async def test_a_service_in_a_tested_line_is_answered_with_its_version(
    world: Wired,
) -> None:
    assert await world.mailbox.ensure_tested() == world.service.version
    assert is_tested(world.service.version)


def test_the_fake_service_runs_the_newest_tested_line() -> None:
    assert FakeService().version == ".".join(map(str, TESTED[-1]))


async def test_a_service_outside_the_lines_is_refused_by_name(world: Wired) -> None:
    world.service.version = "0.99.0"

    with pytest.raises(ServiceVersionError) as raised:
        await world.mailbox.ensure_tested()

    assert "'0.99.0'" in raised.value.message
    assert line_names() in raised.value.message
    assert raised.value.code == "service_version"


async def test_a_version_that_is_no_version_is_refused_and_cut(world: Wired) -> None:
    world.service.version = "x" * 500

    with pytest.raises(ServiceVersionError) as raised:
        await world.mailbox.ensure_tested()

    assert "x" * 40 in raised.value.message
    assert "x" * 41 not in raised.value.message


async def test_every_pass_asks_the_service_for_its_version(world: Wired) -> None:
    run = worker(world)

    await run.run_pass()
    await run.run_pass()

    assert world.service.health_asked == 2


async def test_a_pass_against_another_line_reads_nothing_and_changes_nothing(
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


async def test_a_backfill_against_another_line_takes_nothing_up(world: Wired) -> None:
    world.service.add(wire_message("m1", subject="Your invoice"))
    world.service.version = "0.99.0"

    with pytest.raises(ServiceVersionError):
        await worker(world).backfill(30)

    assert world.service.requests == []
    assert world.store.counts()["pending"] == 0


async def test_another_line_ends_the_loop(world: Wired) -> None:
    """A pass after it would be refused the same way, forever."""
    world.service.version = "0.99.0"
    run = worker(world, poll_seconds=0.01)

    with pytest.raises(ServiceVersionError):
        await asyncio.wait_for(run.run(asyncio.Event()), timeout=5)

    assert world.service.health_asked == 1


@pytest.mark.parametrize("health", ["no version", "refused"])
async def test_a_service_that_names_no_version_is_outside_the_lines(
    world: Wired, health: str
) -> None:
    if health == "no version":
        world.service.version = None
    else:
        world.service.health_status = 404

    with pytest.raises(ServiceVersionError) as raised:
        await world.mailbox.ensure_tested()

    assert raised.value.message.startswith(
        "the mailbox service names no version at /health"
    )
    assert line_names() in raised.value.message


async def test_a_service_that_names_no_version_ends_the_loop(world: Wired) -> None:
    world.service.version = None
    run = worker(world, poll_seconds=0.01)

    with pytest.raises(ServiceVersionError):
        await asyncio.wait_for(run.run(asyncio.Event()), timeout=5)

    assert world.service.health_asked == 1
    assert world.service.requests == []


async def test_a_service_away_is_away_and_not_another_line(world: Wired) -> None:
    world.service.down = True

    with pytest.raises(MailboxUnavailableError):
        await worker(world).run_pass()


# -- the commands -------------------------------------------------------------------


def test_run_against_another_line_is_an_error_to_correct(
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
        "mailbox service names no version: not tested, no agent starts "
        f"(tested: {line_names()})"
    )
    assert any(line.startswith("counting ") for line in lines)


def test_backfill_against_another_line_is_an_error_to_correct(
    service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(monkeypatch)
    service.version = "0.99.0"

    assert main(["backfill", "--agent", "counting", "--days", "1"]) == 2
    assert service.requests == []


def test_status_names_the_service_and_its_line(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)

    assert main(["status"]) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == f"mailbox service {service.version}: tested ({line_names()})"


def test_status_names_a_service_outside_the_lines(
    service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure(monkeypatch)
    service.version = "0.99.0"

    assert main(["status"]) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first == (
        f"mailbox service 0.99.0: not tested, no agent starts (tested: {line_names()})"
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


def test_the_client_is_pinned_to_the_newest_tested_line() -> None:
    """The client is pinned to the release of the newest line, the same
    one the agent accepts of the service, as the workspace releases them
    together."""
    text = (PACKAGE_DIR / "pyproject.toml").read_text("utf-8")
    found = re.search(r'"benethos-mailbox-client==(\d+\.\d+\.\d+)"', text)

    assert found is not None
    assert _numbers(found.group(1)) == TESTED[-1]


def test_the_live_setup_runs_a_service_of_the_newest_tested_line() -> None:
    text = (ROOT / "containers" / "live" / "mailbox-agents" / "compose.yaml").read_text(
        "utf-8"
    )
    found = re.search(r"benethos-mailbox-service:(\d+\.\d+\.\d+)@sha256:", text)

    assert found is not None
    newest = TESTED[-1]
    width = 2 if newest[0] == 0 else 1
    assert is_tested(found.group(1))
    assert _numbers(found.group(1))[:width] == newest[:width]


def test_the_readme_names_the_tested_lines_and_the_service() -> None:
    """A reader learns which service the agents need, and where it is,
    before installing anything."""
    text = " ".join((PACKAGE_DIR / "README.md").read_text("utf-8").split())

    assert f"today {line_names()}," in text
    assert "[mailbox service](https://github.com/benethos-hub/mailbox)" in text


def test_the_compatibility_table_names_this_release_on_top() -> None:
    """The newest row of docs/mailbox-agents/COMPATIBILITY.md is the version of
    pyproject.toml, with the tested lines and the pin of the client."""
    project = (PACKAGE_DIR / "pyproject.toml").read_text("utf-8")
    version = re.search(r'^version = "([^"]+)"', project, re.MULTILINE)
    pin = re.search(r'"benethos-mailbox-client(==[^"]+)"', project)
    table = (DOCS / "COMPATIBILITY.md").read_text("utf-8")
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in table.splitlines()
        if line.startswith("| ") and not line.startswith("| Mailbox Agents")
    ]

    assert version is not None
    assert pin is not None
    assert rows
    agents, service, client = rows[0]
    assert agents in (version.group(1), f"{version.group(1)} (not released yet)")
    assert service == line_names()
    assert client == f"`{pin.group(1)}`"


def _version() -> str:
    """The version of the package, as pyproject.toml names it."""
    project = (PACKAGE_DIR / "pyproject.toml").read_text("utf-8")
    found = re.search(r'^version = "([^"]+)"', project, re.MULTILINE)
    assert found is not None
    return found.group(1)


def test_the_production_example_pulls_this_release() -> None:
    example = ROOT / "containers" / "production" / "mailbox-agents" / ".env.example"

    assert f"MAILBOX_AGENTS_VERSION={_version()}\n" in example.read_text("utf-8")


def test_the_changelog_names_this_release_and_links_it() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text("utf-8")
    version = _version()
    released = re.findall(r"^## \[(\d[^\]]*)\]", changelog, re.MULTILINE)
    unreleased = re.search(r"^\[Unreleased\]: (\S+)$", changelog, re.MULTILINE)

    assert released[0] == version
    assert unreleased is not None
    assert unreleased.group(1).endswith(f"/compare/v{version}...HEAD")
    assert re.search(rf"^\[{re.escape(version)}\]: \S+$", changelog, re.MULTILINE)
