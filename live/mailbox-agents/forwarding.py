"""The live check of the actor forwarding, against the test account of
containers/live/mailbox-agents/. It WRITES drafts to that account and
deletes them again. It sends nothing.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/forwarding.py
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

It signs in to the UI of the service as the administrator of the live
setup, makes a token of one day, and with it a user of its own with
mail.read and drafts on the test account. The user agents sets
``agent-invoice`` on two invoices of the invented mail, as an instance of
categorization would. Then forwarding, under the user of its own: in
``shadow`` no draft, in ``suggest`` exactly one draft per message in the
drafts folder, to the address of the list, with a reference to the
original, once inline and once as an attachment, the original unchanged.
A second run drafts none more. What the sender check says on this server
is read and both cases of the rule shown. Last it deletes the drafts,
takes the keyword off, deletes the user and revokes the token. Each check
says ok or FAILED, and the exit code is 1 if one failed. Never point it
at an account that is not a test account.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import sys
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
from agents_common import (  # beside this script
    DAYS,
    LIVE,
    connect_mailbox,
    parse_settings,
    run_checks,
    snapshot,
    worker,
)
from common.admin import csrf_of, ui_sign_in
from pydantic import SecretStr

from benethos_mailbox_agents.agents.forwarding.agent import Forwarding
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import Store
from benethos_mailbox_client import Grant, SyncMailboxClient

# The invoices of the invented mail by the local part of their Message-ID.
INVOICES = ("inv-cloudhost-1", "inv-telco-1")
KEYWORD = "agent-invoice"
TO = "books@example.org"


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    folder: Path
    stack: ExitStack
    admin: SyncMailboxClient | None = None
    admin_token: tuple[str, str] | None = None
    user_id: str | None = None
    forwarder: Settings | None = None
    invoices: list[MessageRef] = field(default_factory=list)
    before: dict[MessageRef, Any] = field(default_factory=dict)
    sender_check: str = ""
    stores: dict[str, Store] = field(default_factory=dict)

    def account(self) -> str:
        return self.settings.accounts[0]

    def drafts_of(self, ref: MessageRef) -> list[dict[str, Any]]:
        """The drafts of the account that forward ``ref``: their id, their
        addresses, their form and whether the service set the subject. The
        draft keeps the action and the original, not the form: a forward as
        an attachment carries the original as message/rfc822."""
        assert self.admin is not None
        found = []
        for draft in self.admin.list_drafts(ref.account_id).items:
            whole = self.admin.get_message(ref.account_id, draft.id)
            named = whole.reference
            if named and (named.message_id, named.action) == (
                ref.message_id,
                "forward",
            ):
                found.append(
                    {
                        "id": draft.id,
                        "to": sorted(a.email.casefold() for a in whole.to),
                        "form": "attachment"
                        if any(
                            a.content_type == "message/rfc822"
                            for a in whole.attachments
                        )
                        else "inline",
                        "fwd": (whole.subject or "").startswith("Fwd:"),
                    }
                )
        return found

    async def forward(
        self, ref: MessageRef, stage: str, form: str, check: str, name: str
    ) -> int:
        """One run of forwarding over the last days, with a list for one
        rule, its state file ``name``. Answers how many drafts forward
        ``ref`` after it."""
        assert self.forwarder is not None
        listed = self.folder / f"{name}.json"
        rule = {"keywords": [KEYWORD], "to": [TO], "forward_as": form}
        listed.write_text(
            json.dumps({"rules": [{**rule, "sender_check": check}]}), encoding="utf-8"
        )
        found = self.forwarder.model_copy(
            update={"stage": stage, "forwarding_file": listed, "data_dir": self.folder}
        )
        agent = Forwarding(found)
        agent.prepare()
        if name not in self.stores:
            path = self.folder / f"{name}.db"
            self.stores[name] = self.stack.enter_context(Store.open(path))
        store = self.stores[name]
        async with connect_mailbox(found) as own:
            running = worker(agent, store, own)
            await running.backfill(DAYS, again=True)
            await running.drain()
        return len(self.drafts_of(ref))


def _admin_password() -> str:
    """The password of the administrator of the live setup, from its file."""
    found = (LIVE / "secrets" / "service-admin").read_text(encoding="utf-8")
    return found.strip().partition(":")[2]


def _admin_token(url: str) -> str:
    """A token of the administrator for one day, made in the UI as an
    operator would."""
    with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as browser:
        ui_sign_in(browser, "admin", _admin_password())
        users = browser.get("/ui/users").text
        user = re.search(r'href="/ui/users/(usr_[0-9a-f]+)"', users)
        if user is None:
            raise AssertionError("the UI lists no administrator")
        page = browser.get(f"/ui/users/{user.group(1)}?tab=access").text
        made = browser.post(
            f"/ui/users/{user.group(1)}/tokens",
            data={"csrf_token": csrf_of(page), "name": "live forwarding", "days": "1"},
        )
        token = re.search(r'<code class="secret"[^>]*>(mbx_[A-Za-z0-9_-]+)', made.text)
        if token is None:
            raise AssertionError("the UI showed no token")
        return token.group(1)


async def setup(live: Live) -> str:
    url = live.settings.service_url or ""
    token = _admin_token(url)
    live.admin = live.stack.enter_context(
        SyncMailboxClient(base_url=url, token=token, allow_http=True)
    )
    me = live.admin.get_me()
    mine = [
        t for t in live.admin.list_tokens(me.user_id) if t.name == "live forwarding"
    ]
    live.admin_token = (me.user_id, mine[-1].id)
    user = live.admin.create_user(
        f"live forwarding {secrets.token_hex(3)}",
        grants=[Grant((live.account(),), ("mail.read", "drafts"))],
    )
    live.user_id = user.id
    secret = live.admin.create_token(user.id, "live").secret.get_secret_value()
    live.forwarder = live.settings.model_copy(
        update={"service_token": SecretStr(secret), "service_token_file": None}
    )
    return "a user of its own with mail.read and drafts, and its token"


async def keyword(live: Live) -> str:
    since = date.today() - timedelta(days=DAYS)
    found = await live.mailbox.recent(since, live.settings.accounts, roles=("inbox",))
    for ref in found:
        message = await live.mailbox.message(ref)
        local = (message.message_id_header or "").strip("<>").split("@")[0]
        if local in INVOICES:
            live.invoices.append(ref)
            live.sender_check = message.sender_check
    if len(live.invoices) != len(INVOICES):
        raise AssertionError("the two invoices are not in the inbox")
    # On the first alone: a run with a state file of its own takes up
    # every message that carries it, as after a state file made anew.
    await live.mailbox.add_keyword(live.invoices[0], KEYWORD)
    live.before = await snapshot(live.mailbox, live.invoices)
    said = f"the sender check of the server says {live.sender_check}"
    return f"{KEYWORD} on the first invoice, {said}"


async def shadow(live: Live) -> str:
    ref = live.invoices[0]
    if await live.forward(ref, "shadow", "inline", "off", "shadow"):
        raise AssertionError("shadow drafted a forward")
    return "no draft"


async def sender_check(live: Live) -> str:
    """The rule with the check required: a draft only when it passed."""
    ref = live.invoices[0]
    made = await live.forward(ref, "suggest", "inline", "required", "required")
    wanted = 1 if live.sender_check == "pass" else 0
    if made != wanted:
        raise AssertionError(f"{made} drafts with the check {live.sender_check}")
    # A state file of its own: the run in suggest that follows would
    # draft one more, so this one goes again.
    assert live.admin is not None
    for draft in live.drafts_of(ref):
        live.admin.delete_draft(ref.account_id, draft["id"])
    return f"check {live.sender_check}, required: {made} draft"


async def suggest(live: Live) -> str:
    ref = live.invoices[0]
    made = await live.forward(ref, "suggest", "inline", "off", "suggest")
    [draft] = live.drafts_of(ref)
    if made != 1 or draft["to"] != [TO] or draft["form"] != "inline":
        raise AssertionError(f"{made} drafts, {draft['form']}")
    if not draft["fwd"]:
        raise AssertionError("the subject of the draft does not start with Fwd:")
    if await snapshot(live.mailbox, [ref]) != {ref: live.before[ref]}:
        raise AssertionError("the original changed")
    return "one draft inline to the list's address, Fwd:, the original unchanged"


async def attachment(live: Live) -> str:
    """The keyword moves to the second invoice, a list asks for an
    attachment."""
    first, ref = live.invoices
    await live.mailbox.remove_keyword(first, KEYWORD)
    await live.mailbox.add_keyword(ref, KEYWORD)
    made = await live.forward(ref, "suggest", "attachment", "off", "attachment")
    if len(live.drafts_of(first)) != 1:
        raise AssertionError("the first invoice got a second draft")
    [draft] = live.drafts_of(ref)
    if made != 1 or draft["form"] != "attachment":
        raise AssertionError(f"{made} drafts, {draft['form']}")
    return "one draft as an attachment"


async def again(live: Live) -> str:
    ref = live.invoices[0]
    if await live.forward(ref, "suggest", "inline", "off", "suggest") != 1:
        raise AssertionError("a second run drafted a second forward")
    return "no second draft"


async def clean(live: Live) -> str:
    deleted = 0
    if live.admin is not None:
        for ref in live.invoices:
            for draft in live.drafts_of(ref):
                live.admin.delete_draft(ref.account_id, draft["id"])
                deleted += 1
    for ref in live.invoices:
        message = await live.mailbox.message(ref)
        if message.has_keyword(KEYWORD):
            await live.mailbox.remove_keyword(ref, KEYWORD)
    if live.admin is not None and live.user_id is not None:
        live.admin.delete_user(live.user_id)
        live.user_id = None
    if live.admin is not None and live.admin_token is not None:
        live.admin.revoke_token(*live.admin_token)
        live.admin_token = None
    return f"{deleted} drafts deleted, the keyword off, the user and the token gone"


CHECKS: list[tuple[str, Callable[[Live], Awaitable[str]]]] = [
    ("a user of its own", setup),
    ("the keyword set by hand", keyword),
    ("forwarding in shadow", shadow),
    ("the sender check required", sender_check),
    ("forwarding in suggest", suggest),
    ("a second run", again),
    ("a forward as an attachment", attachment),
    ("put back", clean),
]


async def run(settings: Settings) -> int:
    async with connect_mailbox(settings) as mailbox:
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            live = Live(settings, mailbox, Path(folder), stack)
            try:
                failed = await run_checks(live, CHECKS, stop=True)
            finally:
                if live.user_id is not None or live.admin_token is not None:
                    print(f"         {await clean(live)}")
    return 1 if failed else 0


if __name__ == "__main__":
    found = parse_settings("forwarding", "The live check of the actor forwarding.")
    sys.exit(asyncio.run(run(found)))
