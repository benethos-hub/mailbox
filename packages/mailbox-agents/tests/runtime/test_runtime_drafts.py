"""The executor and a forward drafted: only to the agent's recipients,
once per message, within the drafts of a day, never sent."""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from benethos_mailbox_agents.contract import Action, ActionRequest, Limits
from benethos_mailbox_agents.errors import MailboxUnavailableError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.actions import Executor, Outcome

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Wired, settings
from .actions_helpers import REF, Every

TO = ("partner@example.org",)


class Forwarder(Every):
    limits: ClassVar[Limits] = Limits(drafts_per_day=20)

    def recipients(self) -> frozenset[str]:
        return frozenset({"partner@example.org", "desk@example.org"})


def forward(ref: MessageRef = REF, *to: str, form: str = "inline") -> ActionRequest:
    return ActionRequest(
        Action.DRAFT_FORWARD,
        ref,
        recipients=to or TO,
        forward_as=form,
        why="rule",
    )


def executor(world: Wired, stage: str = "suggest") -> Executor:
    return Executor(
        agent=Forwarder(settings(stage=stage)),
        store=world.store,
        mailbox=world.mailbox,
        now=world.clock,
    )


def drafted(world: Wired) -> list[dict[str, object]]:
    return [
        json.loads(r.content)
        for r in world.service.requests
        if r.method == "POST" and r.url.path.endswith("/drafts")
    ]


async def test_shadow_records_the_forward_and_drafts_none(actions_world: Wired) -> None:
    assert await executor(actions_world, "shadow")([forward()]) == [Outcome.RECORDED]

    assert drafted(actions_world) == []
    [row] = actions_world.store.actions(REF)
    assert (row.action, row.argument, row.before, row.executed) == (
        "draft_forward",
        "inline:partner@example.org",
        {},
        False,
    )


@pytest.mark.parametrize("stage", ["suggest", "full"])
async def test_suggest_and_full_draft_it(actions_world: Wired, stage: str) -> None:
    request = forward(REF, "Partner@example.org", "desk@example.org", form="attachment")

    assert await executor(actions_world, stage)([request]) == [Outcome.DONE]

    [body] = drafted(actions_world)
    assert body["reference"] == {
        "message_id": "m1",
        "action": "forward",
        "forward_as": "attachment",
    }
    [row] = actions_world.store.actions(REF)
    assert row.argument == "attachment:desk@example.org,partner@example.org"
    assert row.executed
    assert actions_world.service.writes() == []


@pytest.mark.parametrize(
    "request_",
    [
        forward(REF, "other@example.org"),
        forward(REF, "partner@example.org", "other@example.org"),
        ActionRequest(Action.DRAFT_FORWARD, REF, forward_as="inline"),
        forward(form="quoted"),
    ],
    ids=["stranger", "one-stranger", "nobody", "form"],
)
async def test_a_forward_beyond_its_terms_is_refused(
    actions_world: Wired, request_: ActionRequest
) -> None:
    assert await executor(actions_world)([request_]) == [Outcome.REFUSED]

    assert drafted(actions_world) == []
    assert actions_world.store.actions() == []


async def test_a_message_is_forwarded_once(actions_world: Wired) -> None:
    run = executor(actions_world)

    assert await run([forward()]) == [Outcome.DONE]
    assert await run([forward()]) == [Outcome.PRESENT]
    assert len(drafted(actions_world)) == 1


async def test_the_drafts_of_a_day_are_limited(actions_world: Wired) -> None:
    refs = [MessageRef(account_id=ACCOUNT, message_id=f"n{i}") for i in range(22)]
    for ref in refs:
        actions_world.service.add(wire_message(ref.message_id), change=None)
    run = executor(actions_world)

    outcomes = [(await run([forward(ref)]))[0] for ref in refs[:21]]
    assert outcomes == [Outcome.DONE] * 20 + [Outcome.REFUSED]

    actions_world.clock.advance(days=1)
    assert await run([forward(refs[21])]) == [Outcome.DONE]
    assert len(drafted(actions_world)) == 21


@pytest.mark.parametrize("folder", ["sent", "drafts"])
async def test_no_forward_of_the_owners_own_mail(
    actions_world: Wired, folder: str
) -> None:
    ref = MessageRef(account_id=ACCOUNT, message_id="own")
    actions_world.service.add(wire_message("own", folder_ids=[folder]), change=None)

    assert await executor(actions_world)([forward(ref)]) == [Outcome.REFUSED]
    assert drafted(actions_world) == []


async def test_a_draft_whose_answer_did_not_come_counts_once(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = actions_world.mailbox
    made = mailbox.draft_forward

    async def lost(*args: object, **kwargs: object) -> str:
        await made(*args, **kwargs)  # type: ignore[arg-type]
        raise MailboxUnavailableError("the answer did not come")

    monkeypatch.setattr(mailbox, "draft_forward", lost)
    run = executor(actions_world)
    with pytest.raises(MailboxUnavailableError):
        await run([forward()])
    monkeypatch.undo()

    [row] = actions_world.store.actions(REF)
    assert row.executed
    assert await run([forward()]) == [Outcome.PRESENT]
    assert len(drafted(actions_world)) == 1


async def test_a_draft_whose_answer_and_check_were_lost_is_not_made_again(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailbox = actions_world.mailbox
    made = mailbox.draft_forward

    async def lost(*args: object, **kwargs: object) -> str:
        await made(*args, **kwargs)  # type: ignore[arg-type]
        raise MailboxUnavailableError("the answer did not come")

    async def away(*args: object, **kwargs: object) -> bool:
        raise MailboxUnavailableError("the service is away")

    monkeypatch.setattr(mailbox, "draft_forward", lost)
    monkeypatch.setattr(mailbox, "forward_drafted", away)
    run = executor(actions_world)
    with pytest.raises(MailboxUnavailableError):
        await run([forward()])
    monkeypatch.undo()
    [row] = actions_world.store.actions(REF)
    assert not row.executed

    assert await run([forward()]) == [Outcome.PRESENT]

    [row] = actions_world.store.actions(REF)
    assert row.executed
    assert len(drafted(actions_world)) == 1


async def test_no_log_line_names_an_address(
    actions_world: Wired, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    run = executor(actions_world)

    await run([forward()])
    await run([forward(REF, "other@example.org")])
    await executor(actions_world, "shadow")([forward()])

    assert caplog.records
    assert "example.org" not in caplog.text
