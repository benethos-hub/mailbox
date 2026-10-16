"""The tools follow the token's rights while the server runs: a right
granted adds its tool, one taken away removes it, and the client is
told. A refused token is asked for no more."""

from __future__ import annotations

import logging

import anyio
import pytest

from .rights_helpers import (
    ME,
    READ,
    Service,
    connected,
    following,
    me_with,
    until,
)

SHARE = "share_attachment"
LOG = "benethos_mailbox_mcp.server"


async def test_a_granted_right_adds_its_tool() -> None:
    service = Service(ME)
    async with connected(following(service, READ)) as client:
        assert SHARE not in await client.tools()
        service.me = me_with(SHARE)
        await client.told()
        assert SHARE in await client.tools()


async def test_a_right_taken_away_removes_its_tool() -> None:
    service = Service(me_with(SHARE))
    async with connected(following(service, [*READ, SHARE])) as client:
        assert SHARE in await client.tools()
        service.me = ME
        await client.told()
        assert SHARE not in await client.tools()


async def test_the_tools_keep_their_order() -> None:
    """A tool granted later stands where it would have at start."""
    service = Service(ME)
    async with connected(following(service, READ)) as client:
        service.me = me_with(SHARE)
        await client.told()
        later = await client.tools()
    async with connected(following(Service(ME), [*READ, SHARE], every=0)) as client:
        assert later == await client.tools()


async def test_nothing_changed_tells_nobody() -> None:
    service = Service(ME)
    async with connected(following(service, READ)) as client:
        await until(lambda: service.asked >= 3)
        assert client.received == []


async def test_the_change_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    service = Service(ME)
    with caplog.at_level(logging.INFO, logger=LOG):
        async with connected(following(service, READ)) as client:
            await client.tools()
            service.me = me_with(SHARE)
            await client.told()
    assert f"tools changed, 1 client told: +{SHARE}" in caplog.text


async def test_a_refused_token_removes_every_tool_and_asks_no_more(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refusal counts against this address like a wrong token, and ten
    lock it, the UI's sign-in included."""
    service = Service(ME)
    with caplog.at_level(logging.WARNING, logger=LOG):
        async with connected(following(service, READ)) as client:
            service.status = 401
            await client.told()
            assert await client.tools() == []
            asked = service.asked
            await anyio.sleep(0.1)
            assert service.asked == asked
    assert "refused the token (HTTP 401)" in caplog.text


async def test_a_user_that_may_do_nothing_gets_its_tools_back() -> None:
    service = Service(ME)
    async with connected(following(service, READ)) as client:
        service.status = 403
        await client.told()
        assert await client.tools() == []
        service.status = 200
        await client.told(2)
        assert "list_accounts" in await client.tools()


async def test_a_service_that_does_not_answer_leaves_the_tools(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warned once per outage, not on every try."""
    service = Service(ME)
    with caplog.at_level(logging.INFO, logger=LOG):
        async with connected(following(service, READ)) as client:
            before = await client.tools()
            service.down = True
            asked = service.asked
            await until(lambda: service.asked >= asked + 3)
            assert await client.tools() == before
            service.down = False
            await until(lambda: "answers again" in caplog.text)
            assert client.received == []
    assert caplog.text.count("could not ask what the token may do") == 1


async def test_without_an_interval_it_asks_only_at_start() -> None:
    service = Service(ME)
    async with connected(following(service, READ, every=0)) as client:
        await client.tools()
        await anyio.sleep(0.05)
    assert service.asked == 0
