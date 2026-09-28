"""The log of ``serve``: what reaches it, in which form."""

from __future__ import annotations

import io
import logging
import logging.config
import re
import sys
from datetime import datetime

import pytest

from benethos_mailbox_service import logs
from benethos_mailbox_service.data.logbook import LogBook
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.secrets import redact
from benethos_mailbox_service.main import Services

from .conftest import ADMIN


def configure(level: str) -> None:
    logging.config.dictConfig(logs.log_config(level, colours=False))


async def test_a_sign_in_reaches_the_log(
    services: Services, capsys: pytest.CaptureFixture[str]
) -> None:
    configure("info")
    user = services.users.create_user(
        ADMIN, "Anna", [], [Grant(accounts=["*"], allow=["mail.read"])], ui_sign_in=True
    )
    await services.users.set_password(ADMIN, user.id, "correct horse battery staple")
    await services.auth.sign_in(
        "Anna", "correct horse battery staple", source="10.0.0.1"
    )
    line = next(
        line
        for line in capsys.readouterr().err.splitlines()
        if "signed in to the UI" in line
    )
    when, _, rest = line.partition(" INFO     ")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d", when)
    assert rest.startswith("benethos_mailbox_service.activity.auth: ")
    assert f"Anna ({user.id}) signed in to the UI from 10.0.0.1" in line


def test_the_level_names_what_the_service_writes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure("warning")
    service = logging.getLogger(f"{logs.PACKAGE}.domain.users")
    service.info("an info line")
    service.warning("a warning line")
    configure("debug")
    service.debug("a debug line")
    err = capsys.readouterr().err
    assert "an info line" not in err
    assert "WARNING  benethos_mailbox_service.domain.users: a warning line" in err
    assert "a debug line" in err


def test_libraries_speak_from_warning_on(capsys: pytest.CaptureFixture[str]) -> None:
    """httpx names every request with its URL at INFO, and a library at
    debug may echo what it sends to a server."""
    configure("debug")
    logging.getLogger("httpx").info("HTTP Request: GET https://example.org/?q=secret")
    logging.getLogger("imapclient").debug("> LOGIN user password")
    logging.getLogger("httpx").warning("a library warning")
    err = capsys.readouterr().err
    assert "q=secret" not in err and "LOGIN" not in err
    assert "a library warning" in err


def test_uvicorn_writes_to_the_same_stream(capsys: pytest.CaptureFixture[str]) -> None:
    configure("info")
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/health", "1.1", 200
    )
    err = capsys.readouterr().err
    assert "INFO     uvicorn.error: Application startup complete." in err
    assert 'uvicorn.access: 127.0.0.1:5000 - "GET /health HTTP/1.1" 200' in err


@pytest.mark.parametrize("level", sorted(logs.LEVELS))
def test_every_level_of_the_settings_is_known(level: str) -> None:
    configure(level)
    assert logging.getLogger(logs.PACKAGE).level == logs.LEVELS[level]


def test_the_time_is_to_the_millisecond() -> None:
    """The plain line with its offset, the terminal without."""
    record = logging.makeLogRecord({"created": 1790590342.1239})
    local = datetime.fromtimestamp(1790590342.1239).astimezone()
    offset = local.isoformat()[-6:]
    day = f"{local:%Y-%m-%d %H:%M:%S}"
    assert logs.Redacting().formatTime(record) == f"{day}.123{offset}"
    assert logs.Console().formatTime(record) == f"{day}.123"


# --- at a terminal --------------------------------------------------------------------


def test_a_terminal_gets_short_lines_in_colour(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.config.dictConfig(logs.log_config("info", colours=True))
    logging.getLogger(f"{logs.PACKAGE}.domain.auth").info("sign-in to the UI as anna")
    logging.getLogger(f"{logs.PACKAGE}.main").warning("a warning")
    err = capsys.readouterr().err
    assert "\033[32mINFO    \033[0m\033[36mdomain.auth   \033[0m sign-in" in err
    assert "\033[33mWARNING \033[0m\033[36mmain          \033[0m a warning" in err
    assert re.search(r"\033\[2m\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}\033\[0m ", err)


@pytest.mark.parametrize(
    ("status", "shown"),
    [
        (200, "\033[32m200 OK"),
        (303, "\033[33m303 See Other"),
        (404, "\033[31m404 Not Found"),
    ],
)
def test_an_access_line_names_the_status_in_colour(
    capsys: pytest.CaptureFixture[str], status: int, shown: str
) -> None:
    logging.config.dictConfig(logs.log_config("info", colours=True))
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", "/ui", "1.1", status
    )
    err = capsys.readouterr().err
    assert f"\033[36mhttp          \033[0m GET /ui {shown}\033[0m" in err
    assert "\033[2m127.0.0.1:5000\033[0m" in err


def test_a_coloured_line_masks_secrets_and_keeps_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logging.config.dictConfig(logs.log_config("info", colours=True))
    redact.note("a-password-in-a-line")
    try:
        raise RuntimeError("echoed a-password-in-a-line")
    except RuntimeError:
        logging.getLogger(f"{logs.PACKAGE}.domain.sync").exception("a bug")
    err = capsys.readouterr().err
    assert "a-password-in-a-line" not in err
    assert "a bug\nTraceback" in err and "RuntimeError: echoed ***" in err


@pytest.mark.parametrize(
    ("name", "short"),
    [
        (f"{logs.PACKAGE}.domain.auth", "domain.auth"),
        ("uvicorn.error", "uvicorn"),
        ("uvicorn.access", "http"),
        ("httpx", "httpx"),
    ],
)
def test_the_source_is_short(name: str, short: str) -> None:
    assert logs.short_source(name) == short


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_colours_on_a_terminal_unless_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stderr", Terminal())
    assert logs.colours_wanted()
    monkeypatch.setenv("NO_COLOR", "1")
    assert not logs.colours_wanted()
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert not logs.colours_wanted()


@pytest.mark.parametrize("colours", [False, True])
def test_an_access_line_leaves_out_the_query(
    capsys: pytest.CaptureFixture[str], colours: bool
) -> None:
    """A query holds what a person typed, such as the words of a search."""
    book = LogBook()
    logging.config.dictConfig(logs.log_config("info", book, colours=colours))
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:5000",
        "GET",
        "/v1/messages?q=holiday+plans&from=anna",
        "1.1",
        200,
    )
    err = capsys.readouterr().err
    assert "/v1/messages" in err and "holiday" not in err and "anna" not in err
    [entry] = book.newest_first()
    assert "/v1/messages" in entry.message and "holiday" not in entry.message
