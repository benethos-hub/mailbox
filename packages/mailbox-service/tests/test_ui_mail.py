"""Reading mail in the configuration UI."""

from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Attachment, Folder, Grant
from benethos_mailbox_service.main import Services

from .conftest import bearer_for
from .ui_helpers import sign_in


def test_every_inbox_together(ui: TestClient, account_id: str) -> None:
    page = ui.get("/ui/mail").text
    assert "Invoice 1" in page and "Hello 4" in page
    assert f'href="/ui/accounts/{account_id}/mail/m1"' in page
    assert "me@example.com" in page  # the account column
    assert 'class="unread"' in page


def test_search_narrows_the_list(ui: TestClient, account_id: str) -> None:
    page = ui.get("/ui/mail", params={"q": "invoice"}).text
    assert "Invoice 1" in page and "Hello 2" not in page
    assert 'value="invoice"' in page
    unread = ui.get(f"/ui/accounts/{account_id}/mail", params={"unread": "1"}).text
    assert "Hello 0" in unread and "Hello 2" not in unread


def test_a_bad_search_is_named_not_run(ui: TestClient) -> None:
    page = ui.get("/ui/mail", params={"after": "someday"})
    assert page.status_code == 200
    assert "Search: after" in page.text


def test_paging_carries_the_query(
    ui: TestClient, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_service.web.pages.routes import mail

    monkeypatch.setattr(mail, "PAGE_SIZE", 2)
    first = ui.get(f"/ui/accounts/{account_id}/mail", params={"folder": "inbox"}).text
    assert "Hello 0" in first and "Hello 2" not in first
    assert "Newest" not in first
    older = re.search(r'href="([^"]*cursor=[^"]*)">Older', first)
    assert older is not None
    link = html.unescape(older.group(1))
    assert "folder=inbox" in link
    second = ui.get(link).text
    assert "Hello 2" in second and "Hello 0" not in second
    assert "Newest" in second


def test_folders_as_a_tree(ui: TestClient, account_id: str, services: Services) -> None:
    adapter = services.adapters.get(account_id)
    adapter.folders.append(Folder(id="projects", name="Projects"))
    adapter.folders.append(Folder(id="projects/a", name="A", parent_id="projects"))
    page = ui.get(f"/ui/accounts/{account_id}/mail").text
    assert page.index(">Inbox<") < page.index(">Projects<") < page.index(">A<")
    assert 'class="depth-1"' in page
    assert (
        ui.get(f"/ui/accounts/{account_id}/mail", params={"folder": "nope"}).status_code
        == 404
    )


def test_a_message_is_shown_as_text(
    ui: TestClient, account_id: str, services: Services
) -> None:
    adapter = services.adapters.get(account_id)
    adapter.messages[2].text_body = "<script>alert(1)</script> hi"
    page = ui.get(f"/ui/accounts/{account_id}/mail/m2").text
    assert "Hello 2" in page and "Alice &lt;alice@example.com&gt;" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt; hi" in page
    assert "<script>alert" not in page
    assert "Download original" in page


def test_an_html_only_message_is_shown_as_its_text(
    ui: TestClient, account_id: str, services: Services
) -> None:
    adapter = services.adapters.get(account_id)
    adapter.messages[3].text_body = None
    adapter.messages[
        3
    ].html_body = '<p>Dear <b>you</b></p><img src="https://tracker.example/p.gif">'
    page = ui.get(f"/ui/accounts/{account_id}/mail/m3").text
    assert "Written as HTML; shown here as text." in page
    assert "Dear you" in page
    assert "tracker.example" not in page


def test_attachments_and_the_original_are_downloads(
    ui: TestClient, account_id: str, services: Services
) -> None:
    adapter = services.adapters.get(account_id)
    adapter.messages[0].attachments.append(
        Attachment(id="att_0", filename="page.html", content_type="text/html", size=5)
    )
    adapter.attachment_data[("m0", "att_0")] = b"<b>x"
    page = ui.get(f"/ui/accounts/{account_id}/mail/m0").text
    assert "page.html" in page and "text/html" in page
    got = ui.get(f"/ui/accounts/{account_id}/mail/m0/attachments/att_0")
    assert got.content == b"<b>x"
    assert got.headers["content-type"] == "application/octet-stream"
    assert got.headers["content-disposition"].startswith("attachment;")
    raw = ui.get(f"/ui/accounts/{account_id}/mail/m0/raw")
    assert raw.headers["content-disposition"] == "attachment; filename*=UTF-8''m0.eml"


def test_a_reader_without_attachments_sees_no_download(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services,
        Grant(
            accounts=[account_id],
            allow=["list_accounts", "get_account", "list_messages", "get_message"],
        ),
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    page = app_client.get(f"/ui/accounts/{account_id}/mail/m1").text
    assert "Hello" in page or "Invoice" in page
    assert "Download original" not in page
    assert app_client.get(f"/ui/accounts/{account_id}/mail/m1/raw").status_code == 403


def test_the_account_page_links_its_mail(ui: TestClient, account_id: str) -> None:
    page = ui.get(f"/ui/accounts/{account_id}").text
    assert f'href="/ui/accounts/{account_id}/mail"' in page
    assert 'href="/ui/mail"' in page  # the sidebar
