"""The action executor and folders: those an agent makes, a message
moved once, and a folder the owner deleted or renamed."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import get_args

import httpx
import pytest

from benethos_mailbox_agents.contract import Action, ActionRequest
from benethos_mailbox_agents.errors import MessageGoneError
from benethos_mailbox_agents.records import FolderRef
from benethos_mailbox_agents.runtime.actions import STAGE_ALLOWS, Executor, Outcome
from benethos_mailbox_agents.settings import Stage

from ..agents_fake import ACCOUNT
from ..agents_helpers import Wired, settings
from .actions_helpers import ADD, MOVE, PATH, REF, Every, executor, make, maker

# -- folders an agent makes -----------------------------------------------------


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


@pytest.mark.parametrize("stage", ["shadow", "suggest"])
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


@pytest.mark.parametrize("stage", ["shadow", "suggest"])
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
