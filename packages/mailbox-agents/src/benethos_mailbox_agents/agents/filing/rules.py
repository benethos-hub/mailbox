"""The list of ``filing``: which keywords put mail into which folder.

A rule names the keywords a message carries, all of them, and one of two
targets: ``move``, a folder from the top, or ``below``, a folder below
the one the message goes to or lies in. The target of a message is the
``move`` of the first rule with a move that fits, with the ``below`` of
the first rule with a below that fits under it. A message in a folder of
the owner, one without a role, goes only below that folder. The list
waits for the keywords ``on`` names, or without ``on`` for every keyword
of its rules.

A message of a refused list names the place of a rule, never a keyword
or a folder: both are the owner's own text. See
docs/mailbox-agents/concept/agent-filing.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ...contract import KEYWORD_FORM, folder_path, from_top, is_pattern, waits_for
from ...errors import ConfigError, describe_invalid

__all__ = ["On", "Rule", "Rules", "Target", "load_rules"]


class On(BaseModel):
    """The keywords the list waits for, a ``*`` at the end of one for
    every keyword it starts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keywords: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("keywords")
    @classmethod
    def _patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(is_pattern(pattern) for pattern in value):
            raise ValueError(
                "a keyword of on is lower case letters, digits and dashes, "
                "a * at its end for every keyword it starts"
            )
        return value


class Rule(BaseModel):
    """The keywords a message carries, all of them, and where it goes:
    ``move``, a folder from the top, or ``below``, a folder below."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keywords: tuple[str, ...] = Field(min_length=1, max_length=10)
    move: str | None = Field(default=None, min_length=1, max_length=200)
    below: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(KEYWORD_FORM.fullmatch(keyword) for keyword in value):
            raise ValueError("a keyword is lower case letters, digits and dashes")
        return value

    @field_validator("move", "below")
    @classmethod
    def _folder(cls, value: str | None) -> str | None:
        return None if value is None else folder_path(value)

    @model_validator(mode="after")
    def _one_target(self) -> Rule:
        if (self.move is None) == (self.below is None):
            raise ValueError("a rule names move or below, one of them")
        return self

    def fits(self, carried: frozenset[str]) -> bool:
        """Whether a message that carries ``carried``, in lower case,
        carries every keyword of the rule."""
        return all(keyword in carried for keyword in self.keywords)


@dataclass(frozen=True, slots=True)
class Target:
    """Where a message goes, and the places of the rules, from 1, that
    gave its move and its below."""

    path: str
    move: int | None = None
    below: int | None = None

    @property
    def place(self) -> int:
        """The place of the rule that leads: the move's, else the below's."""
        found = self.move if self.move is not None else self.below
        return found or 0


def _under(folder: str, below: str) -> str:
    """``below`` under ``folder``, unless ``folder`` is it already."""
    if folder == below or folder.endswith(f"/{below}"):
        return folder
    return f"{folder}/{below}"


class Rules(BaseModel):
    """The whole list: what it waits for, and its rules in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    on: On | None = None
    rules: tuple[Rule, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _spelt_alike(self) -> Rules:
        """Refuse two folders that differ in case only: the executor
        refuses a folder whose name exists in another case, so the second
        would never be made. The message names the places of the rules."""
        spelt: dict[str, tuple[str, int]] = {}
        for place, rule in enumerate(self.rules, 1):
            for path in self._paths_of(rule):
                first = spelt.setdefault(path.casefold(), (path, place))
                if first[0] != path:
                    raise ValueError(
                        f"rule {place}: a folder differs from one of rule "
                        f"{first[1]} in case only"
                    )
        return self

    def _paths_of(self, rule: Rule) -> list[str]:
        paths = list(from_top(rule.move)) if rule.move else []
        if rule.below:
            paths += from_top(rule.below)
            paths += [_under(m.move, rule.below) for m in self.rules if m.move]
        return paths

    def waits_for(self, keyword: str) -> bool:
        """Whether the list waits for ``keyword``, case aside: one ``on``
        names, or without ``on`` one of its rules."""
        if self.on is not None:
            return waits_for(self.on.keywords, keyword)
        return any(waits_for(rule.keywords, keyword) for rule in self.rules)

    def target(
        self, keywords: tuple[str, ...], *, in_inbox: bool, own_folder: str | None
    ) -> Target | None:
        """Where a message with ``keywords`` goes. From the inbox to the
        ``move`` of the first rule with a move that fits, with the
        ``below`` of the first rule with a below that fits under it. From a
        folder of the owner, ``own_folder``, only below it, unless it is
        that target already: a move that went through while its keyword
        did not, which is then set. Else nowhere."""
        carried = frozenset(keyword.casefold() for keyword in keywords)
        fitting = [(n, r) for n, r in enumerate(self.rules, 1) if r.fits(carried)]
        moved = next(((n, r.move) for n, r in fitting if r.move), None)
        under = next(((n, r.below) for n, r in fitting if r.below), None)
        if moved is not None:
            whole = (
                Target(moved[1], move=moved[0])
                if under is None
                else Target(_under(moved[1], under[1]), move=moved[0], below=under[0])
            )
            if in_inbox or own_folder == whole.path:
                return whole
        if not in_inbox and own_folder is not None and under is not None:
            return Target(_under(own_folder, under[1]), below=under[0])
        return None

    def folders(self) -> frozenset[str]:
        """Every folder a move of the list names, every folder above it,
        and every move with a below under it: the folders the agent may
        make from the top."""
        found: set[str] = set()
        moves = [rule.move for rule in self.rules if rule.move]
        belows = [rule.below for rule in self.rules if rule.below]
        for move in moves:
            found.update(from_top(move))
            for below in belows:
                found.update(from_top(_under(move, below)))
        return frozenset(found)

    def belows(self) -> frozenset[str]:
        """Every folder a below names, with those above it, relative to
        the folder it is made in."""
        found: set[str] = set()
        for rule in self.rules:
            if rule.below:
                found.update(from_top(rule.below))
        return frozenset(found)


def load_rules(path: Path) -> Rules:
    """The list at ``path``, a JSON file, or a :class:`ConfigError` that
    says what is wrong with it: the place of a rule, never its text."""
    try:
        # utf-8-sig: an editor may start the file with the mark of UTF-8.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        # A ValueError: a file in another encoding than UTF-8.
        raise ConfigError(
            f"the filing list {path.name} cannot be read ({type(exc).__name__})"
        ) from None
    try:
        data = json.loads(text)
    except ValueError:
        raise ConfigError(f"the filing list {path.name} is no JSON") from None
    try:
        return Rules.model_validate(data)
    except ValueError as exc:
        raise ConfigError(
            f"the filing list {path.name}: {describe_invalid(exc)}"
        ) from None
