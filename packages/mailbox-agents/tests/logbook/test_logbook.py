"""The log: one activity class per line, the catalogue as docs/mailbox-agents/LOGGING.md
lists it, nothing of a mail, every line redacted."""

from __future__ import annotations

import io
import logging
import re
import typing
from collections.abc import Iterator
from dataclasses import dataclass, fields
from pathlib import Path
from typing import ClassVar

import pytest

from benethos_mailbox_agents import errors, logbook
from benethos_mailbox_agents.logbook import (
    Activity,
    Failure,
    actions,
    describe,
    escaped,
    feed,
    messages,
    process,
    record,
    worker,
)
from benethos_mailbox_agents.logbook.catalogue import AREAS
from benethos_mailbox_agents.logbook.output import PACKAGE
from benethos_mailbox_common.log import lines, redact

from ..agents_helpers import DOCS

# The package folder, the one above logbook/.
SOURCE = Path(logbook.__file__).resolve().parent.parent
LOGGING_MD = DOCS / "LOGGING.md"
NAME = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
LEVELS = {logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR}
# What no field of an activity may hold: a secret, a piece of a mail, the
# address of a person.
FORBIDDEN_TYPES = {"SecretStr", "MailMessage", "Address", "bytes"}
FORBIDDEN_NAMES = {
    "password",
    "secret",
    "subject",
    "body",
    "text",
    "sender",
    "quote",
    "url",
    "query",
}


def catalogue() -> list[type[Activity]]:
    """Every activity of the catalogue, in the order of its modules."""
    return [
        value
        for area in AREAS
        for value in vars(area).values()
        if isinstance(value, type)
        and issubclass(value, Activity)
        and value.__module__ == area.__name__
    ]


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    found = io.StringIO()
    logbook.configure("DEBUG", stream=found)
    yield found
    logbook.configure("INFO", stream=io.StringIO())


# -- the catalogue ---------------------------------------------------------------


def test_every_activity_is_listed_in_the_concept_and_nothing_else() -> None:
    text = LOGGING_MD.read_text(encoding="utf-8")
    section = text.partition("## 6. The catalogue")[2]
    listed = re.findall(r"^\| `(\w+)\.(\w+)` \| (\w+) \|", section, re.MULTILINE)
    assert listed == [
        (cls.area, cls.name, logging.getLevelName(cls.level)) for cls in catalogue()
    ]


def test_each_name_is_unique() -> None:
    sources = [cls.source() for cls in catalogue()]
    assert len(sources) == len(set(sources))


@pytest.mark.parametrize("cls", catalogue(), ids=lambda cls: cls.source())
def test_each_activity_has_a_name_a_level_a_line_and_no_mail(
    cls: type[Activity],
) -> None:
    assert cls.area == cls.__module__.rpartition(".")[2]
    assert "name" in vars(cls), "each activity sets its name"
    assert NAME.fullmatch(cls.name), cls.name
    assert not cls.name.startswith(cls.area.rstrip("s") + "_"), "the area twice"
    assert len(cls.source()) <= lines.SOURCE_WIDTH, cls.source()
    assert cls.level in LEVELS
    assert cls.says is not Activity.says, "says() writes the line"
    hints = typing.get_type_hints(cls)
    for field in fields(cls):
        shown = repr(hints[field.name])
        assert not any(name in shown for name in FORBIDDEN_TYPES), field
        assert not any(word in field.name for word in FORBIDDEN_NAMES), field


