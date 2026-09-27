"""The webhook pages of the configuration UI."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.storage import Attempt
from benethos_mailbox_service.main import Services

from .conftest import browser_user
from .ui_helpers import post, sign_in

# The vault needs its key before the services are built.
pytestmark = pytest.mark.usefixtures("master_key")
URL = "https://hooks.example.com/mail"


@pytest.fixture
def ready(ui: TestClient, services: Services) -> TestClient:
    """The admin's browser, with a vault that can seal a secret."""
    services.vault.initialize()
    return ui


def create(ui: TestClient, **fields: str | list[str]) -> str:
    """A webhook made in the UI. The path of its page."""
    data = {"url": URL, "events": ["message.created"], "every": "1", **fields}
    answer = post(ui, "/ui/webhooks", data, follow_redirects=False)
    assert answer.status_code == 303
    location: str = answer.headers["location"]
    assert location.startswith("/ui/webhooks/whk_"), location
    return location


def test_create_shows_the_secret_once(ready: TestClient) -> None:
    form = ready.get("/ui/webhooks/new").text
    assert 'name="events" value="message.sent" checked' in form
    page = create(ready)
    shown = ready.get(page).text
    assert "Webhook created." in shown and "shown this once" in shown
    secret = re.search(r'<code class="secret">([^<]+)</code>', shown)
    assert secret is not None
    again = ready.get(page).text
    assert secret.group(1) not in again and URL in again
    assert "Nothing posted yet." in again


def test_the_list_names_the_state(
    ready: TestClient, services: Services, account_id: str
) -> None:
    page = create(ready, every="", accounts=account_id)
    webhook_id = page.rpartition("/")[2]
    listed = ready.get("/ui/webhooks").text
    assert f'href="{page}"' in listed and "me@example.com" in listed
    assert '<span class="tag ok">ok</span>' in listed
    repository = services.webhooks._repository  # type: ignore[attr-defined]
    record = repository.get(webhook_id)
    repository.update(
        webhook_id,
        record.delivery,
        last_delivery_at=None,
        last_error="the receiver answered 503",
    )
    repository.add_attempt(
        Attempt(
            webhook_id,
            "dlv_1",
            datetime(2026, 9, 27, 12, tzinfo=UTC),
            3,
            503,
            "the receiver answered 503",
        ),
        keep=20,
    )
    assert "the receiver answered 503" in ready.get("/ui/webhooks").text
    detail = ready.get(page).text
    assert "<h2>Last deliveries</h2>" in detail and ">503</span>" in detail
    # The overview names it too, with a link to it.
    assert f'href="{page}"' in ready.get("/ui").text


def test_a_webhook_needs_its_accounts(ready: TestClient) -> None:
    answer = post(ready, "/ui/webhooks", {"url": URL, "events": "message.created"})
    assert "Choose the accounts, or every account." in answer.text
    answer = post(ready, "/ui/webhooks", {"url": "ftp://x", "every": "1"})
    assert str(answer.url).endswith("/ui/webhooks/new")
    assert 'class="notice err"' in answer.text


def test_remove(ready: TestClient) -> None:
    page = create(ready)
    removed = post(ready, f"{page}/delete")
    assert "Webhook removed." in removed.text and URL not in removed.text
    assert ready.get(page).status_code == 404


def test_hidden_without_the_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    assert 'href="/ui/webhooks"' not in app_client.get("/ui").text
    assert app_client.get("/ui/webhooks").status_code == 403
    assert app_client.get("/ui/webhooks/new").status_code == 403


def test_webhooks_filter_by_url_account_and_state(
    ready: TestClient, account_id: str
) -> None:
    create(ready, url="https://a.example.com/hook")
    create(ready, url="https://b.example.com/hook", every="", accounts=account_id)
    by_url = ready.get("/ui/webhooks", params={"url": "A.EXAMPLE"}).text
    assert "a.example.com" in by_url and "b.example.com" not in by_url
    by_account = ready.get("/ui/webhooks", params={"account": account_id}).text
    # Every account includes this one.
    assert "a.example.com" in by_account and "b.example.com" in by_account
    failing = ready.get("/ui/webhooks", params={"failing": "1"}).text
    assert "No webhook matches." in failing
