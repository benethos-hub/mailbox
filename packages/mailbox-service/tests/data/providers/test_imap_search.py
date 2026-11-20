"""IMAP SEARCH: the filters of a list as the server reads them, and text
beyond ASCII searched in UTF-8."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from benethos_mailbox_service.data.models import MessageFilter

from ...imap_fake import FakeFolder, FakeMailBox, make_message
from .imap_adapter import INBOX, provider


@pytest.fixture
def search_box() -> FakeMailBox:
    search_box = FakeMailBox()
    search_box.folders = {"INBOX": FakeFolder()}
    search_box.add(
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
    search_box.add(
        "INBOX",
        2,
        make_message(
            "Termin",
            to="team@example.com",
            date=datetime(2026, 9, 10, 9, 0, tzinfo=UTC),
        ),
    )
    search_box.add(
        "INBOX",
        3,
        make_message("Rechnung Oktober", date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC)),
    )
    return search_box


async def subjects(search_box: FakeMailBox, **fields: object) -> list[str]:
    page = await provider(search_box).list_messages(
        INBOX, limit=10, cursor=None, search=MessageFilter.model_validate(fields)
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
    search_box: FakeMailBox, fields: dict[str, object], expected: list[str]
) -> None:
    assert await subjects(search_box, **fields) == expected


async def test_non_ascii_filters_search_in_utf8(search_box: FakeMailBox) -> None:
    await subjects(search_box, sender="Steuerbüro")
    assert any(c[0] == "search" and c[2] == "UTF-8" for c in search_box.calls)
