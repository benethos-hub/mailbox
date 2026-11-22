"""The action executor: declared actions only, the stage, what was before."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import get_args

import httpx
import pytest

from benethos_mailbox_agents.contract import Action, ActionRequest
from benethos_mailbox_agents.errors import MailboxUnavailableError, MessageGoneError
from benethos_mailbox_agents.records import FolderRef, MessageRef
from benethos_mailbox_agents.runtime.actions import STAGE_ALLOWS, Executor, Outcome
from benethos_mailbox_agents.settings import Stage

from ..agents_fake import ACCOUNT, wire_message
from ..agents_helpers import Echo, Wired, settings, wired

REF = MessageRef(account_id=ACCOUNT, message_id="m1")
PATH = f"/v1/accounts/{ACCOUNT}/messages/m1"

ADD = ActionRequest(Action.ADD_KEYWORD, REF, keyword="echo")
REMOVE = ActionRequest(Action.REMOVE_KEYWORD, REF, keyword="echo")
MOVE = ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Invoices/Hosting")


@pytest.fixture
async def actions_world(tmp_path: Path) -> AsyncIterator[Wired]:
    async with wired(tmp_path) as found:
        found.service.add(wire_message("m1", keywords=["$seen"]))
        yield found


class Every(Echo):
    actions = frozenset(Action)


def executor(actions_world: Wired, stage: str = "full", **values: object) -> Executor:
    return Executor(
        agent=Every(settings(stage=stage, **values)),
        store=actions_world.store,
        mailbox=actions_world.mailbox,
        now=actions_world.clock,
    )


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


# -- folders an agent makes -----------------------------------------------------

MAY_MAKE = frozenset(
    {
        "Providers",
        "Providers/CloudHost",
        "Trash/New",
        "Junk/New",
        "invoices",
        "Invoices/Hosting",
        "Missing/Below",
    }
)


class Maker(Every):
    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        # The executor hands over the account's folders by path.
        return path in MAY_MAKE and folders["INBOX"].role == "inbox"


def maker(actions_world: Wired, stage: str = "full") -> Executor:
    return Executor(
        agent=Maker(settings(stage=stage)),
        store=actions_world.store,
        mailbox=actions_world.mailbox,
        now=actions_world.clock,
    )


def make(path: str) -> ActionRequest:
    return ActionRequest(Action.CREATE_FOLDER, REF, folder=path, why="group")


async def test_a_folder_the_agent_may_make_is_made_from_the_top(
    actions_world: Wired,
) -> None:
    run = maker(actions_world)

    outcomes = await run([make(p) for p in ("Providers", "Providers/CloudHost")])

    assert outcomes == [Outcome.DONE, Outcome.DONE]
    assert actions_world.service.made() == [
        {"name": "Providers"},
        {"name": "CloudHost", "parent_id": "Providers"},
    ]
    made = actions_world.store.actions(REF)
    assert [(a.action, a.argument, a.before, a.executed) for a in made] == [
        ("create_folder", "Providers", {}, True),
        ("create_folder", "Providers/CloudHost", {}, True),
    ]


@pytest.mark.parametrize(
    "path",
    ["Elsewhere", "Trash/New", "Junk/New", "invoices", "Missing/Below"],
    ids=["not-declared", "below-trash", "below-junk", "other-case", "parent-missing"],
)
async def test_a_folder_is_refused(actions_world: Wired, path: str) -> None:
    assert await maker(actions_world)([make(path)]) == [Outcome.REFUSED]
    assert actions_world.service.made() == []
    assert actions_world.store.actions() == []


class Lenient(Every):
    def may_create(self, path: str, folders: Mapping[str, FolderRef]) -> bool:
        return True


@pytest.mark.parametrize(
    "path", ["A//B", "/A", "A/", "A/..", "Invoices/.", "Invoices/.."]
)
@pytest.mark.parametrize(
    "action", [Action.MOVE_TO_FOLDER, Action.CREATE_FOLDER], ids=["move", "make"]
)
async def test_a_folder_path_out_of_form_is_refused_by_the_executor(
    actions_world: Wired, action: Action, path: str
) -> None:
    """Names between slashes, none empty, ``.`` or ``..``: the executor
    holds to it whatever the agent may make, before it reads the message."""
    run = Executor(
        agent=Lenient(settings(stage="full")),
        store=actions_world.store,
        mailbox=actions_world.mailbox,
        now=actions_world.clock,
    )
    actions_world.service.requests.clear()

    assert await run([ActionRequest(action, REF, folder=path)]) == [Outcome.REFUSED]
    assert ("GET", PATH) not in [
        (r.method, r.url.path) for r in actions_world.service.requests
    ]
    assert actions_world.service.writes() == []
    assert actions_world.service.made() == []
    assert actions_world.store.actions() == []


async def test_a_folder_that_exists_is_not_made_again(actions_world: Wired) -> None:
    assert await maker(actions_world)([make("Invoices/Hosting")]) == [Outcome.PRESENT]
    assert actions_world.service.made() == []


async def test_an_agent_makes_no_folder_unless_it_says_so(actions_world: Wired) -> None:
    assert await executor(actions_world)([make("Providers")]) == [Outcome.REFUSED]
    assert actions_world.service.made() == []


@pytest.mark.parametrize("stage", ["shadow", "keyword"])
async def test_a_folder_is_recorded_only_below_full(
    actions_world: Wired, stage: str
) -> None:
    assert await maker(actions_world, stage)([make("Providers")]) == [Outcome.RECORDED]
    assert actions_world.service.made() == []
    (made,) = actions_world.store.actions(REF)
    assert (made.action, made.argument, made.executed) == (
        "create_folder",
        "Providers",
        False,
    )


async def test_a_move_below_a_held_folder_is_recorded_only(
    actions_world: Wired,
) -> None:
    held = ActionRequest(Action.CREATE_FOLDER, REF, folder="Providers", held=True)
    move = ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Providers")

    await maker(actions_world)([held, move])

    assert actions_world.service.writes() == []
    assert actions_world.service.made() == []
    assert [(a.action, a.executed) for a in actions_world.store.actions(REF)] == [
        ("create_folder", False),
        ("move_to_folder", False),
    ]


async def test_a_folder_below_a_held_folder_is_recorded_only(
    actions_world: Wired,
) -> None:
    held = ActionRequest(Action.CREATE_FOLDER, REF, folder="Providers", held=True)

    await maker(actions_world)([held, make("Providers/CloudHost")])

    assert actions_world.service.made() == []
    assert [(a.argument, a.executed) for a in actions_world.store.actions(REF)] == [
        ("Providers", False),
        ("Providers/CloudHost", False),
    ]


# -- a message is moved once ----------------------------------------------------


async def test_a_message_the_owner_moved_back_is_not_moved_again(
    actions_world: Wired, caplog: pytest.LogCaptureFixture
) -> None:
    """The owner's folder is a settled state, not a refusal: no warning and
    no failure counted, however often an update asks for the move."""
    caplog.set_level("INFO")
    run = executor(actions_world)
    assert await run([MOVE]) == [Outcome.DONE]
    actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] = ["inbox"]

    for _ in range(3):
        assert await run([MOVE, ADD]) == [Outcome.SKIPPED]

    assert actions_world.service.writes() == [(PATH, {"folder_ids": ["inv-hosting"]})]
    assert actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] == ["inbox"]
    names = [r.name.rsplit(".", 1)[-1] for r in caplog.records if ".actions." in r.name]
    assert names == ["done", "kept", "kept", "kept"]
    failures = run.metrics.registry.get_sample_value(
        "mailbox_agents_step_failures_total", {"kind": "action_refused"}
    )
    assert not failures


async def test_no_folder_is_made_for_a_message_moved_before(
    actions_world: Wired,
) -> None:
    run = maker(actions_world)
    await run([MOVE])
    actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] = ["inbox"]

    outcomes = await run([make("Providers"), MOVE])

    assert outcomes == [Outcome.SKIPPED, Outcome.SKIPPED]
    assert actions_world.service.made() == []
    assert [a.action for a in actions_world.store.actions(REF)] == ["move_to_folder"]
    assert actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] == ["inbox"]


async def test_a_move_only_recorded_does_not_count(actions_world: Wired) -> None:
    assert await executor(actions_world, "shadow")([MOVE]) == [Outcome.RECORDED]

    assert await executor(actions_world)([MOVE]) == [Outcome.DONE]


async def test_after_a_refused_move_the_rest_is_not_taken(actions_world: Wired) -> None:
    missing = ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Missing")

    assert await executor(actions_world)([missing, ADD]) == [Outcome.REFUSED]

    assert actions_world.service.writes() == []
    assert actions_world.store.actions() == []


async def test_after_a_refused_folder_the_rest_is_not_taken(
    actions_world: Wired,
) -> None:
    await maker(actions_world)([make("Elsewhere"), MOVE, ADD])

    assert actions_world.service.writes() == []


# -- a folder deleted or renamed by the owner ------------------------------------


async def test_a_folder_deleted_since_it_was_read_is_made_again(
    actions_world: Wired,
) -> None:
    run = maker(actions_world)
    assert await run([make("Providers")]) == [Outcome.DONE]
    actions_world.service.folders[ACCOUNT] = [
        f for f in actions_world.service.folders[ACCOUNT] if f["id"] != "Providers"
    ]
    move = ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Providers")

    assert await run([make("Providers"), move]) == [Outcome.DONE, Outcome.DONE]

    assert actions_world.service.made() == [
        {"name": "Providers"},
        {"name": "Providers"},
    ]
    assert actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] == [
        "Providers"
    ]


async def test_a_move_to_a_folder_gone_meanwhile_is_refused_not_gone(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = actions_world.service._update

    def deleted_first(request: httpx.Request, parts: list[str]) -> httpx.Response:
        # The owner deletes the folder between its listing and the move.
        actions_world.service.folders[ACCOUNT] = [
            f
            for f in actions_world.service.folders[ACCOUNT]
            if f["id"] != "inv-hosting"
        ]
        return update(request, parts)

    monkeypatch.setattr(actions_world.service, "_update", deleted_first)

    assert await executor(actions_world)([MOVE, ADD]) == [Outcome.REFUSED]

    assert actions_world.store.actions() == []
    assert actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] == ["inbox"]


async def test_a_folder_below_one_gone_meanwhile_is_refused_not_gone(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_folder = actions_world.service._create_folder

    def parent_gone(request: httpx.Request, parts: list[str]) -> httpx.Response:
        # The owner deletes the folder above between its listing and the
        # folder made below it, which the service answers as not found.
        if json.loads(request.content).get("parent_id") == "Providers":
            return httpx.Response(
                404, json={"error": {"code": "not_found", "message": "gone"}}
            )
        return make_folder(request, parts)

    monkeypatch.setattr(actions_world.service, "_create_folder", parent_gone)

    outcomes = await maker(actions_world)(
        [make("Providers"), make("Providers/CloudHost")]
    )

    assert outcomes == [Outcome.DONE, Outcome.REFUSED]
    assert [a.argument for a in actions_world.store.actions(REF)] == ["Providers"]


async def test_a_move_of_a_message_gone_meanwhile_is_still_gone(
    actions_world: Wired, monkeypatch: pytest.MonkeyPatch
) -> None:
    update = actions_world.service._update

    def deleted_first(request: httpx.Request, parts: list[str]) -> httpx.Response:
        del actions_world.service.messages[(ACCOUNT, "m1")]
        return update(request, parts)

    monkeypatch.setattr(actions_world.service, "_update", deleted_first)

    with pytest.raises(MessageGoneError):
        await executor(actions_world)([MOVE])
    assert actions_world.store.actions() == []


def test_every_stage_has_a_row() -> None:
    assert set(STAGE_ALLOWS) == set(get_args(Stage))


@pytest.mark.parametrize("stage", ["shadow", "keyword"])
async def test_after_a_move_recorded_only_the_rest_is_recorded_only(
    actions_world: Wired, stage: str
) -> None:
    assert await executor(actions_world, stage)([MOVE, ADD]) == [Outcome.RECORDED] * 2

    assert actions_world.service.writes() == []
    assert [(a.action, a.executed) for a in actions_world.store.actions(REF)] == [
        ("move_to_folder", False),
        ("add_keyword", False),
    ]


async def test_after_a_held_folder_the_rest_is_recorded_only(
    actions_world: Wired,
) -> None:
    held = ActionRequest(Action.CREATE_FOLDER, REF, folder="Providers", held=True)

    outcomes = await maker(actions_world)([held, ADD])

    assert outcomes == [Outcome.RECORDED, Outcome.RECORDED]
    assert actions_world.service.writes() == []


async def test_after_a_move_taken_the_keyword_is_taken(actions_world: Wired) -> None:
    assert await executor(actions_world)([MOVE, ADD]) == [Outcome.DONE, Outcome.DONE]


async def test_a_refused_keyword_does_not_stop_a_move(actions_world: Wired) -> None:
    other = ActionRequest(Action.ADD_KEYWORD, REF, keyword="other")

    await executor(actions_world)([other, MOVE])

    assert actions_world.service.writes() == [(PATH, {"folder_ids": ["inv-hosting"]})]


async def test_a_message_moved_once_is_kept_where_its_target_is_missing(
    actions_world: Wired, caplog: pytest.LogCaptureFixture
) -> None:
    """The owner moved it to a folder below which the agent's target is
    missing: that is the owner's choice as well, not a refusal."""
    caplog.set_level("INFO")
    run = executor(actions_world)
    assert await run([MOVE]) == [Outcome.DONE]
    actions_world.service.messages[(ACCOUNT, "m1")]["folder_ids"] = ["inbox"]
    missing = ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Invoices/Missing")

    for _ in range(3):
        assert await run([missing]) == [Outcome.SKIPPED]

    names = [r.name.rsplit(".", 1)[-1] for r in caplog.records if ".actions." in r.name]
    assert names == ["done", "kept", "kept", "kept"]
    failures = run.metrics.registry.get_sample_value(
        "mailbox_agents_step_failures_total", {"kind": "action_refused"}
    )
    assert not failures
