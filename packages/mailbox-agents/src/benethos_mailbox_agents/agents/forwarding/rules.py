"""The list of ``forwarding``: which keywords send a forward of a message,
as a draft, to which addresses.

A rule names the keywords a message carries, all of them, the addresses
the forward goes to, its form, ``inline`` or as an ``attachment``, and
whether the sender check of the message must pass before a draft is made.
The first rule that fits holds. The list waits for the keywords ``on``
names, or without ``on`` for every keyword of its rules.

A message of a refused list names the place of a rule, never an address
or a keyword: both are the owner's own text. See
docs/mailbox-agents/concept/agent-forwarding.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...contract import KEYWORD_FORM, ForwardForm, is_pattern, waits_for
from ...errors import ConfigError, describe_invalid

__all__ = ["On", "Rule", "Rules", "load_rules"]

# The longest address, as SMTP allows a path.
_LONGEST = 254


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
    """The keywords a message carries, all of them, and the forward it
    gets: to whom, in which form, and whether its sender check must
    pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    keywords: tuple[str, ...] = Field(min_length=1, max_length=10)
    to: tuple[str, ...] = Field(min_length=1, max_length=5)
    forward_as: ForwardForm = "inline"
    sender_check: Literal["required", "off"] = "required"

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(KEYWORD_FORM.fullmatch(keyword) for keyword in value):
            raise ValueError("a keyword is lower case letters, digits and dashes")
        return value

    @field_validator("to")
    @classmethod
    def _addresses(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Each address with one @ and no white space, kept in lower case
        and once, in the order of the list."""
        for address in value:
            local, at, domain = address.partition("@")
            if (
                not (local and at and domain)
                or "@" in domain
                or any(c.isspace() for c in address)
                or len(address) > _LONGEST
            ):
                raise ValueError(
                    "an address of to is one @ between two parts, no white "
                    f"space, at most {_LONGEST} characters"
                )
        return tuple(dict.fromkeys(address.casefold() for address in value))

    def fits(self, carried: frozenset[str]) -> bool:
        """Whether a message that carries ``carried``, in lower case,
        carries every keyword of the rule."""
        return all(keyword in carried for keyword in self.keywords)


class Rules(BaseModel):
    """The whole list: what it waits for, and its rules in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    on: On | None = None
    rules: tuple[Rule, ...] = Field(min_length=1, max_length=50)

    def waits_for(self, keyword: str) -> bool:
        """Whether the list waits for ``keyword``, case aside: one ``on``
        names, or without ``on`` one of its rules."""
        if self.on is not None:
            return waits_for(self.on.keywords, keyword)
        return any(waits_for(rule.keywords, keyword) for rule in self.rules)

    def first(self, keywords: tuple[str, ...]) -> tuple[int, Rule] | None:
        """The first rule that fits a message with ``keywords``, with its
        place from 1, or None."""
        carried = frozenset(keyword.casefold() for keyword in keywords)
        return next(
            ((n, rule) for n, rule in enumerate(self.rules, 1) if rule.fits(carried)),
            None,
        )

    def recipients(self) -> frozenset[str]:
        """Every address of the list, in lower case."""
        return frozenset(address for rule in self.rules for address in rule.to)


def load_rules(path: Path) -> Rules:
    """The list at ``path``, a JSON file, or a :class:`ConfigError` that
    says what is wrong with it: the place of a rule, never its text."""
    try:
        # utf-8-sig: an editor may start the file with the mark of UTF-8.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        # A ValueError: a file in another encoding than UTF-8.
        raise ConfigError(
            f"the forwarding list {path.name} cannot be read ({type(exc).__name__})"
        ) from None
    try:
        data = json.loads(text)
    except ValueError:
        raise ConfigError(f"the forwarding list {path.name} is no JSON") from None
    try:
        return Rules.model_validate(data)
    except ValueError as exc:
        raise ConfigError(
            f"the forwarding list {path.name}: {describe_invalid(exc)}"
        ) from None
