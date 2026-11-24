"""The list of ``sorting``: groups of mail, each with its folder.

An entry names a group, the folder its mail goes to, the senders that
belong to it and a topic, one line on the mail that belongs to it, which
the model is given (decided 2026-11-24). A group names senders, a topic or
both. ``by_topic`` says how far a group chosen by its topic goes:
``record`` by default, ``act`` to move as a sender rule does. The same
sender rule may stand in several groups when each of them has a topic: the
model then chooses among them. A sender is written in one of three ways:

- an address, ``service@bank-two.example``: that address alone,
- a pattern with ``*`` before the ``@``, ``*@cloudhost.example`` or
  ``mailbox*@telco.example``: every address the ``*`` fits, of that one
  domain,
- a pattern for the subdomains, ``*@*.shop.example``: every address of
  every subdomain of ``shop.example``, not of ``shop.example`` itself
  (decided 2026-11-18). The domain after ``*.`` has two names at least, so
  ``*@*.example`` is refused as too broad.

A domain alone, ``cloudhost.example``, is refused: ``sorting`` sets no
keyword a domain could mark with, and the message says what to write
instead (decided 2026-11-18). A message about a wrong rule names its group
and its place in the group's list, never the rule, which often names a
person (decided 2026-11-18). Matching ignores case. The most specific rule
wins: an address before a pattern before a pattern for the subdomains. Two
groups whose rules of the same kind both match leave the sender to no
group, so neither is guessed. See docs/mailbox-agents/concept/agent-sorting.md.

The file is JSON. A reader is chosen by the file's suffix, so another
format is one entry in :data:`READERS`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ...errors import ConfigError, describe_invalid

__all__ = [
    "MAX_TOPIC",
    "MAX_TOPICS",
    "NONE",
    "READERS",
    "Group",
    "Groups",
    "Kind",
    "Match",
    "load_groups",
]

# The label of a message whose sender is in no group, or in two alike. No
# group is named so, case aside, as its messages would be counted as none.
NONE = "none"

# An address longer than this matches no rule: 64 characters before the
# @, 255 after it, as much as the mail standards allow. A pattern is
# matched in time linear in the length of the address and the number of
# its *, so the limit only bounds that time.
MAX_ADDRESS = 320

# A topic is one line of at most this many characters, and at most this
# many groups have one: every topic of the groups to choose from goes into
# each call of the model.
MAX_TOPIC = 300
MAX_TOPICS = 50

_NAME = r"[^\s@*]+"
# One name of a domain, and a domain of two names at least, none empty.
_LABEL = r"[^\s@*.]+"
_DOMAIN = rf"{_LABEL}(?:\.{_LABEL})+"
_ADDRESS = re.compile(rf"^{_NAME}@{_DOMAIN}$")
_PATTERN = re.compile(rf"^[^\s@]*\*[^\s@]*@{_DOMAIN}$")
_SUBDOMAINS = re.compile(rf"^[^\s@]+@\*\.({_DOMAIN})$")
_BARE_DOMAIN = re.compile(rf"^@?{_DOMAIN}$")
_TOO_BROAD = re.compile(rf"^[^\s@]+@\*\.{_LABEL}$")


class Kind(IntEnum):
    """How specific a sender rule is, the higher the more."""

    SUBDOMAINS = 1
    PATTERN = 2
    ADDRESS = 3


def _kind(rule: str) -> Kind:
    """The kind of ``rule``, or a ValueError that says what is wrong with it
    without quoting it."""
    if _ADDRESS.match(rule):
        return Kind.ADDRESS
    if _PATTERN.match(rule):
        return Kind.PATTERN
    if _SUBDOMAINS.match(rule):
        return Kind.SUBDOMAINS
    if _BARE_DOMAIN.match(rule):
        raise ValueError(
            "is a domain: write *@ and the domain for its addresses, "
            "or *@*. and the domain for those of its subdomains"
        )
    if _TOO_BROAD.match(rule):
        raise ValueError("is too broad: the domain after *. needs two names at least")
    raise ValueError(
        "is no address and no pattern: a * stands before the @, "
        "or as *. at the start of the domain"
    )


def _place(group: object, number: int) -> str:
    """A sender rule by its group and its place in the group's list, from 1."""
    if isinstance(group, str):
        return f"group {group!r}, sender {number}"
    return f"sender {number}"


