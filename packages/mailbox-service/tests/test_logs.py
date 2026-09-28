"""The log of ``serve``: what reaches it, in which form."""

from __future__ import annotations

import logging
import logging.config
import re

import pytest

from benethos_mailbox_service import logs
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.main import Services

from .conftest import ADMIN


def configure(level: str) -> None:
    logging.config.dictConfig(logs.log_config(level))


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
        if "sign-in to the UI as Anna" in line
    )
    when, _, rest = line.partition(" INFO     ")
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", when)
    assert rest.startswith("benethos_mailbox_service.domain.auth: ")
    assert "from 10.0.0.1" in line


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
