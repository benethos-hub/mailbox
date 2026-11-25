"""The action executor: declared actions only, the stage, what was before."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from benethos_mailbox_agents.contract import Action, ActionRequest
from benethos_mailbox_agents.errors import MailboxUnavailableError, MessageGoneError
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.runtime.actions import Executor, Outcome

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Echo, Wired, settings, wired
from .actions_helpers import ADD, MOVE, PATH, REF, REMOVE, executor, make, maker


async def test_full_takes_every_declared_action(actions_world: Wired) -> None:
    await executor(actions_world)([ADD, MOVE])

    assert actions_world.service.writes() == [
        (PATH, {"add_keywords": ["echo"]}),
        (PATH, {"folder_ids": ["inv-hosting"]}),
    ]
    keyword, move = actions_world.store.actions(REF)
    assert (keyword.argument, keyword.before, keyword.executed) == (
        "echo",
        {"keywords": ["$seen"]},
        True,
    )
    assert (move.argument, move.before, move.stage) == (
        "Invoices/Hosting",
        {"folders": ["inbox"]},
        "full",
    )


async def test_shadow_records_and_changes_nothing(actions_world: Wired) -> None:
    await executor(actions_world, "shadow")([ADD, MOVE])

    assert actions_world.service.writes() == []
    assert [(a.action, a.executed) for a in actions_world.store.actions(REF)] == [
        ("add_keyword", False),
        ("move_to_folder", False),
    ]


async def test_keyword_sets_the_keyword_and_moves_nothing(actions_world: Wired) -> None:
    await executor(actions_world, "keyword")([ADD, MOVE])

    assert actions_world.service.writes() == [(PATH, {"add_keywords": ["echo"]})]
    assert [a.executed for a in actions_world.store.actions(REF)] == [True, False]


async def test_an_action_already_done_is_not_taken_again(actions_world: Wired) -> None:
    run = executor(actions_world)
    await run([ADD, MOVE])
    await run([ADD, MOVE])

    assert len(actions_world.service.writes()) == 2
    assert len(actions_world.store.actions(REF)) == 2


async def test_an_action_recorded_before_is_not_recorded_again(
    actions_world: Wired, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    asked = [make("Providers"), make("Providers/CloudHost"), ADD]

    for _ in range(3):
        assert await maker(actions_world, "shadow")(asked) == [Outcome.RECORDED] * 3

    assert actions_world.service.writes() == []
    assert [(a.action, a.argument) for a in actions_world.store.actions(REF)] == [
        ("create_folder", "Providers"),
        ("create_folder", "Providers/CloudHost"),
        ("add_keyword", "echo"),
    ]
    lines = [r.getMessage() for r in caplog.records if ".actions." in r.name]
    assert len(lines) == 3


async def test_an_action_recorded_in_another_stage_is_recorded_again(
    actions_world: Wired,
) -> None:
    await executor(actions_world, "shadow")([MOVE])
    await executor(actions_world, "keyword")([MOVE])

    assert [a.stage for a in actions_world.store.actions(REF)] == ["shadow", "keyword"]


async def test_removing_a_keyword_that_is_not_there_does_nothing(
    actions_world: Wired,
) -> None:
    assert await executor(actions_world)([REMOVE]) == [Outcome.PRESENT]

    await executor(actions_world)([ADD])
    assert await executor(actions_world)([REMOVE]) == [Outcome.DONE]
    assert actions_world.service.writes()[-1] == (PATH, {"remove_keywords": ["echo"]})


@pytest.mark.parametrize(
    "request_",
    [
        ActionRequest(Action.REMOVE_KEYWORD, REF, keyword="echo"),
        ActionRequest(Action.ADD_KEYWORD, REF, keyword="someone-elses"),
        ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Missing"),
        ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Trash"),
        ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Trash/Sub"),
        ActionRequest(Action.MOVE_TO_FOLDER, REF, folder=None),
        ActionRequest(
            Action.ADD_KEYWORD,
            MessageRef(account_id=ACCOUNT, message_id="gone"),
            keyword="echo",
        ),
    ],
    ids=[
        "undeclared",
        "foreign-keyword",
        "missing-folder",
        "trash",
        "below-trash",
        "no-folder",
        "gone",
    ],
)
async def test_a_refused_action_is_neither_taken_nor_recorded(
    actions_world: Wired, request_: ActionRequest
) -> None:
    class Narrow(Echo):
        actions = frozenset({Action.ADD_KEYWORD, Action.MOVE_TO_FOLDER})

    run = Executor(
        agent=Narrow(settings(stage="full")),
        store=actions_world.store,
        mailbox=actions_world.mailbox,
        now=actions_world.clock,
    )

    if request_.ref.message_id == "gone":
        with pytest.raises(MessageGoneError):
            await run([request_])
    else:
        assert await run([request_]) == [Outcome.REFUSED]
    assert actions_world.service.writes() == []
    assert actions_world.store.actions() == []


@pytest.mark.parametrize("folder", ["trash", "junk", "trash-sub"])
@pytest.mark.parametrize("request_", [ADD, MOVE], ids=["keyword", "move"])
async def test_a_message_in_the_trash_or_junk_is_left_alone(
    tmp_path: Path, folder: str, request_: ActionRequest
) -> None:
    async with wired(tmp_path) as found:
        found.service.add(wire_message("m1", folder_ids=[folder]))

        assert await executor(found)([request_]) == [Outcome.DISCARDED]
        assert found.service.writes() == []
        assert found.store.actions() == []


async def test_an_account_the_agent_does_not_work_on_is_refused(
    actions_world: Wired,
) -> None:
    assert await executor(actions_world, accounts=["other"])([ADD]) == [Outcome.REFUSED]
    assert actions_world.service.writes() == []


async def test_what_was_before_is_recorded_before_the_action(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(action_id: int) -> None:
        raise RuntimeError("the process ends here")

    monkeypatch.setattr(actions_world.store, "mark_action_executed", crash)

    with pytest.raises(RuntimeError):
        await executor(actions_world)([MOVE])

    assert actions_world.service.writes() == [(PATH, {"folder_ids": ["inv-hosting"]})]
    (move,) = actions_world.store.actions(REF)
    assert (move.action, move.before) == ("move_to_folder", {"folders": ["inbox"]})


async def test_a_write_the_service_refuses_is_not_recorded(
    actions_world: Wired,
) -> None:
    actions_world.service.write_refusal = (422, "keyword_refused")

    assert await executor(actions_world)([ADD]) == [Outcome.REFUSED]
    assert actions_world.store.actions() == []


async def test_the_log_line_names_why(
    actions_world: Wired, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")
    request = ActionRequest(Action.ADD_KEYWORD, REF, keyword="echo", why="due")

    await executor(actions_world)([request])
    await executor(actions_world)([MOVE])

    lines = [r.getMessage() for r in caplog.records if ".actions." in r.name]
    assert lines[0].endswith("carried out add_keyword on message m1 in stage full: due")
    assert lines[1].endswith("in stage full")


async def test_a_service_that_is_away_is_raised(actions_world: Wired) -> None:
    actions_world.service.down = True

    with pytest.raises(MailboxUnavailableError):
        await executor(actions_world)([ADD])


def taken_then_away(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch, *, down: bool = False
) -> None:
    """The service takes each write and then answers 503, and with
    ``down`` answers 503 to everything after."""
    for name in ("_update", "_create_folder"):
        write = getattr(actions_world.service, name)

        def away(
            request: httpx.Request,
            parts: list[str],
            write: Callable[[httpx.Request, list[str]], httpx.Response] = write,
        ) -> httpx.Response:
            write(request, parts)
            actions_world.service.down = down
            return httpx.Response(503, json={"error": {"code": "unavailable"}})

        monkeypatch.setattr(actions_world.service, name, away)


@pytest.mark.parametrize(
    "request_",
    [MOVE, ADD, ActionRequest(Action.CREATE_FOLDER, REF, folder="Providers")],
    ids=["move", "keyword", "folder"],
)
async def test_an_action_taken_while_the_answer_failed_counts_as_taken(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch, request_: ActionRequest
) -> None:
    taken_then_away(actions_world, monkeypatch)

    with pytest.raises(MailboxUnavailableError):
        await maker(actions_world)([request_])

    (taken,) = actions_world.store.actions(REF)
    assert (taken.action, taken.executed) == (request_.action.value, True)


async def test_an_action_the_service_cannot_tell_of_stays_not_taken(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    taken_then_away(actions_world, monkeypatch, down=True)

    with pytest.raises(MailboxUnavailableError):
        await executor(actions_world)([MOVE])

    (move,) = actions_world.store.actions(REF)
    assert (move.action, move.executed) == ("move_to_folder", False)


async def test_a_move_not_taken_while_the_service_was_away_is_dropped(
    actions_world: Wired,
) -> None:
    actions_world.service.write_refusal = (503, "unavailable")

    with pytest.raises(MailboxUnavailableError):
        await executor(actions_world)([MOVE])

    assert actions_world.store.actions() == []


class Listing(Echo):
    """An agent whose configuration names a keyword beside its own."""

    actions = frozenset({Action.ADD_KEYWORD, Action.REMOVE_KEYWORD})

    def keywords(self) -> frozenset[str]:
        return frozenset({self.keyword, "agent-listed"})


@pytest.mark.parametrize(
    ("keyword", "outcome", "written"),
    [
        ("agent-listed", Outcome.DONE, [(PATH, {"add_keywords": ["agent-listed"]})]),
        ("echo", Outcome.DONE, [(PATH, {"add_keywords": ["echo"]})]),
        ("agent-other", Outcome.REFUSED, []),
    ],
)
async def test_a_keyword_the_agent_names_is_set_and_no_other(
    actions_world: Wired, keyword: str, outcome: Outcome, written: list[object]
) -> None:
    run = Executor(
        agent=Listing(settings(stage="full")),
        store=actions_world.store,
        mailbox=actions_world.mailbox,
        now=actions_world.clock,
    )
    request = ActionRequest(Action.ADD_KEYWORD, REF, keyword=keyword)

    assert await run([request]) == [outcome]
    assert actions_world.service.writes() == written
