"""What the accounts list and the mail pages offer in their rows and
headers (docs/UI.md 4.1, 4.4): the account page's links per row, the
batch bar of a mail list, and the actions of a message."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Folder, Grant

from ...conftest import browser_user, memory_of
from ...ui_helpers import post, sign_in


def test_each_account_row_has_mail_and_sends(ui: TestClient, account_id: str) -> None:
    page = ui.get("/ui/accounts").text
    assert 'aria-label="Mail of me@example.com"' in page
    assert f'href="/ui/accounts/{account_id}/mail"' in page
    assert 'aria-label="Sends of me@example.com"' in page
    # Sends is not plain as an icon: its word comes back on a touch screen.
    assert '<span class="word">Sends</span>' in page
    # Verify stays on the account page.
    assert "/verify" not in page


def test_a_row_offers_only_what_the_caller_may(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services, Grant(accounts=[account_id], allow=["accounts.read", "mail.read"])
        ),
    )
    page = app_client.get("/ui/accounts").text
    assert 'aria-label="Mail of me@example.com"' in page
    assert 'aria-label="Sends of me@example.com"' not in page


def test_the_batch_bar_asks_a_folder_only_to_move(
    ui: TestClient, account_id: str
) -> None:
    page = ui.get(f"/ui/accounts/{account_id}/mail").text
    assert 'data-show-for="f-batch-action:move"' in page
    assert 'data-tick-all="ids" data-batch="batch"' in page


def test_the_message_header_holds_its_actions(
    ui: TestClient, services: Services, account_id: str
) -> None:
    memory_of(services, account_id).folders.append(Folder(id="old", name="Old"))
    page = ui.get(f"/ui/accounts/{account_id}/mail/m1").text
    header = page[page.index('<header class="topbar">') : page.index("</header>")]
    for label in (
        "Reply to all",
        "Forward",
        "Mark read",
        "Star",
        "Move",
        "Move to the trash",
        "Delete for good",
    ):
        assert f'title="{label}"' in header, label
    assert "</svg> Reply</a>" in header
    # Move asks for the folder in a dialog, the keywords have a card.
    assert '<dialog class="ask form-dialog" id="move-message"' in page
    assert "<h2>Keywords</h2>" in page
    moved = post(ui, f"/ui/accounts/{account_id}/mail/m1/move", {"folder": "old"})
    assert moved.status_code == 200


def test_a_reader_sees_no_actions_on_a_message(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    page = app_client.get(f"/ui/accounts/{account_id}/mail/m1").text
    header = page[page.index('<header class="topbar">') : page.index("</header>")]
    assert 'title="Star"' not in header and "Reply" not in header
    assert 'id="move-message"' not in page
