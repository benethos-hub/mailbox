"""The action executor: the runtime's lock on what an agent may do.

An agent asks, this module decides. It carries out only an action the
agent declared, a keyword only if it is the agent's own, a folder path
only of names between slashes, a move only into a folder that exists and
is not the trash, junk or spam, nor below them, and makes only a folder
the agent may make, below a folder that exists and not below those three,
nor one whose name exists in another case. A message in one of them, or
in a folder below one, is left alone. What the stage allows is carried
out, the rest is recorded as what would have been done, and so is an
action the agent asks to be held, once per message and stage. Every
action records what was there before, so it can be taken back. An action
whose result is already there is not taken again, and a message the agent
moved once is not moved again, so one the owner moved back stays, and no
folder is made for its move. After a refused move or folder, the rest of
the message's actions are not taken, and after one recorded only, the rest
are recorded only. See docs/mailbox-agents/concept/agent-contract.md,
docs/mailbox-agents/concept/runtime.md and docs/mailbox-agents/concept/safety.md.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from ..contract import Action, ActionRequest, Agent
from ..errors import (
    ActionRefusedError,
    MailboxAgentError,
    MailboxRefusedError,
    MailboxUnavailableError,
    MessageGoneError,
)
from ..logbook import actions, record
from ..records import DISCARD_ROLES, FolderRef, MailMessage, MessageRef
from ..store import Store
from ..telemetry import NO_SPANS, Spans
from .metrics import Metrics
from .writer import Writer

__all__ = [
    "FORBIDDEN_ROLES",
    "STAGE_ALLOWS",
    "Executor",
    "Outcome",
    "in_another_case",
]

# What each stage carries out. The rest is recorded only.
STAGE_ALLOWS: dict[str, frozenset[Action]] = {
    "shadow": frozenset(),
    "keyword": frozenset({Action.ADD_KEYWORD, Action.REMOVE_KEYWORD}),
    "full": frozenset(Action),
}

# Folders no agent moves a message into: a move there is a deletion.
FORBIDDEN_ROLES = DISCARD_ROLES

# The actions after whose refusal the rest of a message's are not taken,
# and after whose recording only the rest are recorded only.
_FOLDER_ACTIONS = frozenset({Action.CREATE_FOLDER, Action.MOVE_TO_FOLDER})


# The names a folder path may not hold between its slashes.
_NO_NAMES = frozenset({"", ".", ".."})


def _well_formed(path: str) -> None:
    """Refuse a folder path that is not names between slashes: one that
    starts or ends with a slash, holds two in a row, or names ``.`` or
    ``..``. The executor holds to it whatever the agent may make."""
    if any(name in _NO_NAMES for name in path.split("/")):
        raise ActionRefusedError("the folder path is not names between slashes")


class Outcome(StrEnum):
    """What became of one action."""

    DONE = "done"  # the stage allows it, it was taken
    PRESENT = "present"  # its result was already there
    RECORDED = "recorded"  # the stage does not allow it, it was recorded only
    REFUSED = "refused"  # the executor or the mailbox service refused it
    # refused as the message lies in the trash, junk or spam, where the
    # owner put it: no failure, and no action of an agent comes there
    DISCARDED = "discarded"
    # a folder for a move not taken, not made, or a move of a message the
    # agent moved once before, where the owner's folder stands
    SKIPPED = "skipped"


class _DiscardedError(Exception):
    """The message lies in the trash, junk or spam, where the owner put
    it: no action of an agent is taken there."""


class _OwnersChoiceError(Exception):
    """The message was moved by the agent once already: a move asked again
    is not taken, the folder it lies in now is the owner's choice."""


def in_another_case(path: str, paths: Iterable[str]) -> bool:
    """Whether one of ``paths`` is ``path`` in another case only. The
    service would make such a folder as a second one (measured
    2026-11-18), so the executor neither makes it nor moves into it, and
    ``status`` names it."""
    return any(p != path and p.casefold() == path.casefold() for p in paths)


@dataclass(frozen=True)
class Plan:
    """One action as planned: the argument to record, what was there
    before, the target to send, and whether it is recorded only, as below
    a folder recorded and not made, whatever the stage."""

    argument: str
    before: dict[str, Any]
    target: str
    record_only: bool = False