ERROR = errors.GatewayUnavailableError("away")
LINES: list[tuple[Activity, str]] = [
    (
        process.Started(agent="a", version="3", stage="shadow"),
        "a started version 3 in stage shadow",
    ),
    (process.Stopped(agent="a", reason="signal"), "a stopped: signal"),
    (
        process.Migrated(agent="a", before=0, after=2, notes=()),
        "a made its state file at schema 2",
    ),
    (
        process.Migrated(agent="a", before=1, after=2, notes=("schema 2: x",)),
        "a migrated its state file from schema 1 to 2: schema 2: x",
    ),
    (
        process.MetricsServing(agent="a", port=9464),
        "a began serving metrics on port 9464",
    ),
    (
        worker.PassDone(agent="a", seconds=0.5, pending=1),
        "a finished a pass in 0.50s with 1 message pending",
    ),
    (
        worker.PassFailed(agent="a", error=ERROR, wait=120),
        "a failed a pass and waits 120s: GatewayUnavailableError(gateway_unavailable)",
    ),
    (
        worker.UpstreamAway(agent="a", error=ERROR, wait=30),
        "a found an upstream away and waits 30s: "
        "GatewayUnavailableError(gateway_unavailable)",
    ),
    (worker.TickDone(agent="a", actions=2), "a ticked with 2 actions"),
    (
        feed.Read(agent="a", changes=3, selected=1),
        "a read 3 changes from the feed and selected 1",
    ),
    (
        feed.Expired(agent="a"),
        "a found its place in the feed expired and starts anew",
    ),
    (
        feed.Backfilled(agent="a", messages=4, days=1),
        "a backfilled 4 messages of the last 1 day",
    ),
    (
        messages.StateSet(agent="a", message_id="m1", state="done"),
        "a set message m1 to done",
    ),
    (
        messages.StepDone(agent="a", message_id="m1", step="decision", ms=12),
        "a finished step decision of message m1 in 12ms",
    ),
    (
        messages.StepFailed(agent="a", message_id="m1", step="model", error=ERROR),
        "a failed step model of message m1: "
        "GatewayUnavailableError(gateway_unavailable)",
    ),
    (
        messages.AnswerRefused(agent="a", message_id="m1", reason="schema"),
        "a refused the model's answer on message m1: schema",
    ),
    (
        messages.QuoteMissing(agent="a", message_id="m1", field="label"),
        "a found no quote for label in message m1",
    ),
    (
        actions.Done(
            agent="a", message_id="m1", action="move", stage="full", reason="due"
        ),
        "a carried out move on message m1 in stage full: due",
    ),
    (
        actions.Recorded(
            agent="a", message_id="m1", action="move", stage="shadow", reason=""
        ),
        "a recorded move on message m1 in stage shadow without carrying it out",
    ),
    (
        actions.Kept(agent="a", message_id="m1"),
        "a left message m1 where the owner put it, as it moved it once before",
    ),
    (
        actions.Refused(agent="a", message_id="m1", action="move", error=ERROR),
        "a was refused move on message m1: "
        "GatewayUnavailableError(gateway_unavailable)",
    ),
]


def test_every_activity_has_a_line_in_the_test() -> None:
    assert {type(activity) for activity, _ in LINES} == set(catalogue())


@pytest.mark.parametrize(
    ("activity", "line"), LINES, ids=lambda value: getattr(value, "name", "")
)
def test_the_line_of_each_activity(
    activity: Activity, line: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger=PACKAGE):
        record(activity)

    [written] = caplog.records
    assert written.name == f"{PACKAGE}.{activity.source()}"
    assert written.levelno == activity.level
    assert written.getMessage() == line


# -- the recorder ----------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class _Costly(Activity):
    name: ClassVar[str] = "costly"
    level: ClassVar[int] = logging.DEBUG

    def says(self) -> str:
        raise AssertionError("built below its level")


def test_a_line_below_the_level_is_not_built(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=PACKAGE):
        record(_Costly(agent="a"))

    assert not caplog.records


