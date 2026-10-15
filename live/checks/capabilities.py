"""What an account names it can do, as each kind of server offers it
(docs/UNIFORM.md section 3), and the check that it does."""

from __future__ import annotations

from typing import Any

import httpx

from .run import Run

# Gmail: no keywords, no push, refused recipients come back later as a
# bounce mail.
GMAIL = frozenset(
    {
        "read_state",
        "stars",
        "folders",
        "move",
        "trash",
        "purge",
        "labels",
        "search",
        "drafts",
        "send",
        "sent_copy",
        "threads",
        "external_changes",
    }
)
# A JMAP server with submission, an event source and the special folders:
# everything but naming refused recipients at once.
JMAP = GMAIL | {"keywords", "push"}


def named(run: Run, described: dict[str, Any], expected: frozenset[str]) -> None:
    """The account names exactly ``expected``."""
    offered = set(described["capabilities"])
    run.check(
        "the account names what it can do",
        offered == expected,
        ", ".join(sorted(offered ^ expected)),
    )


def refused(run: Run, client: httpx.Client, url: str, change: dict[str, Any]) -> None:
    """A change of what the account lacks answers 501, refused before the
    provider is asked: nothing changes."""
    answer = client.patch(url, json=change)
    run.check(f"{', '.join(change)} answers 501", answer.status_code == 501)
