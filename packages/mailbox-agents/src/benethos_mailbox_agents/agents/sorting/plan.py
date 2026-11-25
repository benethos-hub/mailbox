"""The chain at work on one message: its dimensions in order, then what
follows from the categories found.

Each dimension runs when its ``when`` holds, its recognizers without a
model first. The decision holds the category of the first dimension as
its label and those of the others as fields, each with its evidence, so
the check of the runtime drops a field whose quote it does not find and
refuses a label whose quote it does not find. The details of the first
dimension stand under their own keys, those of the others under
``<dimension>.<key>``.

What follows is put together from the categories that stand after the
check: the keywords and other actions of ``then`` first, then at most one
move, and with the move the agent's own keyword. Of several moves the one
of the highest ``priority`` wins, at a tie the earlier dimension's. When
it is held, no other takes its place. A ``move_below`` goes below the
winner's folder, or below the folder of the owner the message lies in
when no move wins (decided 2026-11-25). See
docs/mailbox-agents/concept/agent-sorting.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...contract import Action, ActionRequest, Context
from ...records import LABEL, Decision, Evidence, MailMessage
from .actions import ACTIONS, ChainAction, Move, MoveBelow, Placed, held_by_stage
from .dimensions import Category, Chain, Dimension, Step
from .groups import NONE
from .recognizers import RECOGNIZERS, Choice

__all__ = [
    "BY_CODE",
    "DISPLACED",
    "Found",
    "classify",
    "classify_rules",
    "found_in",
    "key",
    "requests_for",
    "to_decision",
]

# The detail that names the dimensions whose move lost to another's
# priority.
DISPLACED = "moves.displaced"

# The matches that are code: a category so found was not the model's
# choice.
BY_CODE = frozenset({"group", "none", "ambiguous", "keyword"})


def key(index: int, dimension: Dimension, name: str) -> str:
    """The key of a detail of a dimension: its own for the first, under
    the dimension's name for the others."""
    return name if index == 0 else f"{dimension.name}.{name}"


def _runs(dimension: Dimension, chosen: dict[str, str]) -> bool:
    """Whether ``when`` holds for the categories ``chosen`` so far."""
    return all(chosen.get(name) in allowed for name, allowed in dimension.when.items())


def classify_rules(dimension: Dimension, message: MailMessage) -> Choice:
    """The answer of the recognizers without a model: the first that
    settles it, else the first that answered."""
    first: Choice | None = None
    for recognizer in RECOGNIZERS.values():
        if recognizer.asks_model(dimension) or not recognizer.applies(dimension):
            continue
        found = recognizer.baseline(dimension, message)
        if found is None:
            continue
        if found.settled:
            return found
        first = first or found
    return first or Choice(NONE, {"match": "none"}, settled=False)


async def classify(
    dimension: Dimension, message: MailMessage, context: Context
) -> Choice:
    """The answer by rules where they settle it, else by the recognizers
    that ask the model, in their order, until one names a category."""
    found = classify_rules(dimension, message)
    if found.category != NONE:
        return found
    for recognizer in RECOGNIZERS.values():
        if not (recognizer.applies(dimension) and recognizer.asks_model(dimension)):
            continue
        said = await recognizer.decide(dimension, message, context)
        if said is None:
            continue
        found = said
        if said.category != NONE:
            break
    return found


def to_decision(chain: Chain, choices: list[Choice | None]) -> Decision:
    """The decision of the chain from the answer of each dimension, None
    for one that did not run."""
    source = "model" if any(c is not None and c.by_model for c in choices) else None
    fields: dict[str, str] = {}
    evidence: list[Evidence] = []
    details: dict[str, str] = {}
    label = NONE
    for index, (dimension, choice) in enumerate(
        zip(chain.dimensions, choices, strict=True)
    ):
        if choice is None:
            continue
        name = LABEL if index == 0 else dimension.name
        if index == 0:
            label = choice.category
        else:
            fields[name] = choice.category
        details.update({key(index, dimension, k): v for k, v in choice.details.items()})
        if source is not None:
            # A quote of the model is looked up by the check. Code found the
            # rest, or the model said none: no quote, found from the start.
            checked = choice.by_model and choice.quote is not None
            evidence.append(
                Evidence(
                    field=name,
                    value=choice.category,
                    quote=choice.quote or "",
                    found=None if checked else True,
                )
            )
    found = Decision(
        label=label,
        source="model" if source else "baseline",
        fields=fields,
        evidence=tuple(evidence),
        details=details,
    )
    displaced = _displaced(chain, found)
    if displaced:
        details[DISPLACED] = ",".join(displaced)
        found = found.model_copy(update={"details": details})
    return found


@dataclass(frozen=True)
class Found:
    """A category that stands after the check, with its dimension and
    whether the model chose it."""

    index: int
    dimension: Dimension
    category: Category
    by_model: bool


