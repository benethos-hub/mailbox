"""What an account names it can do, as each kind of server offers it
(docs/mailbox-service/UNIFORM.md section 3), and the check that it does."""

from __future__ import annotations

from typing import Any

import httpx

from .run import Run

# Gmail: no keywords, no push, refused recipients come back later as a
# bounce mail. Gmail names its receiving server itself: the sender check
# reads its entries.
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
        "sender_check",
    }
)
# A JMAP server with submission, an event source and the special folders:
# everything but naming refused recipients at once. The sender check only
# where the account names its receiving server, which the test accounts
# do not.
JMAP = (GMAIL - {"sender_check"}) | {"keywords", "push"}
# An IMAP server with SMTP, IDLE, CONDSTORE and the special folders: a
# message in one folder alone, and SMTP names a refused recipient at once.
IMAP = (JMAP - {"labels"}) | {"refused"}
# A POP3 server with SMTP: the inbox alone, deleting for good and sending.
POP3 = frozenset({"purge", "refused", "send"})


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
