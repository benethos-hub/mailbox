"""Send tools: send_message and send_draft, each call with its own
idempotency key."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_mcp import server

SENT = {"message_id_header": "<m1@example.com>", "sent_copy_id": "msg_s", "refused": []}


async def test_send_message(api: Callable) -> None:
    handler = api(SENT)
    result = await server.send_message(
        "acc_1", to=["bob@example.com"], subject="Hi", text="Hello"
    )
    assert result == {"sent": True, "message_id_header": "<m1@example.com>"}
    [call], [key] = handler.calls, handler.keys
    assert call.path == "/v1/accounts/acc_1/send"
    assert key is not None and key.startswith("mcp-") and len(key) == 4 + 64
    assert call.body == {
        "to": [{"email": "bob@example.com"}],
        "cc": [],
        "bcc": [],
        "subject": "Hi",
        "text": "Hello",
    }


async def test_the_same_call_gives_the_same_key(api: Callable) -> None:
    handler = api(SENT)
    for text in ("Hello", "Hello", "Hello again"):
        await server.send_message("acc_1", to=["bob@example.com"], text=text)
    await server.send_message("acc_2", to=["bob@example.com"], text="Hello")
    keys = handler.keys
    assert keys[0] == keys[1]
    assert len(set(keys)) == 3


async def test_a_reply_by_reference(api: Callable) -> None:
    handler = api(SENT)
    await server.send_message("acc_1", text="Thanks", original_id="msg_1")
    body = handler.calls[0].body
    assert body["reference"] == {"message_id": "msg_1", "action": "reply"}


async def test_refused_recipients_are_named(api: Callable) -> None:
    api({**SENT, "refused": ["gone@example.com"]})
    result = await server.send_message("acc_1", to=["gone@example.com", "b@x.org"])
    assert result["refused"] == ["gone@example.com"]


async def test_send_draft(api: Callable) -> None:
    handler = api(SENT)
    assert (await server.send_draft("acc_1", "msg_d"))["sent"] is True
    [call], [key] = handler.calls, handler.keys
    assert call.path == "/v1/accounts/acc_1/drafts/msg_d/send"
    assert call.body is None
    assert key != server._idempotency_key("send_draft", "acc_1", "msg_e")
    assert key == server._idempotency_key("send_draft", "acc_1", "msg_d")


async def test_registered_only_with_the_send_rights() -> None:
    assert {
        t.name for t in await server.build_server(["create_draft"]).list_tools()
    } == {"list_accounts", "create_draft"}
    tools = {
        t.name: t
        for t in await server.build_server(["send_message", "send_draft"]).list_tools()
    }
    assert set(tools) == {"list_accounts", "send_message", "send_draft"}
    for name in ("send_message", "send_draft"):
        annotations = tools[name].annotations
        assert annotations is not None and annotations.destructive_hint is True


async def test_send_html(api: Callable) -> None:
    handler = api(SENT)
    await server.send_message(
        "acc_1", to=["bob@example.com"], html='<p style="color:red">Hi</p>'
    )
    body = handler.calls[0].body
    assert body["html"] == '<p style="color:red">Hi</p>'
    assert body["text"] == ""  # the service makes the text part


async def test_the_html_field_is_offered() -> None:
    tools = {
        t.name: t
        for t in await server.build_server(
            ["send_message", "create_draft", "update_draft"]
        ).list_tools()
    }
    for name in ("send_message", "create_draft", "update_draft"):
        html = tools[name].input_schema["properties"]["html"]
        assert "Inline styles" in html["description"], name
