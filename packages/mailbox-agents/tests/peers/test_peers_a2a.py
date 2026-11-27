"""The entrance for peers over A2A: the token on every request, the agent
card, and the skill classify in the protocols 1.0 and 0.3, held to what
the classifier answers: docs/mailbox-agents/concept/a2a.md."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from benethos_mailbox_agents.peers import Card, app
from benethos_mailbox_agents.records import Classified, MessageRef, NotClassified

TOKEN = "peer-token-value"  # pragma: allowlist secret
CARD = Card(
    name="categorization/bookkeeping", version="3", url="http://agents.example.test/"
)
ASKED = {"account_id": "acc1", "message_id": "m1"}
# Without it, a request counts as one of the protocol 0.3.
V1 = {"A2A-Version": "1.0"}


class Answers:
    """A classifier that answers what the test says, and notes each ask."""

    def __init__(self, answer: Classified | NotClassified) -> None:
        self.answer = answer
        self.asked: list[MessageRef] = []

    async def __call__(self, ref: MessageRef) -> Classified | NotClassified:
        self.asked.append(ref)
        return self.answer


CLASSIFIED = Classified(
    agent="categorization/bookkeeping",
    version="v1-list-0123456789ab",
    label="Invoice",
    source="model",
    fields={"partner": "Telco"},
    found={"label": True, "partner": True},
)


def client(answers: Answers, token: str | None = TOKEN) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(answers, CARD, TOKEN)),
        base_url="http://agents.example.test",
        headers=headers,
    )


def v1(data: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "q1",
                "role": "ROLE_USER",
                "parts": [{"data": data}],
            }
        },
    }


def v03(data: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "q2",
                "role": "user",
                "kind": "message",
                "parts": [{"kind": "data", "data": data}],
            }
        },
    }


async def test_the_card_names_the_agent_its_skill_and_the_token() -> None:
    async with client(Answers(CLASSIFIED)) as peer:
        card = (await peer.get("/.well-known/agent-card.json")).json()

    assert card["name"] == "categorization/bookkeeping"
    assert card["supportedInterfaces"][0]["url"] == "http://agents.example.test/"
    assert [s["id"] for s in card["skills"]] == ["classify"]
    scheme = card["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]
    assert scheme["scheme"] == "Bearer"


@pytest.mark.parametrize("token", [None, "another-token", TOKEN + "x"])
async def test_without_the_token_nothing_is_answered(token: str | None) -> None:
    answers = Answers(CLASSIFIED)
    async with client(answers, token) as peer:
        card = await peer.get("/.well-known/agent-card.json")
        sent = await peer.post("/", json=v1(ASKED), headers=V1)

    assert card.status_code == sent.status_code == 401
    assert sent.headers["WWW-Authenticate"] == "Bearer"
    assert answers.asked == []


async def test_a_peer_is_told_the_categories_in_protocol_1_0() -> None:
    answers = Answers(CLASSIFIED)
    async with client(answers) as peer:
        sent = await peer.post("/", json=v1(ASKED), headers=V1)

    parts = sent.json()["result"]["message"]["parts"]
    assert parts == [{"data": CLASSIFIED.model_dump(mode="json")}]
    assert answers.asked == [MessageRef(account_id="acc1", message_id="m1")]


async def test_a_peer_of_protocol_0_3_is_told_the_same() -> None:
    async with client(Answers(CLASSIFIED)) as peer:
        sent = await peer.post("/", json=v03(ASKED))

    result = sent.json()["result"]
    assert result["kind"] == "message"
    assert result["parts"] == [
        {"kind": "data", "data": CLASSIFIED.model_dump(mode="json")}
    ]


async def test_a_message_not_classified_is_told_why() -> None:
    gone = NotClassified(agent="categorization/bookkeeping", reason="message_gone")
    async with client(Answers(gone)) as peer:
        sent = await peer.post("/", json=v1(ASKED), headers=V1)

    data = sent.json()["result"]["message"]["parts"][0]["data"]
    assert data == {"agent": "categorization/bookkeeping", "reason": "message_gone"}


@pytest.mark.parametrize(
    "data",
    [
        {"account_id": "acc1"},
        {"account_id": "acc1", "message_id": "m1", "subject": "x"},
        {"account_id": "", "message_id": "m1"},
        {"account_id": "acc1", "message_id": 7},
        {"account_id": "acc1", "message_id": "m" * 2000},
        {"account_id": "..", "message_id": "x"},
        {"account_id": "acc1", "message_id": "."},
        {"account_id": "acc1", "message_id": "a/b"},
        {"account_id": "acc1", "message_id": "a\\b"},
        {"account_id": "acc\n1", "message_id": "m1"},
    ],
)
async def test_anything_but_the_two_ids_is_refused_unasked(data: Any) -> None:
    answers = Answers(CLASSIFIED)
    async with client(answers) as peer:
        sent = await peer.post("/", json=v1(data), headers=V1)

    answer = sent.json()["result"]["message"]["parts"][0]["data"]
    assert answer == {"error": "one data part with account_id and message_id"}
    assert answers.asked == []
