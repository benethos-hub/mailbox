"""The names receiving servers wrote into the newest mails, for a person
to choose the account's own from: IMAP, POP3 and JMAP read them, Gmail
and Microsoft name theirs themselves."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.data.providers import ServerNames

from ...conformance_helpers import box, mail

ENTRY = "Authentication-Results"


@pytest.mark.parametrize("kind", ["imap", "pop3", "jmap"])
async def test_the_names_of_the_newest_mails(kind: str) -> None:
    found = box(kind)
    found.put(mail("Without"))
    found.put(
        mail(
            "Two",
            headers=[
                (ENTRY, "mx.example.org; dmarc=pass header.from=example.com"),
                (ENTRY, "MX.Example.NET 1; spf=pass smtp.mailfrom=example.com"),
            ],
        )
    )
    found.put(mail("Odd", headers=[(ENTRY, "not a host; dkim=pass")]))
    adapter = found.make()
    assert isinstance(adapter, ServerNames)
    # Newest first, one name per entry, none for a name with spaces.
    assert await adapter.authserv_ids(10) == [
        [],
        ["mx.example.org", "mx.example.net"],
        [],
    ]
    assert len(await adapter.authserv_ids(2)) == 2


@pytest.mark.parametrize("kind", ["gmail", "microsoft"])
def test_gmail_and_microsoft_read_none(kind: str) -> None:
    assert not isinstance(box(kind).make(), ServerNames)