def found_in(
    chain: Chain, decision: Decision, message: MailMessage | None = None
) -> list[Found]:
    """The categories of ``decision`` that stand, as the list says now: a
    category the sender rules chose is looked up again by the sender, so a
    rule added since reaches older mail, one the model chose by its name. A
    dimension whose ``when`` no longer holds, or whose field the check
    dropped, has none."""
    chosen: dict[str, str] = {}
    found: list[Found] = []
    for index, dimension in enumerate(chain.dimensions):
        name = decision.label if index == 0 else decision.fields.get(dimension.name)
        if name is None or not _runs(dimension, chosen):
            continue
        chosen[dimension.name] = name
        match = decision.details.get(key(index, dimension, "match"), "")
        category: Category | None
        if match == "group" and message is not None:
            address = message.sender.email if message.sender else None
            matched = dimension.match(address)
            category = matched.group if matched is not None else None
        else:
            category = dimension.named(name)
        if category is not None:
            chosen[dimension.name] = category.name
            found.append(Found(index, dimension, category, match not in BY_CODE))
    return found


def _displaced(chain: Chain, decision: Decision) -> list[str]:
    """The dimensions whose move lost to the priority of another."""
    moves = [f for f in found_in(chain, decision) if f.category.target is not None]
    if len(moves) < 2:
        return []
    winner = _winner(moves)
    return [f.dimension.name for f in moves if f is not winner]


def _winner(moves: list[Found]) -> Found:
    """The move of the highest priority, at a tie the earlier dimension's."""
    return max(moves, key=lambda f: (f.category.priority, -f.index))


def _held(found: Found, step: Step, action: ChainAction) -> bool:
    """Whether an entry is held: its category is held, the model chose a
    category whose action needs the owner's word, or its stage is below the
    one the action needs."""
    if found.category.hold:
        return True
    if found.by_model and not action.by_model and found.category.by_topic != "act":
        return True
    return any(held_by_stage(step.stage, p) for p in action.primitives)


def _why(found: Found, held: bool) -> str:
    """A code, never a category's name: a name is the owner's free text
    and often names a person, which no log line may (decided 2026-11-18)."""
    if held:
        return "held"
    return "topic" if found.by_model else "group"


def _path(
    winner: Found | None, below: Found | None, placed: Placed
) -> tuple[str, Found | None] | None:
    """The folder the message goes to and the move that leads there, None
    when only a move_below does, or None when it goes nowhere. Mail in the inbox goes to
    the winner's folder, with the move_below below it. Mail elsewhere lies
    where the owner or a rule of the mail server put it: it is not moved
    out, only below the folder of the owner it lies in, and only by a
    move_below. Mail in the folder already stays there, as when a move
    went through and what follows it did not."""
    lies = [folder.path for folder in placed.folders]
    under = below.category.below if below is not None else None
    if winner is not None:
        target = winner.category.target or ""
        path = f"{target}/{under}" if under else target
        if placed.in_inbox or lies == [path]:
            return path, winner
    own = placed.own_folder
    if own is None or under is None:
        return None
    if own == under or own.endswith(f"/{under}"):
        return own, None
    return f"{own}/{under}", None


def requests_for(
    found: list[Found], placed: Placed, own_keyword: str
) -> list[ActionRequest]:
    """What the categories ``found`` ask for, in the order the executor
    takes it: the other actions first, as a move held or refused holds or
    stops what follows it, then the folders and the move, then the own
    keyword, which says the message was moved."""
    requests: list[ActionRequest] = []
    for item in found:
        for step in item.category.then:
            action = ACTIONS[step.action]
            if isinstance(action, (Move, MoveBelow)):
                continue
            params = action.params.model_validate(step.params)
            held = _held(item, step, action)
            requests += action.requests(params, placed, held=held, why="keyword")
    moves = [f for f in found if f.category.target is not None]
    belows = [f for f in found if f.category.below is not None]
    winner = _winner(moves) if moves else None
    below = _winner(belows) if belows else None
    found_path = _path(winner, below, placed)
    if found_path is None:
        return requests
    path, winner = found_path
    held = False
    for part, entry in ((winner, Move.name), (below, MoveBelow.name)):
        if part is not None:
            step = part.category.steps(entry)[0]
            held = held or _held(part, step, ACTIONS[entry])
    lead = winner if winner is not None else below
    if lead is None:  # never: one of them gave the path
        return requests
    move = ACTIONS[Move.name]
    params = move.params.model_validate({"target": path})
    moving = move.requests(params, placed, held=held, why=_why(lead, held))
    if winner is None:
        # Below the folder it lies in: that one and those above it are
        # there, only the folders of the move_below are made.
        own = placed.own_folder or ""
        moving = [
            r
            for r in moving
            if r.action is not Action.CREATE_FOLDER
            or (r.folder or "").startswith(f"{own}/")
        ]
    requests += moving
    # The keyword says the message was moved, so it is asked for after the
    # move. The executor takes nothing after a refused move, and records
    # only what follows a move recorded only: the keyword never stands
    # without the move.
    requests.append(
        ActionRequest(Action.ADD_KEYWORD, placed.ref, keyword=own_keyword, why="sorted")
    )
    return requests
