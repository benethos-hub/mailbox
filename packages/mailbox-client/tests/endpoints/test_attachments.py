"""A link to an attachment for another service, the same for both
clients."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from benethos_mailbox_client import ApiError, AttachmentLink, Secret

from ..fake_api import FakeApi

LINK = {
    "url": "https://mail.test/v1/links/" + "s" * 128,
    "expires_at": "2026-10-01T08:02:00Z",
    "content_type": "application/pdf",
    "size": 12,
    "filename": "a.pdf",
}
LINKS = "/v1/accounts/acc_1/messages/msg_1/attachments/att_0/links"


async def test_share_attachment_answers_the_link(make_client: Callable) -> None:
    api = FakeApi(LINK, 201)
    found = await make_client(api).share_attachment("acc_1", "msg_1", "att_0")
    assert api.call() == ("POST", LINKS, {}, {})
    assert found == AttachmentLink(
        url=Secret(LINK["url"]),
        expires_at=datetime(2026, 10, 1, 8, 2, tzinfo=UTC),
        content_type="application/pdf",
        size=12,
        filename="a.pdf",
    )
    assert "s" * 128 not in repr(found)


async def test_share_attachment_asks_for_fewer_seconds(make_client: Callable) -> None:
    api = FakeApi({**LINK, "filename": None}, 201)
    found = await make_client(api).share_attachment(
        "acc_1", "msg_1", "att_0", expires_in=30
    )
    assert api.call() == ("POST", LINKS, {}, {"expires_in": 30})
    assert found.filename is None


async def test_share_attachment_reads_a_refusal(make_client: Callable) -> None:
    api = FakeApi(
        {"error": {"code": "forbidden", "message": "needs share_attachment"}}, 403
    )
    with pytest.raises(ApiError) as raised:
        await make_client(api).share_attachment("acc_1", "msg_1", "att_0")
    assert raised.value.code == "forbidden"
