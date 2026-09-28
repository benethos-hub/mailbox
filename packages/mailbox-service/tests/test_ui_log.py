"""The service log in the configuration UI, for the admin alone."""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.logbook import LogBook
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.secrets import redact
from benethos_mailbox_service.domain.servicelog import ServiceLog
from benethos_mailbox_service.errors import BadRequestError, ForbiddenError
from benethos_mailbox_service.main import Services, build_services, create_app

from .conftest import ADMIN, CHEAP, browser_admin, browser_user
from .ui_helpers import sign_in

SERVICE = logging.getLogger("benethos_mailbox_service.domain.users")


@pytest.fixture
def book() -> LogBook:
    """The lines behind the page, fed by the service's loggers at info."""
    book = LogBook()
    package = logging.getLogger("benethos_mailbox_service")
    package.addHandler(book)
    package.setLevel(logging.INFO)
    return book


@pytest.fixture
def logged(book: LogBook) -> Iterator[tuple[TestClient, Services]]:
    settings = Settings()
    services = build_services(settings, password_hasher=CHEAP, logbook=book)
    with TestClient(create_app(settings, services)) as client:
        yield client, services


def test_the_admin_reads_the_log(logged: tuple[TestClient, Services]) -> None:
    client, services = logged
    sign_in(client, *browser_admin(services))
    assert 'href="/ui/log"' in client.get("/ui").text
    page = client.get("/ui/log").text
    assert 'href="/ui/log" class="active"' in page
    # The page shows its own reader's sign-in, to the millisecond.
    assert "signed in to the UI" in page
    assert re.search(
        r'<td class="mono">\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}</td>', page
    )
    assert "benethos_mailbox_service.activity.auth" in page


def test_the_log_is_for_the_admin_alone(logged: tuple[TestClient, Services]) -> None:
    client, services = logged
    sign_in(
        client, *browser_user(services, Grant(accounts=["*"], allow=["users.manage"]))
    )
    assert 'href="/ui/log"' not in client.get("/ui").text
    assert client.get("/ui/log").status_code == 403


def test_the_filter_bar_narrows_the_lines(logged: tuple[TestClient, Services]) -> None:
    client, services = logged
    sign_in(client, *browser_admin(services))
    SERVICE.info("an ordinary line about anna")
    SERVICE.warning("a warning about bert")
    warnings = client.get("/ui/log", params={"level": "warning"}).text
    assert "a warning about bert" in warnings
    assert "an ordinary line about anna" not in warnings
    searched = client.get("/ui/log", params={"text": "ANNA"}).text
    assert "an ordinary line about anna" in searched
    assert "a warning about bert" not in searched


def test_the_log_pages_newest_first(logged: tuple[TestClient, Services]) -> None:
    client, services = logged
    sign_in(client, *browser_admin(services))
    for n in range(60):
        SERVICE.info("line number %03d", n)
    first = client.get("/ui/log", params={"text": "line number"}).text
    assert first.index("line number 059") < first.index("line number 010")
    assert "line number 009" not in first
    older = re.search(r'<a class="btn small" href="([^"]+)">Older</a>', first)
    assert older is not None
    second = client.get(html.unescape(older.group(1))).text
    assert "line number 009" in second and "line number 059" not in second
    assert ">Newest</a>" in second


def test_a_secret_in_a_line_is_masked(logged: tuple[TestClient, Services]) -> None:
    client, services = logged
    sign_in(client, *browser_admin(services))
    redact.note("an-account-password")
    SERVICE.warning("the server echoed an-account-password")
    page = client.get("/ui/log").text
    assert "an-account-password" not in page
    assert "the server echoed ***" in page


def test_a_traceback_is_kept(book: LogBook) -> None:
    try:
        raise RuntimeError("it broke")
    except RuntimeError:
        SERVICE.exception("a bug")
    [line] = book.newest_first()
    assert line.level == "ERROR"
    assert line.message.startswith("a bug\nTraceback")
    assert "RuntimeError: it broke" in line.message


def test_the_domain_refuses_what_it_cannot_read(services: Services) -> None:
    log = ServiceLog(LogBook())
    with pytest.raises(BadRequestError, match="no log level loud"):
        log.lines(ADMIN, level="loud")
    with pytest.raises(BadRequestError, match="invalid cursor"):
        log.lines(ADMIN, cursor="yesterday")
    user = services.users.create_user(
        ADMIN, "reader", [], [Grant(accounts=["*"], allow=["mail.read"])]
    )
    with pytest.raises(ForbiddenError):
        log.lines(services.auth.access_of(user.id))


def test_only_the_newest_lines_are_kept() -> None:
    book = LogBook(kept=3)
    logger = logging.getLogger("benethos_mailbox_service.test.kept")
    logger.addHandler(book)
    logger.setLevel(logging.INFO)
    for n in range(5):
        logger.info("line %d", n)
    assert [line.message for line in book.newest_first()] == [
        "line 4",
        "line 3",
        "line 2",
    ]
    logger.removeHandler(book)
