"""The lines of a log: the time, the colours, the source, the masking."""

from __future__ import annotations

import io
import json
import logging
import re
import sys
from datetime import UTC, datetime

import pytest

from benethos_mailbox_common.log import redact
from benethos_mailbox_common.log.lines import (
    FORMAT,
    SOURCE_WIDTH,
    Console,
    Json,
    Redacting,
    colours_wanted,
    formatter,
    log_time,
    short_source,
    stderr_handler,
)

PACKAGE = "benethos_x"


def _record(
    name: str = f"{PACKAGE}.server", message: str = "started"
) -> logging.LogRecord:
    record = logging.makeLogRecord(
        {"created": 1790590342.1239, "name": name, "msg": message}
    )
    record.levelname = "INFO"
    record.levelno = logging.INFO
    return record


def test_a_log_time_is_iso_local_to_the_millisecond_with_the_offset() -> None:
    value = datetime(2026, 9, 28, 10, 12, 22, 123456, tzinfo=UTC)
    local = value.astimezone()
    offset = local.isoformat()[-6:]
    assert log_time(value) == f"{local:%Y-%m-%dT%H:%M:%S}.123{offset}"
    assert datetime.fromisoformat(log_time(value)) == value.replace(microsecond=123000)


def test_every_line_writes_the_time_alike() -> None:
    """ISO 8601, local, to the millisecond, with the offset: the plain
    line and the terminal alike."""
    record = _record()
    local = datetime.fromtimestamp(1790590342.1239).astimezone()
    offset = local.isoformat()[-6:]
    expected = f"{local:%Y-%m-%dT%H:%M:%S}.123{offset}"
    assert Redacting().formatTime(record) == expected
    assert Console().formatTime(record) == expected


def test_a_plain_line_names_the_time_the_level_and_the_source() -> None:
    line = Redacting().format(_record())
    assert re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.123[+-]\d\d:\d\d INFO     "
        rf"{PACKAGE}\.server: started",
        line,
    )
    assert Redacting()._fmt == FORMAT


def test_a_terminal_line_is_short_and_in_colour() -> None:
    line = Console(PACKAGE).format(_record())
    server = "server".ljust(SOURCE_WIDTH)
    assert f"\033[32mINFO    \033[0m \033[36m{server}\033[0m started" in line


def test_a_program_gives_its_own_text_for_its_own_lines() -> None:
    def own(record: logging.LogRecord) -> str | None:
        return "own text" if record.name == "special" else None

    console = Console(PACKAGE, own)
    assert console.format(_record("special")).endswith(" own text")
    assert console.format(_record()).endswith(" started")


@pytest.mark.parametrize("make", [Redacting, lambda: Console(PACKAGE)])
def test_a_line_masks_a_noted_secret_in_a_traceback_too(make: type[Redacting]) -> None:
    redact.note("a-password-in-a-line")
    record = _record(message="echoed a-password-in-a-line")
    try:
        raise RuntimeError("raised a-password-in-a-line")
    except RuntimeError:
        record.exc_info = sys.exc_info()
    line = make().format(record)
    assert "a-password-in-a-line" not in line
    assert "echoed ***" in line and "RuntimeError: raised ***" in line


@pytest.mark.parametrize(
    ("name", "short"),
    [
        (f"{PACKAGE}.domain.auth", "domain.auth"),
        ("uvicorn.error", "uvicorn"),
        ("uvicorn.access", "http"),
        ("httpx", "httpx"),
    ],
)
def test_the_source_is_short(name: str, short: str) -> None:
    assert short_source(name, PACKAGE) == short


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_colours_on_a_terminal_unless_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stderr", Terminal())
    assert colours_wanted()
    assert isinstance(formatter(PACKAGE), Console)
    monkeypatch.setenv("NO_COLOR", "1")
    assert not colours_wanted()
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert not colours_wanted()
    assert type(formatter(PACKAGE)) is Redacting


def test_the_handler_writes_to_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    handler = stderr_handler(PACKAGE, colours=False)
    handler.emit(_record())
    assert stream.getvalue().endswith(f"INFO     {PACKAGE}.server: started\n")
    assert isinstance(stderr_handler(PACKAGE, colours=True).formatter, Console)


def test_a_json_line_is_one_line_with_its_fields() -> None:
    record = _record(message="first\nsecond")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record.exc_info = sys.exc_info()
    line = Json().format(record)
    assert "\n" not in line
    found = json.loads(line)
    assert found["time"] == Redacting().formatTime(record)
    assert (found["level"], found["source"]) == ("INFO", f"{PACKAGE}.server")
    assert found["message"] == "first\nsecond"
    assert found["traceback"].endswith("RuntimeError: boom")


def test_a_json_line_without_a_traceback_has_no_such_field() -> None:
    assert "traceback" not in json.loads(Json().format(_record()))


def test_a_program_adds_fields_but_replaces_none() -> None:
    def fields(record: logging.LogRecord) -> dict[str, object] | None:
        return {"status": 200, "message": "not this"} if record.name == "x" else None

    found = json.loads(Json(fields).format(_record("x")))
    assert (found["status"], found["message"]) == (200, "started")
    assert "status" not in json.loads(Json(fields).format(_record()))


def test_a_json_line_masks_a_secret_before_encoding_it() -> None:
    """JSON writes a quote, a backslash and a line break anew: masking
    the finished line would miss a secret holding one."""
    secret = 'pa"ss\\wörd\nline'
    redact.note(secret)
    record = _record(message=f"echoed {secret}")
    try:
        raise RuntimeError(f"raised {secret}")
    except RuntimeError:
        record.exc_info = sys.exc_info()
    line = Json(lambda _: {"path": f"/x/{secret}"}).format(record)
    found = json.loads(line)
    assert found["message"] == "echoed ***"
    assert found["traceback"].endswith("RuntimeError: raised ***")
    assert found["path"] == "/x/***"
    assert "wörd" not in line


def test_a_json_line_masks_a_secret_in_the_arguments() -> None:
    redact.note("an-argument-secret")
    record = _record(message="sent %s")
    record.args = ("an-argument-secret",)
    assert json.loads(Json().format(record))["message"] == "sent ***"