def _one_line(text: str) -> bool:
    """Whether ``text`` holds no line break and no control character: it
    stands in one line of the prompt."""
    return not any(
        unicodedata.category(character) in ("Cc", "Zl", "Zp") for character in text
    )


def _matches(rule: str, kind: Kind, address: str) -> bool:
    if kind is Kind.ADDRESS:
        return address == rule
    local, _, domain = rule.rpartition("@")
    found_local, _, found_domain = address.rpartition("@")
    if kind is Kind.SUBDOMAINS:
        parent = domain[2:]  # the domain after "*."
        if not found_domain.endswith("." + parent):
            return False
    elif found_domain != domain:
        return False
    return _glob(local, found_local)


def _glob(pattern: str, text: str) -> bool:
    """Whether ``text`` is ``pattern`` with each * standing for any run of
    characters. Each piece between two * is taken where it first fits,
    which is right for a pattern of * alone and keeps the time linear in
    the length of ``text``."""
    if "*" not in pattern:
        return text == pattern
    first, *middle, last = pattern.split("*")
    end = len(text) - len(last)
    if end < len(first) or not text.startswith(first) or not text.endswith(last):
        return False
    position = len(first)
    for piece in middle:
        found = text.find(piece, position, end)
        if found < 0:
            return False
        position = found + len(piece)
    return True


