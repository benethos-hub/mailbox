"""The status page and the recovery key in the configuration UI."""

from __future__ import annotations

import logging
import re

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.secrets import encode_recovery
from benethos_mailbox_service.main import Services

from .conftest import UI_PASSWORD, browser_user
from .ui_helpers import post, sign_in


def test_the_status_of_accounts_and_the_worker(ui: TestClient, account_id: str) -> None:
    page = ui.get("/ui/status").text
    assert f'href="/ui/accounts/{account_id}"' in page
    assert "<h2>Sync worker</h2>" in page and "<h2>Your webhooks</h2>" in page
    assert 'href="/ui/status" class="active"' in page


def test_the_status_needs_an_account_to_list(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    assert 'href="/ui/status"' not in app_client.get("/ui").text
    assert app_client.get("/ui/status").status_code == 403


@pytest.mark.usefixtures("master_key")
def test_the_recovery_key_after_the_password(
    ui: TestClient, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    services.vault.initialize()
    assert 'href="/ui/recovery-key"' in ui.get("/ui").text
    page = ui.get("/ui/recovery-key").text
    assert 'name="password" type="password"' in page and "<code" not in page

    wrong = post(ui, "/ui/recovery-key", {"password": "not the password at all"})
    assert "the password is not right" in wrong.text and "<code" not in wrong.text

    with caplog.at_level(logging.INFO):
        shown = post(ui, "/ui/recovery-key", {"password": UI_PASSWORD})
    key = re.search(r'<code class="secret">([^<]+)</code>', shown.text)
    assert key is not None
    assert key.group(1) == encode_recovery(services.vault.master_key())
    assert "was shown the recovery key in the UI" in caplog.text
    assert key.group(1) not in caplog.text
    # Once: the next visit asks again.
    assert key.group(1) not in ui.get("/ui/recovery-key").text


@pytest.mark.usefixtures("master_key")
def test_the_recovery_key_is_for_admin_alone(
    app_client: TestClient, services: Services
) -> None:
    services.vault.initialize()
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=["*"], allow=["users.manage"])),
    )
    assert 'href="/ui/recovery-key"' not in app_client.get("/ui").text
    assert app_client.get("/ui/recovery-key").status_code == 403
    refused = post(app_client, "/ui/recovery-key", {"password": UI_PASSWORD})
    assert "missing right" in refused.text and "<code" not in refused.text
