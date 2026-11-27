"""State files for the tests of the cockpit, and a mailbox that answers
one message."""

from __future__ import annotations

import inspect
import re
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from benethos_mailbox_agents.contract import Reader
from benethos_mailbox_agents.records import (
    Address,
    MailMessage,
    MessageRef,
    Profile,
    StepResult,
    Thread,
)
from benethos_mailbox_agents.store import MIGRATIONS, Store

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
REF = MessageRef(account_id="acc1", message_id="m1")
# The secret of the cockpit in the tests.
SECRET = "cockpit-secret-value"  # pragma: allowlist secret
# A subject that would move a terminal and open a script, were it drawn
# as it is.
SUBJECT = "Your invoice\x1b[2J <script>alert(1)</script>"

PROFILE = Profile(
    agent="counting",
    instance=None,
    agent_version="1",
    package_version="0.11.1",
    stage="shadow",
    accounts=(),
    keyword="agent-counted",
    poll_seconds=60.0,
    gateway_timeout_seconds=120.0,
    model_alias="",
    prompt_version="",
    started=NOW - timedelta(hours=1),
)


def filled(path: Path, profile: Profile | None = PROFILE) -> Path:
    """A state file with one message decided and one action recorded,
    closed again, so it reads as stopped."""
    with Store.open(path) as store:
        if profile is not None:
            store.set_profile(profile)
        store.enqueue(REF, NOW - timedelta(minutes=5))
        store.add_step(
            REF,
            StepResult(
                step="decision",
                prompt_version="v1",
                model="reported-model",
                result={
                    "label": "invoice",
                    "source": "model",
                    "evidence": [
                        {"field": "label", "value": "invoice", "quote": SUBJECT}
                    ],
                },
                at=NOW - timedelta(minutes=4),
            ),
            "alias",
        )
        store.set_state(REF, "done", NOW - timedelta(minutes=4))
        store.add_action(
            REF,
            action="add_keyword",
            argument="agent-counted",
            before=[],
            stage="shadow",
            executed=False,
            now=NOW - timedelta(minutes=4),
        )
        store.set_progress(NOW - timedelta(minutes=1))
    return path


def older(path: Path) -> Path:
    """A state file of schema 3, before the profile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as raw, raw:
        for number in (1, 2, 3):
            for statement in MIGRATIONS.step(number).statements:
                raw.execute(inspect.cleandoc(statement))
        raw.execute("PRAGMA user_version = 3")
    return path


def newer(path: Path) -> Path:
    """A state file of a schema this program does not know."""
    filled(path)
    with closing(sqlite3.connect(path)) as raw, raw:
        raw.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    return path


class _Mailbox:
    async def message(self, ref: MessageRef) -> MailMessage:
        return MailMessage(
            ref=ref,
            subject=SUBJECT,
            sender=Address(email="billing@example.org", name="Billing‮"),
        )

    async def thread(self, account_id: str, thread_id: str) -> Thread:
        raise NotImplementedError


@asynccontextmanager
async def mailbox() -> AsyncIterator[Reader]:
    """The mailbox service, answering every message with :data:`SUBJECT`."""
    yield _Mailbox()


def signed_in(client: TestClient) -> TestClient:
    """``client`` with a session of the cockpit."""
    page = client.get("/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    assert nonce is not None
    answer = client.post("/login", data={"secret": SECRET, "nonce": nonce[1]})
    assert answer.headers["location"] == "/"
    return client
