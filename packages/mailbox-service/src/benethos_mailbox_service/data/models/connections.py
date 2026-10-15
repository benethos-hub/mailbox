"""How a kind of account is connected, as a form draws it (UNIFORM U6):
the settings it takes with their words, hints and choices, the secret
it signs in with, where a person signs in instead, and what its page
sums up. A new kind of account brings its own, and no form changes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SettingField:
    """One setting of a connection. ``choices``: the values it takes with
    their words, a value "" for the default. ``required`` when an account
    is connected, ``number`` for a port, ``login`` for a name a browser
    must not fill in."""

    name: str
    label: str
    hint: str | None = None
    choices: tuple[tuple[str, str], ...] = ()
    default: str = ""
    required: bool = False
    number: bool = False
    login: bool = False


@dataclass(frozen=True, slots=True)
class Summary:
    """A line of an account's page: a server by its host, port and path."""

    label: str
    host: str
    port: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class Connection:
    """How accounts of one kind are connected. ``kind``: the provider type.
    ``about``: what a person should know before choosing it. ``secret``:
    the word for what signs in, where a password or a token does.
    ``signs_in_at``: where a person signs in instead, with OAuth.
    ``by_hand``: offered to set up by hand, its servers typed in."""

    kind: str
    name: str
    fields: tuple[SettingField, ...] = ()
    secret: str = "Password"
    about: str | None = None
    signs_in_at: str | None = None
    by_hand: bool = False
    summary: tuple[Summary, ...] = ()
