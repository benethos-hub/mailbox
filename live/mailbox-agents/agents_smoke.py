"""The read-only live check, against the test account of
containers/live/mailbox-agents/.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/agents_smoke.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

It asks the service for its version, which has to be in a tested line, and
reads the change feed, the folders, every message of the last weeks, a
thread and the attachments, through the package's own module for the
mailbox service, and runs the agent ``counting`` over all of it with a
state file in a folder of its own. It writes nothing to the mailbox. Each
check says ok, skipped or FAILED, and the exit code is 1 if one failed.
Never point it at an account that is not a test account.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from agents_common import (  # beside this script
    DAYS,
    Skip,
    connect_mailbox,
    mail,
    parse_settings,
    run_checks,
    worker,
)

from benethos_mailbox_agents.agents.counting.agent import Counting
from benethos_mailbox_agents.records import MailMessage, MessageRef
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import Store

# What containers/live/mailbox-agents/mail.py puts into the test account.
INVENTED = len(list(mail.messages("me@invented.example")))
PDFS = sum(
    1
    for _, _, message in mail.messages("me@invented.example")
    for part in message.iter_attachments()
    if part.get_content_type() == "application/pdf"
)
SUB_FOLDER = mail.SUB_FOLDERS[0]


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    refs: list[MessageRef] = field(default_factory=list)
    messages: list[MailMessage] = field(default_factory=list)

    @property
    def accounts(self) -> list[str]:
        return self.settings.accounts


async def version(live: Live) -> str:
    found = await live.mailbox.ensure_tested()
    return f"the service runs {found}, a tested line"


async def feed(live: Live) -> str:
    state = await live.mailbox.start(live.accounts)
    events, after = await live.mailbox.changes(state, live.accounts)
    return f"state read, {len(events)} changes since it, state {after}"


async def folders(live: Live) -> str:
    found = await live.mailbox.folders(live.accounts[0])
    missing = {"inbox", "sent"} - {f.role for f in found.values()}
    if missing:
        raise AssertionError(f"no folder with the roles {sorted(missing)}")
    if SUB_FOLDER not in {f.path for f in found.values()}:
        raise AssertionError(f"the folder {SUB_FOLDER} is missing")
    return f"{len(found)} folders, inbox and sent, {SUB_FOLDER}"


async def recent(live: Live) -> str:
    """The service syncs the account after it was connected: wait for it."""
    end = time.monotonic() + 120
    since = date.today() - timedelta(days=DAYS)
    while True:
        live.refs = await live.mailbox.recent(
            since, live.accounts, roles=("inbox", "sent")
        )
        if len(live.refs) >= INVENTED or time.monotonic() > end:
            break
        await asyncio.sleep(3)
    if len(live.refs) < INVENTED:
        raise AssertionError(f"{len(live.refs)} messages, {INVENTED} expected")
    return f"{len(live.refs)} messages in the inbox and in sent mail"


async def fetch(live: Live) -> str:
    if not live.refs:
        raise Skip("no messages")
    live.messages = [await live.mailbox.message(ref) for ref in live.refs]
    empty = [m for m in live.messages if not m.text.strip()]
    if empty:
        raise AssertionError(f"{len(empty)} messages without text")
    return f"{len(live.messages)} fetched, each with text and folders"


async def attachments(live: Live) -> str:
    found = [
        a.filename
        for m in live.messages
        for a in m.attachments
        if a.content_type == "application/pdf"
    ]
    if len(found) < PDFS:
        raise AssertionError(f"{len(found)} PDF attachments, {PDFS} expected")
    return f"{len(found)} PDF attachments, each named"


async def thread(live: Live) -> str:
    replies = [m for m in live.messages if m.in_reply_to and m.thread_id]
    if not replies:
        raise Skip("no reply with a thread among the messages")
    first = replies[0]
    found = await live.mailbox.thread(first.ref.account_id, first.thread_id or "")
    roles = {f.role for m in found.messages for f in m.folders}
    if len(found.messages) < 2 or not {"inbox", "sent"} <= roles:
        raise AssertionError(f"the thread holds {len(found.messages)} messages")
    return f"{len(found.messages)} messages, sent and received"


async def counting(live: Live) -> str:
    with tempfile.TemporaryDirectory() as folder:
        agent = Counting(live.settings.model_copy(update={"data_dir": Path(folder)}))
        with Store.open(Path(folder) / "counting.db") as store:
            counter = worker(agent, store, live.mailbox)
            await counter.run_pass()
            taken = await counter.backfill(DAYS)
            await counter.drain()
            counts = store.counts()
    if counts["done"] != taken or taken < INVENTED:
        raise AssertionError(f"{taken} taken up, counts {counts}")
    return f"{taken} taken up and done, nothing written to the mailbox"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("the version of the service", version),
    ("feed", feed),
    ("folders", folders),
    ("recent messages", recent),
    ("every message", fetch),
    ("attachments", attachments),
    ("a thread", thread),
    ("the agent counting", counting),
]


async def run(settings: Settings) -> int:
    async with connect_mailbox(settings) as mailbox:
        failed = await run_checks(Live(settings, mailbox), CHECKS)
    return 1 if failed else 0


if __name__ == "__main__":
    found = parse_settings("smoke", "The read-only live check.")
    sys.exit(asyncio.run(run(found)))
