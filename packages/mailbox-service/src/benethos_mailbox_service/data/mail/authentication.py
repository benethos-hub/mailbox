"""The receiving server's statement about the sender of a message, read
from its Authentication-Results entry (RFC 8601).

Only the entries of the account's own server count, known by their
authserv-id. Some servers write two. Each is judged alone, and the
result stands when all of them come to the same one: where they differ,
it is unknown. So an entry the sender brought can spoil the result but
never improve it. Entries of other servers,
``ARC-Authentication-Results`` and the like are never read.

The header is the sender's text as much as the server's. Nothing of it
leaves this module but fixed values and a domain checked as a host
name. The grammar is read by hand: comments and quoted strings are
values, never statements.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, get_args

from ...common.hosts import ascii_host, is_host_name
from ..models import (
    UNKNOWN_ACCOUNT,
    SenderCheck,
    SenderCheckMethod,
    SenderCheckReason,
)

# The header of the entries.
HEADER = "Authentication-Results"
# A longer entry is not read.
MAX_ENTRY = 8192
# The part of an entry its authserv-id is read from.
_HEAD = 1024
_ERRORS = frozenset({"temperror", "permerror"})
_CHECKS = frozenset(get_args(SenderCheckMethod))
# The checks that may stand in for DMARC, in the order they are asked.
_WITHOUT_DMARC: tuple[Literal["dkim", "spf"], ...] = ("dkim", "spf")


@dataclass(frozen=True, slots=True)
class Trust:
    """The authserv-ids of the account's own receiving server: a host
    name, or one with a leading dot for every host below it."""

    ids: tuple[str, ...]

    def trusts(self, authserv_id: str) -> bool:
        found = authserv_id.lower().rstrip(".")
        return any(
            found.endswith(own) if own.startswith(".") else found == own
            for own in self.ids
        )


def host(value: str) -> str | None:
    """``value`` as a host name in lower case, without a dot at its end,
    or None where it is none: labels of ASCII letters, digits and inner
    dashes, at most 63 characters each and 253 in all."""
    found = value.lower().rstrip(".")
    return found if is_host_name(found, dotted=False) else None


def sender_check(
    entries: Sequence[str], sender: str | None, trust: Trust | None
) -> SenderCheck:
    """What the account's server stated about the domain of ``sender``.
    ``entries``: the values of every ``Authentication-Results`` header of
    the message, ``sender``: the one address in ``From``, None without
    one or with several, ``trust``: the account's own server, None where
    the account cannot tell."""
    if trust is None:
        return UNKNOWN_ACCOUNT.model_copy()
    own = [e for e in entries if (i := _authserv_id(e)) and trust.trusts(i)]
    if not own:
        return _unknown("no_entry")
    sender_domain = _domain_of(sender)
    judged = [_entry(entry, sender_domain) for entry in own]
    # The first entry, the topmost, gives the details: several that agree
    # may have checked by other methods.
    first = judged[0]
    if any(found.result != first.result for found in judged[1:]):
        return _unknown("several_entries")
    return first


def _entry(entry: str, sender: str | None) -> SenderCheck:
    """What one entry of the own server states about ``sender``."""
    results = _results(entry)
    if results is None or sender is None:
        return _unknown("unreadable")
    return _judged(results, sender)


def _unknown(reason: SenderCheckReason) -> SenderCheck:
    return SenderCheck(result="unknown", reason=reason)


@dataclass(frozen=True, slots=True)
class _Result:
    """One statement of an entry: ``dkim=pass header.d=example.com``."""

    method: str
    result: str
    properties: dict[str, str] = field(default_factory=dict)


class _UnreadableError(Exception):
    """An entry, or a domain in it, that cannot be read."""


def _judged(results: list[_Result], sender: str) -> SenderCheck:
    """The table of docs/mailbox-service/CONCEPT.md, from the statements of one
    entry."""
    try:
        dmarc = [
            r for r in results if r.method == "dmarc" and r.result in ("pass", "fail")
        ]
        if dmarc:
            return _by_dmarc(dmarc[0], sender)
        return _without_dmarc(results, sender)
    except _UnreadableError:
        return _unknown("unreadable")


def _by_dmarc(result: _Result, sender: str) -> SenderCheck:
    raw = result.properties.get("header.from")
    domain = _checked(raw) if raw is not None else None
    if result.result == "pass":
        if domain == sender:
            return SenderCheck(
                result="pass", domain=sender, matches_from=True, method="dmarc"
            )
        return SenderCheck(
            result="unknown",
            domain=domain,
            matches_from=False,
            method="dmarc",
            reason="from_differs",
        )
    return SenderCheck(
        result="fail",
        domain=domain,
        matches_from=domain == sender if domain is not None else None,
        method="dmarc",
    )


def _without_dmarc(results: list[_Result], sender: str) -> SenderCheck:
    """DKIM or SPF that passed for exactly the domain of the sender, else
    why not."""
    others: list[tuple[Literal["dkim", "spf"], str]] = []
    for method in _WITHOUT_DMARC:
        for result in results:
            if result.method != method or result.result != "pass":
                continue
            domain = _checked_domain(result)
            if domain is None:
                continue
            if domain == sender:
                return SenderCheck(
                    result="pass", domain=sender, matches_from=True, method=method
                )
            others.append((method, domain))
    if others:
        method, domain = others[0]
        return SenderCheck(
            result="unknown",
            domain=domain,
            matches_from=False,
            method=method,
            reason="other_domain",
        )
    if any(r.method in _CHECKS and r.result in _ERRORS for r in results):
        return _unknown("error")
    return _unknown("no_proof")


def _checked_domain(result: _Result) -> str | None:
    """The domain a passed DKIM or SPF names: ``header.d``, else the
    domain of ``header.i`` (Gmail writes that), or the domain of
    ``smtp.mailfrom``, an address or a domain."""
    found = result.properties
    if result.method == "dkim":
        raw = found.get("header.d")
        if raw is None:
            identity = found.get("header.i")
            raw = identity.rpartition("@")[2] if identity and "@" in identity else None
    else:
        mailfrom = found.get("smtp.mailfrom")
        raw = mailfrom.rpartition("@")[2] if mailfrom else None
    return _checked(raw) if raw is not None else None


def _checked(value: str) -> str:
    found = host(value)
    if found is None:
        raise _UnreadableError
    return found


def _domain_of(sender: str | None) -> str | None:
    """The domain of the sender's address, in its ASCII form (IDNA 2008,
    as the servers write it)."""
    if not sender or "@" not in sender:
        return None
    written = ascii_host(sender.rpartition("@")[2])
    return host(written) if written is not None else None


def authserv_ids(entries: Sequence[str]) -> list[str | None]:
    """The authserv-id of each entry, in lower case, where it is a host
    name, alone or with a version: for a person to choose the account's
    own server from. One place per entry, in the order of the mail, None
    where the name is no host name."""
    found: list[str | None] = []
    for entry in entries:
        statements = _statements(entry[:_HEAD], head_only=True)
        head = statements[0] if statements else []
        name = host(head[0][0]) if _head_ok(head) else None
        found.append(name or None)
    return found


# --- the grammar of RFC 8601 section 2.2 --------------------------------------

# A token of an entry: its text, and whether it was a quoted string.
_Token = tuple[str, bool]


def _authserv_id(entry: str) -> str | None:
    """The authserv-id at the start of an entry, None where it cannot be
    read."""
    statements = _statements(entry[:_HEAD], head_only=True)
    if not statements or not statements[0]:
        return None
    return statements[0][0][0]


def _head_ok(head: list[_Token]) -> bool:
    """Whether the head of an entry is an authserv-id, alone or with a
    version of digits not in quotes: "mx.example.org 1"."""
    return len(head) == 1 or (
        len(head) == 2 and not head[1][1] and head[1][0].isdigit()
    )


def _results(entry: str) -> list[_Result] | None:
    """The statements of an entry after its authserv-id, None where it
    cannot be read."""
    if len(entry) > MAX_ENTRY:
        return None
    statements = _statements(entry)
    if not statements or not _head_ok(statements[0]):
        return None
    found = []
    for statement in statements[1:]:
        if not statement:
            continue
        # "none": the server checked nothing.
        if len(statement) == 1 and not statement[0][1]:
            if statement[0][0].lower() == "none":
                continue
        pairs = _pairs(statement)
        if not pairs:
            return None
        (method, result), properties = pairs[0], pairs[1:]
        kept: dict[str, str] = {}
        for key, value in properties:
            kept.setdefault(key, value)
        found.append(_Result(method.split("/")[0], result.lower(), kept))
    return found


def _pairs(tokens: list[_Token]) -> list[tuple[str, str]] | None:
    """``key=value`` pairs, the key in lower case. Space may stand around
    the ``=``, a value may be a quoted string. None for anything else."""
    pairs = []
    at = 0
    while at < len(tokens):
        text, quoted = tokens[at]
        if quoted:
            return None
        if "=" in text:
            key, _, value = text.partition("=")
        else:
            key = text
            at += 1
            if at >= len(tokens) or tokens[at][1] or not tokens[at][0].startswith("="):
                return None
            value = tokens[at][0][1:]
        if not value:
            at += 1
            if at >= len(tokens):
                return None
            value = tokens[at][0]
        if not key:
            return None
        pairs.append((key.lower(), value))
        at += 1
    return pairs


def _statements(text: str, head_only: bool = False) -> list[list[_Token]] | None:
    """The statements of an entry, split at ``;``, each its tokens:
    comments dropped, nested ones too, quoted strings as one token, a
    backslash escaping the next character. None where a comment or a
    string does not end. ``head_only``: the first statement alone."""
    tokens = _tokens(text, head_only)
    if tokens is None:
        return None
    statements: list[list[_Token]] = [[]]
    for token in tokens:
        if token == _SEPARATOR:
            statements.append([])
        else:
            statements[-1].append(token)
    return statements


# Between two statements. A word never holds a ";".
_SEPARATOR: _Token = (";", False)
_SPACE = frozenset(" \t\r\n")
_SPECIAL = frozenset('();"') | _SPACE


def _tokens(text: str, head_only: bool) -> list[_Token] | None:
    """The tokens of an entry and the separators between its statements,
    None where it cannot be read. ``head_only``: up to the first ``;``."""
    found: list[_Token] = []
    at = 0
    while 0 <= at < len(text):
        char = text[at]
        if char in _SPACE:
            at += 1
        elif char == "(":
            at = _after_comment(text, at)
        elif char == '"':
            quoted, at = _quoted(text, at)
            found.append((quoted, True))
        elif char == ";":
            if head_only:
                break
            found.append(_SEPARATOR)
            at += 1
        elif char == ")":
            return None
        else:
            end = at
            while end < len(text) and text[end] not in _SPECIAL:
                end += 1
            found.append((text[at:end], False))
            at = end
    return found if at >= 0 else None


def _after_comment(text: str, at: int) -> int:
    """Where the comment that opens at ``at`` ends, -1 where it does not."""
    depth, at = 1, at + 1
    while at < len(text) and depth:
        char = text[at]
        if char == "\\":
            at += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        at += 1
    return at if depth == 0 else -1


def _quoted(text: str, at: int) -> tuple[str, int]:
    """The quoted string that opens at ``at`` and where it ends, -1 where
    it does not."""
    found: list[str] = []
    at += 1
    while at < len(text):
        char = text[at]
        if char == '"':
            return "".join(found), at + 1
        if char == "\\":
            at += 1
            if at >= len(text):
                break
            char = text[at]
        found.append(char)
        at += 1
    return "", -1