@pytest.mark.parametrize(
    "brk", ["\r\n", "\n", "\x0b", "\x1b", "\x85", "\x9b", "\u2028", "\x00"]
)
def test_an_id_with_a_line_break_stays_on_one_line(
    brk: str, caplog: pytest.LogCaptureFixture
) -> None:
    """An id an upstream chose cannot forge a line of the log."""
    forged = f"m1{brk}2026-11-18 INFO forged"
    with caplog.at_level(logging.INFO, logger=PACKAGE):
        record(messages.StateSet(agent="a", message_id=forged, state="done"))

    [written] = caplog.records
    message = written.getMessage()
    assert message.splitlines() == [message]
    assert brk not in message
    assert brk.encode("unicode_escape").decode() in message


def test_escaped_leaves_printable_text_alone() -> None:
    assert escaped("Rechnung über 12 € – ok") == "Rechnung über 12 € – ok"


@pytest.mark.parametrize(
    "mark",
    [
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    ],
)
def test_escaped_writes_a_direction_mark_as_its_escape(mark: str) -> None:
    """A sender or subject cannot turn the text of a report around."""
    assert escaped(f"a{mark}b") == f"a\\u{ord(mark):04x}b"


def test_an_error_is_named_never_quoted(stream: io.StringIO) -> None:
    error = errors.MailboxRefusedError(
        "Subject: secret plans", status=404, reason="not_found"
    )

    record(messages.StepFailed(agent="a", message_id="m1", step="fetch", error=error))

    line = stream.getvalue()
    assert "MailboxRefusedError(mailbox_refused)" in line
    assert "secret plans" not in line


def test_describe_a_foreign_error() -> None:
    assert describe(ValueError("x")) == "ValueError"


# -- the output ------------------------------------------------------------------


def test_configure_twice_keeps_one_handler(stream: io.StringIO) -> None:
    logbook.configure("DEBUG", stream=stream)
    record(process.Stopped(agent="a", reason="signal"))

    assert len(stream.getvalue().splitlines()) == 1


def test_the_libraries_are_held_at_warning(stream: io.StringIO) -> None:
    for name in logbook.LIBRARIES:
        assert logging.getLogger(name).level == logging.WARNING


def test_a_plain_line_has_the_time_the_level_and_the_whole_source(
    stream: io.StringIO,
) -> None:
    record(process.Stopped(agent="a", reason="signal"))

    assert re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d INFO     "
        rf"{PACKAGE}\.activity\.process\.stopped: a stopped: signal\n",
        stream.getvalue(),
    )


def _record(message: str, exc: BaseException | None = None) -> logging.LogRecord:
    exc_info = (type(exc), exc, exc.__traceback__) if exc is not None else None
    return logging.LogRecord(
        f"{PACKAGE}.activity.feed.read", logging.WARNING, "x", 1, message, (), exc_info
    )


def test_a_registered_secret_is_masked_in_the_line_and_the_traceback() -> None:
    redact.note("tok-123456789")
    try:
        try:
            raise KeyError("tok-123456789")
        except KeyError as exc:
            caught = exc
        for formatter in (lines.Redacting(), lines.Console(PACKAGE)):
            written = formatter.format(_record("sent tok-123456789", caught))
            assert "tok-123456789" not in written
            assert "KeyError" in written
    finally:
        redact.forget()


def test_the_console_shows_the_source_short_and_in_colour() -> None:
    written = lines.Console(PACKAGE).format(_record("a read 3 changes"))

    assert "\033[" in written
    assert f"{PACKAGE}." not in written
    assert "activity.feed.read" in written
    assert written.endswith("a read 3 changes")


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_a_terminal_gets_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    terminal = _Terminal()
    logbook.configure("INFO", stream=terminal)
    try:
        record(process.Stopped(agent="a", reason="signal"))
    finally:
        logbook.configure("INFO", stream=io.StringIO())

    assert "\033[" in terminal.getvalue()


# -- the rule --------------------------------------------------------------------


def test_a_failure_is_a_warning_by_default() -> None:
    assert Failure.level == logging.WARNING


def test_a_lone_surrogate_is_written_as_its_escape() -> None:
    found = escaped("x" + chr(0xD800))

    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in found)
    found.encode("utf-8")
    assert found.startswith("x")
