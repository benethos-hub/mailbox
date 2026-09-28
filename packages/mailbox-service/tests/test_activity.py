"""Activities: the catalogue, the recorder, who acted and from where
(docs/LOGGING.md sections 3, 6 and 7)."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import re
import typing
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service import logs
from benethos_mailbox_service.data.models import (
    Grant,
    OutgoingMessage,
    Recipient,
    SentMessage,
    User,
)
from benethos_mailbox_service.domain.access import Access
from benethos_mailbox_service.domain.activity import (
    WORKER,
    Activity,
    ActivityLog,
    Actor,
    Failure,
    catalogue,
)
from benethos_mailbox_service.domain.activity.catalogue import users as said
from benethos_mailbox_service.errors import StorageError
from benethos_mailbox_service.main import Services, _loop

from .conftest import ADMIN, admin_bearer, memory_of
from .ui_helpers import post

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
LEVELS = {logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR}
# What no field of an activity may hold: a secret, the words of a mail,
# the addresses of its people, what a person typed to search.
FORBIDDEN_TYPES = {
    "SecretStr",
    "bytes",
    "Message",
    "MessageSummary",
    "DraftMessage",
    "OutgoingMessage",
    "AttachmentContent",
    "MessageFilter",
    "Recipient",
    "Address",
}
FORBIDDEN_NAMES = {"password", "secret", "plain", "subject", "body", "url", "query"}


def _catalogue() -> list[type[Activity]]:
    found = []
    for info in pkgutil.iter_modules(catalogue.__path__):
        module = importlib.import_module(f"{catalogue.__name__}.{info.name}")
        found += [
            value
            for value in vars(module).values()
            if isinstance(value, type)
            and issubclass(value, Activity)
            and value.__module__ == module.__name__
        ]
    return found


# The packages of docs/REFACTORING.md section 4 that record, and the two
# areas beyond them (docs/LOGGING.md 7.2).
AREAS = {
    "service",
    "auth",
    "users",
    "accounts",
    "discovery",
    "mailbox",
    "sync",
    "changes",
    "webhooks",
    "http",
}
NAME = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")
LOGGING_MD = Path(__file__).resolve().parents[3] / "docs" / "LOGGING.md"


def test_the_areas_are_the_packages_of_the_domain() -> None:
    assert {cls.area for cls in _catalogue()} == AREAS


def test_each_name_is_unique_within_its_area() -> None:
    sources = [cls.source() for cls in _catalogue()]
    assert len(sources) == len(set(sources))


def test_every_activity_is_listed_in_the_concept_and_nothing_else() -> None:
    """LOGGING.md 7.2 names every activity, and only those there are."""
    text = LOGGING_MD.read_text(encoding="utf-8")
    section = text.partition("### 7.2 Names")[2].partition("\n## ")[0]
    listed = set(re.findall(r"^\| `(\w+\.\w+)` \|", section, re.MULTILINE))
    assert listed == {f"{cls.area}.{cls.name}" for cls in _catalogue()}


@pytest.mark.parametrize("cls", _catalogue(), ids=lambda cls: cls.__name__)
def test_each_activity_has_a_level_a_line_and_no_secret(cls: type[Activity]) -> None:
    assert cls.area == cls.__module__.rpartition(".")[2]
    # Set in the class, not taken from its name (docs/LOGGING.md 7.2).
    assert "name" in vars(cls), "each activity sets its name"
    assert NAME.fullmatch(cls.name), cls.name
    assert not cls.name.startswith(cls.area.rstrip("s") + "_"), "the area twice"
    assert len(cls.source()) <= logs.SOURCE_WIDTH, cls.source()
    assert cls.level in LEVELS
    assert cls.says is not Activity.says, "says() writes the line"
    hints = typing.get_type_hints(cls)
    for field in fields(cls):
        shown = repr(hints[field.name])
        assert not any(name in shown for name in FORBIDDEN_TYPES), field
        assert not any(word in field.name for word in FORBIDDEN_NAMES), field


def test_an_actor_names_the_user_its_token_and_the_address() -> None:
    access = Access(
        "usr_1",
        "Claude Desktop",
        [],
        "tok_1",
        credential_name="laptop",
        source="10.0.0.9",
    )
    line = said.PasswordChanged(by=Actor.of(access)).line()
    assert (
        line
        == "Claude Desktop (usr_1, token laptop) changed its password from 10.0.0.9"
    )
    assert said.PasswordChanged(by=WORKER).line() == "the worker changed its password"


def test_the_recorder_writes_under_the_area_at_the_level(
    caplog: pytest.LogCaptureFixture,
) -> None:
    anna = User(id="usr_2", name="Anna")
    with caplog.at_level(logging.INFO):
        done = ActivityLog(lambda: NOW).record(
            said.UserDeleted(by=Actor.of(ADMIN), user=anna, webhooks=1)
        )
    assert done.at == NOW
    [record] = caplog.records
    assert record.name == "benethos_mailbox_service.activity.users.deleted"
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        "test admin (usr_test_admin) deleted user Anna (usr_2) and its 1 webhook"
    )


@dataclass(frozen=True, kw_only=True)
class _Broke(Failure):
    name = "broke"

    def says(self) -> str:
        return "broke"


def test_a_failure_of_ours_is_a_warning_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ActivityLog().record(_Broke(by=WORKER, error=StorageError("the disk is full")))
    [record] = caplog.records
    assert record.levelno == logging.WARNING and record.exc_info is None
    assert record.getMessage() == "the worker broke: the disk is full"


def test_any_other_failure_is_an_error_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    try:
        raise KeyError("a bug")
    except KeyError as exc:
        ActivityLog().record(_Broke(by=WORKER, error=exc))
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert record.getMessage() == "the worker broke: KeyError"
    assert "KeyError: 'a bug'" in caplog.text


@dataclass(frozen=True, kw_only=True)
class _Costly(Activity):
    name = "costly"
    level = logging.DEBUG

    def says(self) -> str:
        raise AssertionError("built below its level")


def test_a_line_below_the_level_is_not_built(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        ActivityLog().record(_Costly(by=WORKER))
    assert not caplog.records


async def test_a_background_loop_that_ends_is_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def run() -> None:
        raise RuntimeError("the loop broke")

    with pytest.raises(RuntimeError):
        await _loop(ActivityLog(), WORKER, run)
    assert "ERROR" in caplog.text and "the worker ended: RuntimeError" in caplog.text


def test_a_caller_with_a_token_is_named_with_it_and_its_address(
    app_client: TestClient, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    doomed = services.users.create_user(ADMIN, "Doomed", [], [])
    with caplog.at_level(logging.INFO):
        answer = app_client.delete(
            f"/v1/users/{doomed.id}", headers=admin_bearer(services)
        )
    assert answer.status_code == 204
    line = next(
        r.getMessage() for r in caplog.records if "deleted user" in r.getMessage()
    )
    assert line.endswith(
        f", token tests) deleted user Doomed ({doomed.id}) and its 0 webhooks "
        "from testclient"
    )


def test_a_session_of_the_ui_names_its_address(
    ui: TestClient, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    doomed = services.users.create_user(ADMIN, "Doomed", [], [])
    with caplog.at_level(logging.INFO):
        post(ui, f"/ui/users/{doomed.id}/delete")
    assert f"deleted user Doomed ({doomed.id}) and its 0 webhooks from testclient" in (
        caplog.text
    )


async def test_a_sent_copy_the_adapter_could_not_keep_is_logged_by_the_domain(
    services: Services,
    account_id: str,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = memory_of(services, account_id)

    async def send(raw: bytes, sender: str, recipients: list[str]) -> SentMessage:
        return SentMessage(copy_error="the folder is over quota")

    monkeypatch.setattr(provider, "send", send)
    admin = Access("usr_x", "Anna", [Grant(accounts=["*"], allow=["admin"])])
    message = OutgoingMessage(to=[Recipient(email="you@example.com")], text="Hi")
    await services.mailbox.outgoing.send_message(admin, account_id, message)
    account = services.adapters.record(account_id)
    assert (
        f"Anna (usr_x) sent a message from {account.email} ({account_id}), but no "
        "copy is in the sent folder: the folder is over quota"
    ) in caplog.text
    assert "you@example.com" not in caplog.text
