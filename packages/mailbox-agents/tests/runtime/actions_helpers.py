"""What the tests of the action executor share: the message, its
requests, an agent that declares every action, and an executor for it."""

from __future__ import annotations

from collections.abc import Mapping

from benethos_mailbox_agents.contract import Action, ActionRequest
from benethos_mailbox_agents.records import FolderRef, MessageRef
from benethos_mailbox_agents.runtime.actions import Executor

from ..agents_fake import ACCOUNT
from ..agents_helpers import Echo, Wired, settings

REF = MessageRef(account_id=ACCOUNT, message_id="m1")


PATH = f"/v1/accounts/{ACCOUNT}/messages/m1"


ADD = ActionRequest(Action.ADD_KEYWORD, REF, keyword="echo")


REMOVE = ActionRequest(Action.REMOVE_KEYWORD, REF, keyword="echo")


MOVE = ActionRequest(Action.MOVE_TO_FOLDER, REF, folder="Invoices/Hosting")


class Every(Echo):
    actions = frozenset(Action)


def executor(actions_world: Wired, stage: str = "full", **values: object) -> Executor:
    return Executor(
        agent=Every(settings(stage=stage, **values)),
        store=actions_world.store,
        mailbox=actions_world.mailbox,
        now=actions_world.clock,
    )


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
