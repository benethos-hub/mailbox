"""Search filters (CONCEPT 6.6): what the API takes, and IMAP SEARCH."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import MessageFilter
from benethos_mailbox_api.data.providers.protocols.imap import (
    ImapServer,
    ImapSession,
    SearchCriteria,
)
from benethos_mailbox_api.errors import BadRequestError

from .imap_fake import FakeFolder, FakeMailBox, make_message
from .test_imap import provider


@pytest.fixture
def box() -> FakeMailBox:
    box = FakeMailBox()
    box.folders = {"INBOX": FakeFolder()}
    box.add(
        "INBOX",
        1,
        make_message(
            "Rechnung September",
            sender="Steuerbüro Berg <kanzlei@example.com>",
            date=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
            attachments=[("rechnung.pdf", "application/pdf", b"%PDF")],
        ),
        flags=("\\Seen", "\\Flagged"),
    )
    box.add(
        "INBOX",
        2,
        make_message(
            "Termin",
            to="team@example.com",
            date=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
        ),
    )
    box.add(
        "INBOX",
        3,
        make_message("Rechnung Oktober", date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC)),
    )
    return box


async def subjects(box: FakeMailBox, **fields: object) -> list[str]:
    page = await provider(box).list_messages(
        None, limit=10, cursor=None, search=MessageFilter.model_validate(fields)
    )
    return sorted(m.subject or "" for m in page.items)


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"sender": "kanzlei"}, ["Rechnung September"]),
        ({"sender": "Steuerbüro"}, ["Rechnung September"]),
        ({"to": "team@"}, ["Termin"]),
        ({"subject": "rechnung"}, ["Rechnung Oktober", "Rechnung September"]),
        ({"after": date(2026, 9, 10)}, ["Rechnung Oktober", "Termin"]),
        ({"before": date(2026, 9, 10)}, ["Rechnung September"]),
        ({"starred": True}, ["Rechnung September"]),
        ({"starred": False}, ["Rechnung Oktober", "Termin"]),
        ({"has_attachments": True}, ["Rechnung September"]),
        ({"has_attachments": False}, ["Rechnung Oktober", "Termin"]),
        ({"subject": "rechnung", "unread": True}, ["Rechnung Oktober"]),
    ],
)
async def test_imap_filters(
    box: FakeMailBox, fields: dict[str, object], expected: list[str]
) -> None:
    assert await subjects(box, **fields) == expected


async def test_non_ascii_filters_search_in_utf8(box: FakeMailBox) -> None:
    await subjects(box, sender="Steuerbüro")
    assert any(c[0] == "search" and c[2] == "UTF-8" for c in box.calls)


def test_the_session_refuses_a_line_break_in_a_search(box: FakeMailBox) -> None:
    """IMAPClient quotes search text but keeps CR and LF, which would end the
    command and start one of the caller's choosing."""
    session = ImapSession(
        ImapServer("imap.example.com", 993, "tls"), client_factory=box
    )
    session.login("me@example.com", "secret")
    session.select("INBOX")
    for field in ("text", "sender", "to", "subject"):
        with pytest.raises(BadRequestError, match="control characters"):
            session.search(SearchCriteria(**{field: "a\r\nX1 DELETE INBOX"}))
    assert not [c for c in box.calls if c[0] == "search"]


# --- the API ------------------------------------------------------------------------


def test_filters_through_the_api(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    page = client.get(url, params={"subject": "invoice", "unread": False}).json()
    assert [m["subject"] for m in page["items"]] == ["Invoice 3"]
    page = client.get(url, params={"from": "alice", "after": "2026-09-04"}).json()
    assert sorted(m["subject"] for m in page["items"]) == ["Hello 4", "Invoice 3"]


def test_a_folder_by_its_role(client: TestClient, account_id: str) -> None:
    url = f"/v1/accounts/{account_id}/messages"
    assert len(client.get(url, params={"folder": "inbox"}).json()["items"]) == 5
    missing = client.get(url, params={"folder": "trash"})
    assert missing.status_code == 404
    assert "trash" in missing.json()["error"]["message"]


@pytest.mark.parametrize("field", ["q", "from", "to", "subject"])
def test_search_text_on_one_line(
    client: TestClient, account_id: str, field: str
) -> None:
    for url in ("/v1/messages", f"/v1/accounts/{account_id}/messages"):
        answer = client.get(url, params={field: "a\r\nX1 DELETE INBOX"})
        assert answer.status_code == 422


def test_filters_across_accounts(client: TestClient, account_id: str) -> None:
    page = client.get("/v1/messages", params={"subject": "hello"}).json()
    assert [m["subject"] for m in page["items"]] == ["Hello 4", "Hello 2", "Hello 0"]
