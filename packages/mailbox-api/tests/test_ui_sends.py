"""The send audit in the configuration UI."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_api.data.models import Grant
from benethos_mailbox_api.main import Services

from .conftest import bearer_for, create_account
from .ui_helpers import post, sign_in


def _send(ui: TestClient, account_id: str, to: str) -> None:
    post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": to, "text": "private body 4711", "do": "send"},
    )


def test_the_audit_of_one_account(ui: TestClient, account_id: str) -> None:
    _send(ui, account_id, "bob@example.org")
    page = ui.get(f"/ui/accounts/{account_id}/sends").text
    assert "bob@example.org" in page and "sent" in page
    assert "test admin" in page or "admin key" in page
    assert "private body 4711" not in page  # never the content
    account = ui.get(f"/ui/accounts/{account_id}").text
    assert f'href="/ui/accounts/{account_id}/sends"' in account


def test_a_denied_send_is_in_the_audit(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(
        services,
        Grant(
            accounts=[account_id],
            allow=["mail.read", "send", "audit"],
            recipients=["*@example.org"],
        ),
    )
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    _send(app_client, account_id, "eve@elsewhere.example")
    page = app_client.get(f"/ui/accounts/{account_id}/sends").text
    assert "eve@elsewhere.example" in page and "denied" in page
    assert "recipient_not_allowed" in page
    assert "limited" in page  # its own name, though it may not list users


def test_every_account_together(
    ui: TestClient, services: Services, account_id: str
) -> None:
    other = create_account(services.accounts, "memory", "two@example.com").id
    _send(ui, account_id, "bob@example.org")
    _send(ui, other, "carol@example.org")
    page = ui.get("/ui/sends").text
    assert page.index("carol@example.org") < page.index("bob@example.org")
    assert "me@example.com" in page and "two@example.com" in page


def test_paging(
    ui: TestClient, account_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from benethos_mailbox_api.web.pages.routes import sends

    monkeypatch.setattr(sends, "PAGE_SIZE", 1)
    _send(ui, account_id, "first@example.org")
    _send(ui, account_id, "second@example.org")
    page = ui.get(f"/ui/accounts/{account_id}/sends").text
    assert "second@example.org" in page and "first@example.org" not in page
    older = page.split('href="')[-1].split('"')[0].replace("&amp;", "&")
    assert "cursor=" in older
    assert "first@example.org" in ui.get(older).text


def test_no_audit_without_the_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    headers = bearer_for(services, Grant(accounts=[account_id], allow=["mail.read"]))
    sign_in(app_client, headers["Authorization"].removeprefix("Bearer "))
    assert app_client.get(f"/ui/accounts/{account_id}/sends").status_code == 403
    assert "Nothing sent yet" in app_client.get("/ui/sends").text