class Group(BaseModel):
    """One group: its name, its folder, its senders, its topic, how far a
    choice by its topic goes, and whether its moves are held."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    folder: str = Field(min_length=1, max_length=200)
    senders: tuple[str, ...] = ()
    hold: StrictBool = False
    topic: str | None = None
    by_topic: Literal["record", "act"] = "record"

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("a name has no space at its ends")
        if value.casefold() == NONE:
            raise ValueError(
                f"a group is not named {NONE}: that is the label of a message "
                "in no group"
            )
        return value

    @field_validator("folder")
    @classmethod
    def _folder(cls, value: str) -> str:
        parts = value.split("/")
        if any(not p.strip() or p in (".", "..") or p != p.strip() for p in parts):
            raise ValueError("a folder is names between /, none empty, . or ..")
        return value

    @field_validator("senders")
    @classmethod
    def _senders(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        found = tuple(rule.strip().lower() for rule in value)
        for number, rule in enumerate(found, start=1):
            try:
                _kind(rule)
            except ValueError as exc:
                place = _place(info.data.get("name"), number)
                raise ValueError(f"{place} {exc}") from None
        return found

    @field_validator("topic")
    @classmethod
    def _topic(cls, value: str | None, info: ValidationInfo) -> str | None:
        # The message names the group, never the topic: the owner's text.
        if value is None:
            return value
        group = info.data.get("name")
        where = f"group {group!r}: " if isinstance(group, str) else ""
        if not value or value != value.strip():
            raise ValueError(
                f"{where}a topic is not empty and has no space at its ends"
            )
        if len(value) > MAX_TOPIC:
            raise ValueError(f"{where}a topic has at most {MAX_TOPIC} characters")
        if not _one_line(value):
            raise ValueError(f"{where}a topic is one line, without control characters")
        return value

    @model_validator(mode="after")
    def _what_it_names(self) -> Group:
        if not self.senders and self.topic is None:
            raise ValueError(
                f"group {self.name!r}: a group names senders, a topic or both"
            )
        if self.topic is None and "by_topic" in self.model_fields_set:
            raise ValueError(f"group {self.name!r}: by_topic needs a topic")
        if self.topic is not None and not _one_line(self.name):
            # The name stands in one line of the prompt beside its topic.
            raise ValueError(
                f"group {self.name!r}: the name of a group with a topic is one "
                "line, without control characters"
            )
        return self

    @property
    def folders(self) -> tuple[str, ...]:
        """Its folder and every folder above it, the top first: the folders
        the agent may make for it."""
        parts = self.folder.split("/")
        return tuple("/".join(parts[: i + 1]) for i in range(len(parts)))


def _spelt_alike(groups: tuple[Group, ...]) -> None:
    """Raise a ValueError when two groups write a folder, theirs or one
    above it, in another case: the executor refuses a folder whose name
    exists in another case, so the second would never be made. The
    message names the groups, not the folder."""
    spelt: dict[str, tuple[str, str]] = {}
    for group in groups:
        for path in group.folders:
            first = spelt.setdefault(path.casefold(), (path, group.name))
            if first[0] != path:
                raise ValueError(
                    f"group {group.name!r}: a folder differs from one of group "
                    f"{first[1]!r} in case only"
                )


@dataclass(frozen=True)
class Match:
    """The groups whose most specific rules match a sender: one, or more
    when the list names the sender alike in several."""

    groups: tuple[Group, ...]
    kind: Kind

    @property
    def group(self) -> Group | None:
        """The one group, None when several match alike."""
        return self.groups[0] if len(self.groups) == 1 else None


class Groups(BaseModel):
    """The whole list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: tuple[Group, ...] = ()

    @field_validator("groups")
    @classmethod
    def _unique(cls, value: tuple[Group, ...]) -> tuple[Group, ...]:
        for attribute in ("name", "folder"):
            seen: set[str] = set()
            for group in value:
                key = getattr(group, attribute).casefold()
                if key in seen:
                    raise ValueError(f"two groups share the {attribute} {key!r}")
                seen.add(key)
        _spelt_alike(value)
        # A rule belongs to one group, or to several that each have a topic,
        # among which the model chooses.
        owners: dict[str, Group] = {}
        for group in value:
            for number, rule in enumerate(group.senders, start=1):
                first = owners.setdefault(rule, group)
                if first.name != group.name and (
                    first.topic is None or group.topic is None
                ):
                    raise ValueError(
                        f"{_place(group.name, number)} is named by group "
                        f"{first.name!r} as well"
                    )
        if sum(group.topic is not None for group in value) > MAX_TOPICS:
            raise ValueError(f"more than {MAX_TOPICS} groups have a topic")
        return value

    def match(self, address: str | None) -> Match | None:
        """The groups ``address`` belongs to by their most specific rules,
        or None when no rule matches."""
        if not address:
            return None
        found = address.strip().lower()
        if len(found) > MAX_ADDRESS:
            return None
        hits = [
            (group, _kind(rule))
            for group in self.groups
            for rule in group.senders
            if _matches(rule, _kind(rule), found)
        ]
        if not hits:
            return None
        best = max(kind for _, kind in hits)
        top = {group.name: group for group, kind in hits if kind == best}
        return Match(groups=tuple(top.values()), kind=best)

    def may_create(self, path: str) -> bool:
        """Whether ``path`` is the folder of a group or one above it."""
        return any(path in group.folders for group in self.groups)


def _read_json(text: str) -> Any:
    return json.loads(text)


# The readers by suffix. JSON, as the other lists of this project.
READERS: dict[str, Callable[[str], Any]] = {".json": _read_json}


def load_groups(path: Path) -> Groups:
    """The list at ``path``, or a :class:`ConfigError` that says what is
    wrong with it."""
    reader = READERS.get(path.suffix.lower())
    if reader is None:
        raise ConfigError(
            f"the sorting list {path.name} is no {', '.join(sorted(READERS))} file"
        )
    try:
        # utf-8-sig: an editor may start the file with the mark of UTF-8.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        # A ValueError: a file in another encoding than UTF-8.
        raise ConfigError(
            f"the sorting list {path.name} cannot be read ({type(exc).__name__})"
        ) from None
    try:
        return Groups.model_validate(reader(text))
    except ValueError as exc:
        raise ConfigError(
            f"the sorting list {path.name}: {describe_invalid(exc)}"
        ) from None