class Executor:
    """Carries out the actions of one agent, in its stage."""

    def __init__(
        self,
        *,
        agent: Agent,
        store: Store,
        mailbox: Writer,
        now: Callable[[], datetime],
        metrics: Metrics | None = None,
        spans: Spans = NO_SPANS,
    ) -> None:
        self.metrics = metrics or Metrics(
            agent.name, agent.version, agent.settings.stage, agent.instance or ""
        )
        self.spans = spans
        self.agent = agent
        self.stage = agent.settings.stage
        self._store = store
        self._mailbox = mailbox
        self._now = now
        # The folders of this call recorded as to be made and not made, by
        # account and path: a folder or a move below one is recorded too.
        self._recorded_folders: set[tuple[str, str]] = set()

    async def __call__(self, requests: list[ActionRequest]) -> list[Outcome]:
        """Take the actions of one message in order. Answers what became of
        each, in the order of ``requests``, up to the last one handled.

        After a refused folder or move, those after it are not taken and
        have no outcome: an action asked after a move, such as a keyword
        that says the message was moved, must not stand without it. After
        a folder or move recorded only, by the stage or held, those after
        it are recorded only too, as if held, for the same reason. For a
        message the agent moved before, the folders made for its move are
        skipped: the move will be refused, and an empty folder would stay.
        A message that is gone is logged and raised as MessageGoneError, so
        the caller ends it as gone, whatever was taken before.

        Before a folder or a move, the account's folders are read anew, so
        a folder the owner deleted or renamed since is made again, not
        taken as there."""
        self._recorded_folders = set()
        await self._read_folders(requests)
        moved = {
            request.ref
            for request in requests
            if request.action is Action.MOVE_TO_FOLDER
            and self._moved_before(request.ref)
        }
        outcomes: list[Outcome] = []
        # The messages a folder action was recorded for and not taken.
        recorded: set[MessageRef] = set()
        for request in requests:
            if request.action is Action.CREATE_FOLDER and request.ref in moved:
                outcomes.append(Outcome.SKIPPED)
                continue
            held = request.ref in recorded and not request.held
            # The action by its name and its code, never its folder or
            # keyword: those are the owner's text.
            with self.spans.span(
                "action",
                action=request.action.value,
                reason=request.why,
                stage=self.stage,
                held=held or request.held,
            ) as span:
                outcome = await self._run(
                    replace(request, held=True) if held else request
                )
                span.set("outcome", outcome.value)
            outcomes.append(outcome)
            if request.action in _FOLDER_ACTIONS:
                if outcome in (Outcome.REFUSED, Outcome.DISCARDED, Outcome.SKIPPED):
                    break
                if outcome is Outcome.RECORDED:
                    recorded.add(request.ref)
        return outcomes

    async def _read_folders(self, requests: list[ActionRequest]) -> None:
        """Read the folders of each account anew that a folder or a move
        of ``requests`` is in. A refusal is left to the action that needs
        the folders, which is refused with it."""
        accounts = dict.fromkeys(
            request.ref.account_id
            for request in requests
            if request.action in _FOLDER_ACTIONS
        )
        for account in accounts:
            with suppress(MailboxRefusedError):
                await self._mailbox.folders(account, fresh=True)

    async def _run(self, request: ActionRequest) -> Outcome:
        """Take one action, or record it. Answers what became of it.

        The action is recorded with what was there before, and only then
        taken, so a crash between the two leaves what is needed to take it
        back. One recorded and not taken in this stage before is not
        recorded again: it answers ``RECORDED`` without a row or a log
        line, so the tick still notes its keyword as recorded, not as set.
        A refused action is logged and not recorded, whether the
        executor or the mailbox service refused it, the write itself
        included. A message that is gone is raised after it is logged, and
        so is a mailbox service that is away, to the loop.
        """
        try:
            self._admissible(request)
            message = await self._mailbox.message(request.ref)
            planned = await self._plan(request, message)
        except (ActionRefusedError, MailboxRefusedError) as exc:
            return self._refused(request, exc)
        except (_OwnersChoiceError, _DiscardedError) as exc:
            return self._settled(request, exc)
        if planned is None:
            return Outcome.PRESENT
        executed = (
            request.action in STAGE_ALLOWS[self.stage]
            and not request.held
            and not planned.record_only
        )
        argument, target = planned.argument, planned.target
        if not executed and self._recorded_before(request, argument):
            if request.action is Action.CREATE_FOLDER:
                self._recorded_folders.add((request.ref.account_id, argument))
            return Outcome.RECORDED
        recorded = self._store.add_action(
            request.ref,
            action=request.action.value,
            argument=argument,
            before=planned.before,
            stage=self.stage,
            executed=False,
            now=self._now(),
        )
        if executed:
            try:
                await self._take(request, target)
            except MailboxRefusedError as exc:
                self._store.drop_action(recorded)
                return self._refused(request, await self._folder_gone(request, exc))
            except MailboxUnavailableError:
                await self._settle(request, target, recorded)
                raise
            self._store.mark_action_executed(recorded)
        elif request.action is Action.CREATE_FOLDER:
            self._recorded_folders.add((request.ref.account_id, argument))
        self.metrics.action(request.action.value, executed)
        done = actions.Done if executed else actions.Recorded
        record(
            done(
                agent=self.agent.label,
                message_id=request.ref.message_id,
                action=request.action.value,
                stage=self.stage,
                reason=request.why,
            )
        )
        return Outcome.DONE if executed else Outcome.RECORDED

    async def _folder_gone(
        self, request: ActionRequest, exc: MailboxRefusedError
    ) -> ActionRefusedError | MailboxRefusedError:
        """The refusal of a write, as it counts. The service answers a move
        to a folder deleted or renamed since it was read, and a folder
        made below one, as it answers a message that is gone (measured
        2026-11-18). So after a folder or a move answered so, the message
        is asked for again: when it answers, the folder is gone and the
        action is refused, and the message is not ended as gone."""
        if not isinstance(exc, MessageGoneError):
            return exc
        if request.action not in _FOLDER_ACTIONS:
            return exc
        try:
            await self._mailbox.message(request.ref)
        except MessageGoneError:
            return exc
        return ActionRefusedError("the folder is not there any more")

    def _refused(
        self, request: ActionRequest, exc: ActionRefusedError | MailboxRefusedError
    ) -> Outcome:
        """Log the refusal and count it. Answers ``REFUSED``, and raises the
        error again when the message is not there any more."""
        self._log_refused(request, exc)
        self.metrics.step_failed(exc.code)
        if isinstance(exc, MessageGoneError):
            raise exc
        return Outcome.REFUSED

    def _settled(
        self, request: ActionRequest, exc: _OwnersChoiceError | _DiscardedError
    ) -> Outcome:
        """An action the owner's choice settles, not refused: no failure
        counted. A move asked again of a message moved once is not taken,
        without a warning, as an update that asks for it comes with every
        change. An action on a message in the trash, junk or spam is logged
        as refused, and the caller notes it so it is not asked again."""
        if isinstance(exc, _OwnersChoiceError):
            record(
                actions.Kept(agent=self.agent.label, message_id=request.ref.message_id)
            )
            return Outcome.SKIPPED
        self._log_refused(
            request, ActionRefusedError("the message is in the trash, junk or spam")
        )
        return Outcome.DISCARDED

    def _log_refused(
        self, request: ActionRequest, exc: ActionRefusedError | MailboxRefusedError
    ) -> None:
        record(
            actions.Refused(
                agent=self.agent.label,
                message_id=request.ref.message_id,
                action=request.action.value,
                error=exc,
            )
        )

    def _admissible(self, request: ActionRequest) -> None:
        if request.action not in self.agent.actions:
            raise ActionRefusedError(
                f"{self.agent.name} did not declare {request.action}"
            )
        accounts = self.agent.settings.accounts
        if accounts and request.ref.account_id not in accounts:
            raise ActionRefusedError("the account is not one the agent works on")
        if request.action is Action.MOVE_TO_FOLDER:
            if not request.folder:
                raise ActionRefusedError("a move names no folder")
            _well_formed(request.folder)
        elif request.action is Action.CREATE_FOLDER:
            if not request.folder:
                raise ActionRefusedError("a folder to make has no path")
            _well_formed(request.folder)
        elif not request.keyword or request.keyword not in self.agent.keywords():
            raise ActionRefusedError(
                "an agent sets and takes off its own keywords only"
            )

    async def _plan(self, request: ActionRequest, message: MailMessage) -> Plan | None:
        """What to record and the target, or None when the result is
        already there."""
        account = request.ref.account_id
        if await self._in_forbidden(account, message):
            raise _DiscardedError
        if request.action is Action.MOVE_TO_FOLDER:
            path = request.folder or ""  # never empty, _admissible checked it
            folder = await self._mailbox.folder_at(account, path)
            before = [f.id for f in message.folders]
            # Moved once already and not in the target: the owner's choice
            # stands, also where the target is missing.
            if self._moved_before(request.ref) and (
                folder is None or before != [folder.id]
            ):
                raise _OwnersChoiceError
            if folder is None and (account, path) in self._recorded_folders:
                # Its folder was recorded only, by the stage or held: so is
                # the move, which has no target to send.
                return Plan(path, {"folders": before}, "", record_only=True)
            if folder is None:
                raise ActionRefusedError("the target folder does not exist")
            if await self._forbidden(account, folder):
                raise ActionRefusedError("no agent moves a message there")
            if before == [folder.id]:
                return None
            return Plan(folder.path, {"folders": before}, folder.id)
        if request.action is Action.CREATE_FOLDER:
            return await self._plan_folder(account, request.folder)
        keyword = request.keyword or ""  # never empty, _admissible checked it
        if (request.action is Action.ADD_KEYWORD) == message.has_keyword(keyword):
            return None
        return Plan(keyword, {"keywords": list(message.keywords)}, keyword)

    def _recorded_before(self, request: ActionRequest, argument: str) -> bool:
        """Whether the same action is recorded for the message already, in
        this stage and not taken: then it is not recorded again, so a
        ``backfill`` run again adds no row (decided 2026-11-18)."""
        return any(
            row.action == request.action.value
            and row.argument == argument
            and row.stage == self.stage
            and not row.executed
            for row in self._store.actions(request.ref)
        )

    def _moved_before(self, ref: MessageRef) -> bool:
        """Whether the agent moved the message once already: then the
        owner's choice of folder stands (decided 2026-11-18). A move only
        recorded does not count."""
        return any(
            row.action == Action.MOVE_TO_FOLDER.value and row.executed
            for row in self._store.actions(ref)
        )

    async def _plan_folder(self, account_id: str, path: str | None) -> Plan | None:
        """A folder to make: refused unless the agent may make it, given
        the account's folders by path. None when it exists. Refused when
        its name exists in another case, which the service would make as a
        second folder (measured 2026-11-18), when the folder above it is
        missing, and below the trash, junk or spam. Recorded only when the
        folder above it was recorded only."""
        path = path or ""  # never empty, _admissible checked it
        known = await self._mailbox.folders(account_id)
        if not self.agent.may_create(path, {f.path: f for f in known.values()}):
            raise ActionRefusedError(f"{self.agent.name} may not make that folder")
        if await self._mailbox.folder_at(account_id, path) is not None:
            return None
        # Read again, not doubled: folder_at replaces the cached list when
        # it misses, and only the fresh list answers for another case.
        fresh = await self._mailbox.folders(account_id)
        if in_another_case(path, (f.path for f in fresh.values())):
            raise ActionRefusedError("a folder of that name exists in another case")
        above = path.rpartition("/")[0]
        if above and (account_id, above) in self._recorded_folders:
            return Plan(path, {}, path, record_only=True)
        if above:
            parent = await self._mailbox.folder_at(account_id, above)
            if parent is None:
                raise ActionRefusedError("the folder above it does not exist")
            if await self._forbidden(account_id, parent):
                raise ActionRefusedError("no agent makes a folder there")
        return Plan(path, {}, path)

    async def _in_forbidden(self, account_id: str, message: MailMessage) -> bool:
        """Whether ``message`` lies in the trash, junk or spam, or below one."""
        for folder in message.folders:
            if await self._forbidden(account_id, folder):
                return True
        return False

    async def _forbidden(self, account_id: str, folder: FolderRef) -> bool:
        """Whether ``folder`` is the trash, junk or spam, or lies below one."""
        if folder.role in FORBIDDEN_ROLES:
            return True
        known = await self._mailbox.folders(account_id)
        return any(
            folder.path.startswith(f"{other.path}/")
            for other in known.values()
            if other.role in FORBIDDEN_ROLES
        )

    async def _settle(self, request: ActionRequest, target: str, recorded: int) -> None:
        """After a write whose answer did not come: mark the action taken
        when its result is there, and drop it when not, so a move that
        went through counts as one. When the service cannot tell either,
        the action stays recorded and not taken, with what was before."""
        try:
            reached = await self._reached(request, target)
        except MailboxAgentError:
            return
        if reached:
            self._store.mark_action_executed(recorded)
        else:
            self._store.drop_action(recorded)

    async def _reached(self, request: ActionRequest, target: str) -> bool:
        """Whether the result of the action is there now."""
        if request.action is Action.CREATE_FOLDER:
            found = await self._mailbox.folder_at(request.ref.account_id, target)
            return found is not None
        message = await self._mailbox.message(request.ref)
        if request.action is Action.MOVE_TO_FOLDER:
            return [f.id for f in message.folders] == [target]
        return message.has_keyword(target) == (request.action is Action.ADD_KEYWORD)

    async def _take(self, request: ActionRequest, target: str) -> None:
        if request.action is Action.ADD_KEYWORD:
            await self._mailbox.add_keyword(request.ref, target)
        elif request.action is Action.REMOVE_KEYWORD:
            await self._mailbox.remove_keyword(request.ref, target)
        elif request.action is Action.CREATE_FOLDER:
            await self._mailbox.create_folder(request.ref.account_id, target)
        else:
            await self._mailbox.move(request.ref, target)
