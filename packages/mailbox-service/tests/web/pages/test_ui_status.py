"""The state of the service in the configuration UI: on the overview,
in the accounts list and as dots in the sidebar, since the status page
went. And the recovery key."""

from __future__ import annotations

import logging
import re

import anyio
import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import AccountStatus, Grant, ProviderType
from benethos_mailbox_service.data.secrets import encode_recovery
from benethos_mailbox_service.errors import MailboxServiceError

from ...conftest import UI_PASSWORD, browser_user, create_account
from ...pop3_fake import FakePop3Server
from ...ui_helpers import post, sign_in, signed_in


def failed_sync(services: Services, account_id: str, server: FakePop3Server) -> None:
    """The account's last sync failed: its server refused the login for now."""
    server.login_refusal = b"-ERR [SYS/TEMP] try again later"
    with pytest.raises(MailboxServiceError):
        anyio.run(services.sync.sync_account, account_id)


def test_the_overview_names_the_worker_and_no_status_page_is_left(
    ui: TestClient,
) -> None:
    page = ui.get("/ui").text
    assert "<dt>Sync worker</dt>" in page and "switched off" in page
    assert 'href="/ui/status"' not in page
    assert ui.get("/ui/status").status_code == 404


def test_the_accounts_list_says_when_each_synced(
    pop3_services: Services, pop3_account_id: str, pop3_server: FakePop3Server
) -> None:
    """A memory account, which no pass keeps, and a POP3 account."""
    create_account(pop3_services.accounts, ProviderType.MEMORY, "anna@example.com")
    ui = signed_in(pop3_services)
    page = ui.get("/ui/accounts").text
    assert "<th>Last sync</th>" in page and "not synced" in page
    failed_sync(pop3_services, pop3_account_id, pop3_server)
    failed = ui.get("/ui/accounts").text
    assert '<span class="tag bad"' in failed
    assert "the mail server refused the login for now" in failed


def test_a_dot_marks_accounts_and_webhooks_that_need_a_look(
    ui: TestClient, services: Services, account_id: str
) -> None:
    dot = '<span class="dot" role="img" aria-label="needs a look"'
    assert dot not in ui.get("/ui").text
    services.repositories.accounts.set_status(account_id, AccountStatus.NEEDS_REAUTH)
    page = ui.get("/ui").text
    accounts = page[page.index('href="/ui/accounts"') :]
    assert accounts.index(dot) < accounts.index("</a>")


def test_no_dot_for_whom_may_not_see_the_status(
    pop3_services: Services, pop3_account_id: str, pop3_server: FakePop3Server
) -> None:
    failed_sync(pop3_services, pop3_account_id, pop3_server)
    reader = signed_in(
        pop3_services, Grant(accounts=[pop3_account_id], allow=["mail.read"])
    )
    assert 'class="dot"' not in reader.get("/ui").text


@pytest.mark.usefixtures("master_key")
def test_the_recovery_key_after_the_password(
    ui: TestClient, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    services.vault.initialize()
    assert 'href="/ui/recovery-key"' in ui.get("/ui").text
    page = ui.get("/ui/recovery-key").text
    assert 'name="password" type="password"' in page and "<code" not in page
    # Without a second factor the password alone does.
    assert 'name="code"' not in page

    wrong = post(ui, "/ui/recovery-key", {"password": "not the password at all"})
    assert "the password is not right" in wrong.text and "<code" not in wrong.text

    with caplog.at_level(logging.INFO):
        shown = post(ui, "/ui/recovery-key", {"password": UI_PASSWORD})
    key = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', shown.text)
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
        *browser_user(services, service=["users.manage"]),
    )
    assert 'href="/ui/recovery-key"' not in app_client.get("/ui").text
    assert app_client.get("/ui/recovery-key").status_code == 403
    refused = post(app_client, "/ui/recovery-key", {"password": UI_PASSWORD})
    assert "missing right" in refused.text and "<code" not in refused.text
