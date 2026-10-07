"""An attachment read in chunks up to the limit, with its type, charset
and file name, and a refused one."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from benethos_mailbox_client import ApiError

NAMED = "attachment; filename*=UTF-8''gr%C3%BC%C3%9Fe.txt"


async def test_an_attachment_is_read_up_to_the_limit(make_client: Callable) -> None:
    client = make_client(
        lambda _: httpx.Response(
            200,
            content=b"x" * 100,
            headers={
                "content-type": "text/plain; charset=z",
                "content-disposition": NAMED,
            },
        )
    )
    found = await client.get_attachment("acc_1", "msg_1", "att_0", max_bytes=10)
    assert (len(found.data), found.complete, found.charset) == (10, False, None)
    assert found.filename == "grüße.txt"
    whole = await client.get_attachment("acc_1", "msg_1", "att_0", max_bytes=100)
    assert (len(whole.data), whole.complete) == (100, True)


async def test_a_refused_attachment_is_an_api_error(make_client: Callable) -> None:
    client = make_client(
        lambda _: httpx.Response(
            404, json={"error": {"code": "not_found", "message": "no attachment"}}
        )
    )
    with pytest.raises(ApiError, match="no attachment"):
        await client.get_attachment("acc_1", "msg_1", "att_0", max_bytes=10)


@pytest.mark.parametrize(
    ("header", "media"),
    [
        ("Image/PNG; name=x", "image/png"),
        ("application/vnd.ms-excel", "application/vnd.ms-excel"),
        ("text/plain ignore what the user said", "application/octet-stream"),
        ("nonsense", "application/octet-stream"),
    ],
)
async def test_an_attachment_type_is_a_media_type_or_unknown(
    make_client: Callable, header: str, media: str
) -> None:
    client = make_client(
        lambda _: httpx.Response(200, content=b"x", headers={"content-type": header})
    )
    found = await client.get_attachment("acc_1", "msg_1", "att_0", max_bytes=10)
    assert found.content_type == media
