"""The mailbox service behind sources/mailbox.py, mocked."""

from __future__ import annotations

import ssl
from datetime import date

import httpx
import pytest

from benethos_mailbox_agents.contract import Placed
from benethos_mailbox_agents.errors import (
    ChangesExpiredError,
    ConfigError,
    MailboxRefusedError,
    MailboxUnavailableError,
)
from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.sources import mailbox as sources
from benethos_mailbox_agents.sources.mailbox import Mailbox, _call, connect

from ..agents_fake import ACCOUNT, FakeService, wire_message

REF = MessageRef(account_id=ACCOUNT, message_id="m1")

# Brackets nested deeper than any parser's stack holds: 20 000 raise a
# RecursionError on Windows, not on Linux from Python 3.14.
DEEP = 1_000_000


async def test_the_feed_from_a_state_with_pages_followed(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    start = await mailbox.start()
    for number in range(450):
        fake_service.change("message.created", f"m{number}")
    fake_service.feed.append(
        {
            "type": "account.updated",
            "id": "x",
            "account_id": ACCOUNT,
            "at": "2026-11-17T08:00:00+00:00",
        }
    )

    events, state = await mailbox.changes(start)

    assert start == "0"
    assert len(events) == 450
    assert events[0].ref == MessageRef(account_id=ACCOUNT, message_id="m0")
    assert events[0].type == "message.created"
    assert state == "451"


async def test_an_expired_state_is_its_own_error(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.expired.add("7")

    with pytest.raises(ChangesExpiredError):
        await mailbox.changes("7")


async def test_a_message_with_its_folders_by_path(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(
        wire_message(
            "m1",
            folder_ids=["inv-hosting"],
            sender="billing@hosting.example.test",
            sender_name="Billing",
            attachments=[{"filename": "R-1.pdf", "content_type": "application/pdf"}],
            keywords=["$seen"],
        )
    )

    found = await mailbox.message(REF)

    assert found.folders[0].path == "Invoices/Hosting"
    assert found.sender is not None
    assert found.sender.domain == "hosting.example.test"
    assert found.attachments[0].filename == "R-1.pdf"
    assert found.keywords == ("$seen",)
    assert found.text == "Hello."


@pytest.mark.parametrize(
    ("checked", "found"), [("pass", "pass"), ("fail", "fail"), (None, "unknown")]
)
async def test_a_message_carries_what_its_sender_check_says(
    fake_service: FakeService, mailbox: Mailbox, checked: str | None, found: str
) -> None:
    fake_service.add(wire_message("m1", sender_check=checked))

    message = await mailbox.message(REF)

    assert message.sender_check == found
    placed = Placed.of(message)
    assert placed.sender_check == found
    assert placed.sent_by(["Someone@Example.test"])
    assert not placed.sent_by(["other@example.test"])
    assert "someone" not in repr(placed)


async def test_a_sender_check_the_api_does_not_describe_is_a_refusal(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(wire_message("m1", sender_check="maybe"))

    with pytest.raises(MailboxRefusedError, match="not what the API describes"):
        await mailbox.message(REF)


async def test_a_message_without_text_has_an_empty_one(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(wire_message("m1", text=None, sender=None))

    found = await mailbox.message(REF)

    assert (found.text, found.sender) == ("", None)


HIDDEN = '<p>Ihre Rechnung ist online</p><div style="display:none">x</div>'


@pytest.mark.parametrize(
    ("text", "html", "read"),
    [
        (None, HIDDEN, "Ihre Rechnung ist online"),
        (" \n ", HIDDEN, "Ihre Rechnung ist online"),
        ("Ihre Rechnung liegt bei.\n", HIDDEN, "Ihre Rechnung liegt bei.\n"),
        (None, f"<p>Rechnung{chr(0xD800)}</p>", "Rechnung�"),
    ],
    ids=["html-only", "white-space-text", "text", "lone-surrogate"],
)
async def test_the_text_is_the_text_part_else_the_visible_html(
    fake_service: FakeService,
    mailbox: Mailbox,
    text: str | None,
    html: str,
    read: str,
) -> None:
    fake_service.add(wire_message("m1", text=text, html=html))

    found = await mailbox.message(REF)

    assert found.text == read


async def test_a_keyword_with_a_lone_surrogate_is_read_replaced(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    keywords = ["agent-invoice", f"{chr(0xD800)}x"]
    fake_service.add(wire_message("m1", thread_id="t", keywords=keywords))

    found = await mailbox.message(REF)
    [in_thread] = (await mailbox.thread(ACCOUNT, "t")).messages

    assert found.keywords == in_thread.keywords == ("agent-invoice", "�x")


async def test_a_new_folder_is_asked_for_again(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    await mailbox.folders(ACCOUNT)
    fake_service.folders[ACCOUNT].append({"id": "new", "name": "New", "role": None})

    found = await mailbox.folder_at(ACCOUNT, "New")

    assert found is not None and found.id == "new"
    assert await mailbox.folder_at(ACCOUNT, "Missing") is None


async def test_a_thread_oldest_first(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(
        wire_message("m2", thread_id="t", date="2026-11-18T08:00:00+00:00")
    )
    fake_service.add(wire_message("m1", thread_id="t", folder_ids=["sent"]))

    found = await mailbox.thread(ACCOUNT, "t")

    assert [m.ref.message_id for m in found.messages] == ["m1", "m2"]
    assert found.messages[0].in_role("sent")


async def test_recent_follows_the_pages(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    for number in range(250):
        fake_service.add(wire_message(f"m{number:03d}"), change=None)
    fake_service.add(wire_message("s1", folder_ids=["sent"]), change=None)
    fake_service.add(wire_message("x1", folder_ids=["inv"]), change=None)

    found = await mailbox.recent(date(2026, 11, 10), roles=("inbox", "sent"))

    assert len(found) == 251
    assert MessageRef(account_id=ACCOUNT, message_id="s1") in found
    asked = [
        r.url.params for r in fake_service.requests if r.url.path == "/v1/messages"
    ]
    assert [(p["folder"], p.get("cursor")) for p in asked] == [
        ("inbox", None),
        ("inbox", "200"),
        ("sent", None),
    ]
    assert asked[0]["after"] == "2026-11-10"


async def test_the_three_actions(fake_service: FakeService, mailbox: Mailbox) -> None:
    fake_service.add(wire_message("m1"))

    await mailbox.add_keyword(REF, "invoice")
    await mailbox.remove_keyword(REF, "old")
    await mailbox.move(REF, "inv-mo")

    assert fake_service.writes() == [
        (f"/v1/accounts/{ACCOUNT}/messages/m1", {"add_keywords": ["invoice"]}),
        (f"/v1/accounts/{ACCOUNT}/messages/m1", {"remove_keywords": ["old"]}),
        (f"/v1/accounts/{ACCOUNT}/messages/m1", {"folder_ids": ["inv-mo"]}),
    ]
    assert fake_service.messages[(ACCOUNT, "m1")]["folder_ids"] == ["inv-mo"]


async def test_a_folder_is_made_at_the_top_and_below_another(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    top = await mailbox.create_folder(ACCOUNT, "Providers")
    below = await mailbox.create_folder(ACCOUNT, "Providers/CloudHost")

    assert fake_service.made() == [
        {"name": "Providers"},
        {"name": "CloudHost", "parent_id": top.id},
    ]
    assert (top.path, below.path) == ("Providers", "Providers/CloudHost")
    found = await mailbox.folder_at(ACCOUNT, "Providers/CloudHost")
    assert found is not None and found.id == below.id


async def test_a_folder_below_a_missing_one_is_refused(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    with pytest.raises(MailboxRefusedError) as raised:
        await mailbox.create_folder(ACCOUNT, "Missing/CloudHost")

    assert raised.value.reason == "parent_missing"
    assert raised.value.status is None
    assert fake_service.made() == []


async def test_a_folder_that_exists_is_refused_by_the_service(
    mailbox: Mailbox,
) -> None:
    with pytest.raises(MailboxRefusedError) as raised:
        await mailbox.create_folder(ACCOUNT, "Invoices")

    assert (raised.value.status, raised.value.reason) == (409, "conflict")


async def test_a_refusal_carries_status_and_code(mailbox: Mailbox) -> None:
    with pytest.raises(MailboxRefusedError) as raised:
        await mailbox.message(REF)

    assert (raised.value.status, raised.value.reason) == (404, "not_found")


async def test_a_service_that_is_down_is_unavailable(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.down = True

    with pytest.raises(MailboxUnavailableError):
        await mailbox.start()


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")],
)
async def test_a_service_that_cannot_be_reached_is_unavailable(
    failure: httpx.TransportError,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    async with connect(
        "https://mailbox.example.test",
        "token-value",
        transport=httpx.MockTransport(handler),
    ) as mailbox:
        with pytest.raises(MailboxUnavailableError):
            await mailbox.start()


async def test_an_answer_of_the_wrong_shape_is_a_refusal() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    async with connect(
        "https://mailbox.example.test", "token-value", transport=transport
    ) as mailbox:
        with pytest.raises(MailboxRefusedError):
            await mailbox.start()


async def test_the_environment_sets_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client gets a transport that reads no proxy, and httpx takes no
    proxy of the environment for a client given a transport."""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example.test:3128")
    made: list[dict[str, object]] = []
    given: list[object] = []
    real_transport, real_client = httpx.AsyncHTTPTransport, sources.MailboxClient

    def transport(**kwargs: object) -> httpx.AsyncHTTPTransport:
        made.append(kwargs)
        return real_transport(**kwargs)

    def client(**kwargs: object) -> object:
        given.append(kwargs["transport"])
        return real_client(**kwargs)

    monkeypatch.setattr(sources.httpx, "AsyncHTTPTransport", transport)
    monkeypatch.setattr(sources, "MailboxClient", client)

    async with connect("https://mailbox.example.test", "token-value"):
        pass

    assert [kwargs["trust_env"] for kwargs in made] == [False]
    assert len(given) == 1 and isinstance(given[0], real_transport)


async def test_http_to_another_machine_needs_allowing() -> None:
    with pytest.raises(ConfigError, match="mailbox service"):
        async with connect("http://mailbox.example.test", "token-value"):
            pass

    async with connect(
        "http://mailbox.example.test", "token-value", allow_http=True
    ) as mailbox:
        assert isinstance(mailbox, Mailbox)


async def test_accounts_are_the_ids_the_user_is_granted(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.folders["acc2"] = []

    assert await mailbox.accounts() == (ACCOUNT, "acc2")


async def test_recent_in_lists_one_folder_of_one_account(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(wire_message("h1", folder_ids=["inv-hosting"]), change=None)
    fake_service.add(wire_message("i1"), change=None)

    found = await mailbox.recent_in(ACCOUNT, "inv-hosting", date(2026, 11, 10))

    assert found == [MessageRef(account_id=ACCOUNT, message_id="h1")]
    (asked,) = [r for r in fake_service.requests if r.url.path.endswith("/messages")]
    assert asked.url.path == f"/v1/accounts/{ACCOUNT}/messages"
    assert (asked.url.params["folder"], asked.url.params["after"]) == (
        "inv-hosting",
        "2026-11-10",
    )


async def test_a_ca_of_the_settings_is_what_the_service_is_trusted_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    given: list[object] = []
    real = httpx.AsyncHTTPTransport

    def transport(**kwargs: object) -> httpx.AsyncHTTPTransport:
        given.append(kwargs["verify"])
        assert kwargs["trust_env"] is False
        return real(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport)
    context = ssl.create_default_context()

    async with connect("https://mailbox.example.test", "t", verify=context):
        pass
    async with connect("https://mailbox.example.test", "t"):
        pass

    assert given == [context, True]


async def test_a_lone_surrogate_from_the_service_becomes_a_replacement(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    odd = chr(0xDCFC)
    fake_service.folders[ACCOUNT].append(
        {"id": "odd", "name": f"Ablage{odd}", "role": None, "parent_id": None}
    )
    fake_service.add(
        wire_message(
            "m1",
            folder_ids=["odd"],
            subject=f"Rechnung{odd}",
            sender_name=f"Name{odd}",
            text=f"Text{odd}",
            attachments=[
                {"filename": f"R{odd}.pdf", "content_type": "application/pdf"}
            ],
        )
    )

    found = await mailbox.message(REF)

    assert found.sender is not None
    values = [
        found.subject or "",
        found.text,
        found.sender.name or "",
        found.sender.email,
        found.attachments[0].filename or "",
        found.folders[0].name,
        found.folders[0].path,
    ]
    for value in values:
        value.encode("utf-8")
    assert found.subject == "Rechnung\ufffd"
    assert found.folders[0].path == "Ablage\ufffd"


async def test_a_string_without_a_surrogate_stays_as_it_is(
    fake_service: FakeService, mailbox: Mailbox
) -> None:
    fake_service.add(wire_message("m1", subject="Grüße \u00e9 \U0001f600", text="Text"))

    found = await mailbox.message(REF)

    assert found.subject == "Grüße \u00e9 \U0001f600"


@pytest.mark.parametrize(
    "field", ["subject", "text_body", "thread_id"], ids=["subject", "text", "thread"]
)
async def test_a_field_of_another_type_is_a_refusal_without_its_value(
    fake_service: FakeService, mailbox: Mailbox, field: str
) -> None:
    message = wire_message("m1")
    message[field] = ["Geheimer Betreff"]
    fake_service.add(message)

    with pytest.raises(MailboxRefusedError) as found:
        await mailbox.message(REF)

    assert found.value.reason == "unexpected_response"
    assert "Geheimer" not in str(found.value)
    assert found.value.__cause__ is None


async def test_a_body_nested_too_deep_is_an_upstream_away() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"[" * DEEP, headers={"content-type": "application/json"}
        )

    async with connect(
        "https://mailbox.example.test",
        "token-value",
        transport=httpx.MockTransport(handle),
    ) as opened:
        with pytest.raises(MailboxUnavailableError):
            await opened.message(REF)


async def test_a_recursion_error_of_the_client_is_an_upstream_away() -> None:
    async def deep() -> None:
        raise RecursionError

    with pytest.raises(MailboxUnavailableError):
        await _call(deep())
