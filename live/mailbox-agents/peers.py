"""The live check of the entrance for peers over A2A, against the live
setup of containers/live/mailbox-agents/ and its gateway, LiteLLM. It
READS mail of the test account and changes nothing of it. In the gateway
it enters two agents and deletes them at the end.

    sh containers/live/mailbox-agents/setup.sh          # once, in a shell with Docker
    uv run python live/mailbox-agents/peers.py --host ADDRESS
        [--env-file containers/live/mailbox-agents/secrets/agent.env]

The agent ``categorization`` with the example list ``bookkeeping``, which asks the
recognizer ``invoice``, serves the entrance at ``--host`` on port 38470,
with a token made for this run. ``--host`` is an address of this machine
that the gateway's container reaches: under WSL, the address of the
Windows side, the default route of the distro (``ip route show default``).
Then:

1. without the token the agent card is refused, with it the card names
   the agent and its skill,
2. an invoice of the invented mail asked directly is classified as one,
   a mail that is not one is not, and no answer holds its subject or
   sender,
3. the agent is entered in the gateway with the token as its static
   header, and the key of the agents asks it through ``/a2a/<agent>``,
   in A2A 1.0 and 0.3, and is told what it is told directly,
4. an agent entered without the token is told nothing, and the
   classifier is not asked,
5. the inbox is as it was.

The agents entered are deleted again, also after a failure. Each check
says ok or FAILED, and the exit code is 1 if one failed. Never point it
at an account that is not a test account.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import tempfile
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from agents_common import (  # beside this script
    ENV,
    LIVE,
    Snapshot,
    connect_mailbox,
    inbox_snapshot,
    live_settings,
    mail,
    open_gateway,
    run_checks,
    snapshot,
)

from benethos_mailbox_agents.agents.categorization.agent import Categorization
from benethos_mailbox_agents.peers import Card, Server, app
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.classify import Classifier
from benethos_mailbox_agents.settings import Settings
from benethos_mailbox_agents.sources.mailbox import Mailbox
from benethos_mailbox_agents.store import Store

PORT = 38470
LIST = LIVE / "chain" / "categorization.bookkeeping.example.json"
V1 = {"A2A-Version": "1.0"}


def _gold() -> dict[str, str]:
    """The label of ``invoices`` of each invented message in the inbox,
    by its subject."""
    found = {}
    for folder, _, message in mail.messages("me@invented.example"):
        labels = mail.GOLD.get(mail.local(str(message["Message-ID"])), {})
        if folder == "inbox" and "invoices" in labels:
            found[str(message["Subject"])] = labels["invoices"][0]
    return found


@dataclass
class Live:
    settings: Settings
    mailbox: Mailbox
    host: str
    token: str
    gateway: httpx.AsyncClient
    master: dict[str, str]
    before: Snapshot = field(default_factory=dict)
    asked: list[MessageRef] = field(default_factory=list)
    invoice: MessageRef | None = None
    other: MessageRef | None = None
    hidden: list[str] = field(default_factory=list)
    told: dict[str, Any] = field(default_factory=dict)
    entered: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{PORT}/"


def _send(data: dict[str, str], version: str = "1.0") -> dict[str, Any]:
    if version == "1.0":
        message = {"messageId": "q", "role": "ROLE_USER", "parts": [{"data": data}]}
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {"message": message},
        }
    message = {
        "messageId": "q",
        "role": "user",
        "kind": "message",
        "parts": [{"kind": "data", "data": data}],
    }
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "message/send",
        "params": {"message": message},
    }


def _data(answer: httpx.Response) -> dict[str, Any]:
    """The data part of an answer of either version."""
    result = answer.json()["result"]
    found: dict[str, Any] = result.get("message", result)["parts"][0]["data"]
    return found


def _ids(ref: MessageRef) -> dict[str, str]:
    return {"account_id": ref.account_id, "message_id": ref.message_id}


async def before(live: Live) -> str:
    live.before = await inbox_snapshot(live.mailbox, live.settings)
    gold = _gold()
    for ref in live.before:
        message = await live.mailbox.message(ref)
        label = gold.get(message.subject or "")
        if label == "invoice" and live.invoice is None:
            live.invoice = ref
        elif label == "other" and live.other is None:
            live.other = ref
        else:
            continue
        live.hidden += [
            message.subject or "",
            message.sender.email if message.sender else "",
        ]
    if live.invoice is None or live.other is None:
        raise AssertionError("the inbox lacks an invented invoice or another mail")
    return f"{len(live.before)} messages in the inbox, an invoice and another chosen"


async def card(live: Live) -> str:
    async with httpx.AsyncClient(base_url=live.url) as peer:
        refused = await peer.get("/.well-known/agent-card.json")
        given = await peer.get(
            "/.well-known/agent-card.json",
            headers={"Authorization": f"Bearer {live.token}"},
        )
    named = given.json()
    if refused.status_code != 401 or named["name"] != "categorization/bookkeeping":
        raise AssertionError(f"{refused.status_code}, card of {named.get('name')}")
    return f"refused without the token, the card names {named['name']}"


async def direct(live: Live) -> str:
    assert live.invoice is not None and live.other is not None
    headers = {"Authorization": f"Bearer {live.token}", **V1}
    async with httpx.AsyncClient(base_url=live.url, timeout=180) as peer:
        invoice = await peer.post("/", json=_send(_ids(live.invoice)), headers=headers)
        other = await peer.post("/", json=_send(_ids(live.other)), headers=headers)
    live.told = _data(invoice)
    told_other = _data(other)
    if live.told.get("fields", {}).get("kind") != "Invoice":
        raise AssertionError(f"the invoice was told {live.told}")
    if not live.told["found"].get("kind"):
        raise AssertionError("the kind of the invoice is told without its quote")
    if told_other.get("fields", {}).get("kind") == "Invoice":
        raise AssertionError("the other mail was told an invoice")
    text = invoice.text + other.text
    if any(value and value in text for value in live.hidden):
        raise AssertionError("an answer holds a subject or a sender")
    return (
        "the invoice told Invoice with its quote, the other mail not, no mail in either"
    )


def _agent(live: Live, name: str, headers: dict[str, str] | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "agent_name": name,
        "agent_card_params": {
            "protocolVersion": "1.0",
            "name": "categorization/bookkeeping",
            "description": "Classifies one message by its ids.",
            "url": live.url,
            "version": "3",
            "capabilities": {"streaming": False},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [
                {
                    "id": "classify",
                    "name": "classify",
                    "description": "The categories of one message.",
                    "tags": ["mail"],
                }
            ],
        },
        "litellm_params": {"a2a_protocol_version": "1.0"},
    }
    if headers:
        entry["static_headers"] = headers
    return entry


async def _enter(live: Live, name: str, headers: dict[str, str] | None) -> str:
    created = await live.gateway.post(
        "/v1/agents", headers=live.master, json=_agent(live, name, headers)
    )
    created.raise_for_status()
    agent_id: str = created.json()["agent_id"]
    live.entered.append(agent_id)
    return agent_id


async def through_gateway(live: Live) -> str:
    assert live.invoice is not None
    agent_id = await _enter(
        live, "mailbox-agents-live-a2a", {"Authorization": f"Bearer {live.token}"}
    )
    key = {"Authorization": f"Bearer {live.settings.secret('gateway_key')}"}
    told = []
    for version in ("1.0", "0.3"):
        headers = {**key, **(V1 if version == "1.0" else {})}
        sent = await live.gateway.post(
            f"/a2a/{agent_id}", json=_send(_ids(live.invoice), version), headers=headers
        )
        told.append(_data(sent))
    if any(found != live.told for found in told):
        raise AssertionError("the gateway passed on another answer")
    return "the key of the agents is told the same in A2A 1.0 and 0.3"


async def without_token(live: Live) -> str:
    assert live.invoice is not None
    agent_id = await _enter(live, "mailbox-agents-live-a2a-no-token", None)
    asked = len(live.asked)
    key = {"Authorization": f"Bearer {live.settings.secret('gateway_key')}", **V1}
    sent = await live.gateway.post(
        f"/a2a/{agent_id}", json=_send(_ids(live.invoice)), headers=key
    )
    if "result" in sent.json() or len(live.asked) != asked:
        raise AssertionError("an agent entered without the token was answered")
    return f"answered {sent.status_code} with an error, the classifier not asked"


async def unchanged(live: Live) -> str:
    after = await snapshot(live.mailbox, live.before)
    if after != live.before:
        raise AssertionError("the inbox changed")
    return f"{len(after)} messages as they were"


CHECKS = [
    ("the inbox before", before),
    ("the agent card and the token", card),
    ("asked directly", direct),
    ("asked through the gateway", through_gateway),
    ("an entry without the token", without_token),
    ("the inbox after", unchanged),
]


def _master() -> dict[str, str]:
    """The master key of the gateway, from secrets/gateway.env, to enter
    and delete an agent."""
    for line in (LIVE / "secrets" / "gateway.env").read_text("utf-8").splitlines():
        if line.startswith("LITELLM_MASTER_KEY="):
            return {"Authorization": f"Bearer {line.split('=', 1)[1].strip()}"}
    raise SystemExit("peers: no master key in secrets/gateway.env")


async def run(settings: Settings, host: str) -> int:
    agent = Categorization(
        settings.model_copy(
            update={"instance": "bookkeeping", "categorization_file": LIST}
        )
    )
    agent.prepare()
    token = secrets.token_urlsafe(32)
    base = (settings.gateway_url or "").removesuffix("/v1")
    async with AsyncExitStack() as stack:
        mailbox = await stack.enter_async_context(connect_mailbox(settings))
        model = await stack.enter_async_context(open_gateway(settings))
        folder = stack.enter_context(tempfile.TemporaryDirectory())
        store = stack.enter_context(Store.open(Path(folder) / "a2a.db"))
        gateway = await stack.enter_async_context(
            httpx.AsyncClient(base_url=base, timeout=180)
        )
        live = Live(settings, mailbox, host, token, gateway, _master())
        classifier = Classifier(
            agent,
            reader=mailbox,
            gateway=model,
            store=store,
            now=lambda: datetime.now(UTC),
        )

        async def classify(ref: MessageRef) -> Any:
            live.asked.append(ref)
            return await classifier.classify(ref)

        entrance = app(
            classify, Card(name=agent.label, version=agent.version, url=live.url), token
        )
        await stack.enter_async_context(Server(entrance, host, PORT).serving())
        try:
            failed = await run_checks(live, CHECKS, stop=True)
        finally:
            for agent_id in live.entered:
                await gateway.delete(f"/v1/agents/{agent_id}", headers=live.master)
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The live check of peers over A2A.")
    parser.add_argument("--env-file", type=Path, default=ENV)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    found = live_settings(args.env_file, "peers")
    sys.exit(asyncio.run(run(found, args.host)))
