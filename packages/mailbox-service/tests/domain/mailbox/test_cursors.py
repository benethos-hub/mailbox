"""The cursors of the mail lists carry an HMAC of the service: one made up
or changed is refused (review 2026-11-17, finding 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import (
    Folder,
    FolderRole,
    Message,
    Page,
    ProviderType,
)
from benethos_mailbox_service.data.providers import CredentialReader, ProviderSettings
from benethos_mailbox_service.data.providers.memory import MemoryProvider
from benethos_mailbox_service.domain.mailbox.cursors import Cursors
from benethos_mailbox_service.errors import BadRequestError

from ...conftest import ADMIN, admin_bearer, create_account
from ...imap_fake import FakeMailBox, make_message

START = datetime(2026, 9, 1, tzinfo=UTC)
FOLDERS = [
    Folder(id="inbox", name="Inbox", role=FolderRole.INBOX),
    Folder(id="drafts", name="Drafts", role=FolderRole.DRAFTS),
    Folder(id="all", name="All Mail", role=FolderRole.ALL),
]


def _mail(n: int, folder: str) -> Message:
    keywords = ["$draft"] if folder == "drafts" else []
    return Message(
        id=f"{folder}{n}",
        folder_ids=[folder],
        subject=f"{folder} {n}",
        date=START + timedelta(hours=n),
        keywords=keywords,
    )


def test_a_cursor_comes_back_as_it_went() -> None:
    cursors = Cursors()
    sealed = cursors.seal("m_abc")
    assert sealed is not None and sealed.startswith("m_abc.")
    assert cursors.open(sealed) == "m_abc"
    assert cursors.seal(None) is None and cursors.open(None) is None
    page = cursors.sealed(Page[Message](items=[], next_cursor="m_abc"))
    assert page.next_cursor == sealed


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s[:-1] + ("0" if s[-1] != "0" else "1"),  # the HMAC
        lambda s: "x" + s,  # the cursor
        lambda s: s.rpartition(".")[0],  # without the HMAC
        lambda s: s + "ü",  # beyond ASCII
        lambda s: "." + s.rpartition(".")[2],  # the HMAC alone
    ],
)
def test_a_cursor_made_up_or_changed_is_refused(change: object) -> None:
    cursors = Cursors()
    sealed = cursors.seal("m_abc")
    assert sealed is not None
    with pytest.raises(BadRequestError, match="invalid cursor"):
        cursors.open(change(sealed))  # type: ignore[operator]


def test_a_cursor_of_another_start_is_refused() -> None:
    sealed = Cursors().seal("m_abc")
    with pytest.raises(BadRequestError, match="invalid cursor"):
        Cursors().open(sealed)


@pytest.fixture
def lists() -> tuple[TestClient, str]:
    messages = [_mail(n, "inbox") for n in range(3)]
    messages += [_mail(n, "drafts") for n in range(3)]

    def factory(
        kind: ProviderType, settings: ProviderSettings, credentials: CredentialReader
    ) -> MemoryProvider:
        return MemoryProvider(folders=FOLDERS, messages=messages)

    settings = Settings(storage="memory")
    services = build_services(settings, provider_factory=factory)
    account = create_account(services.accounts, ProviderType.MEMORY, "a@example.com")
    app = TestClient(create_app(settings, services), headers=admin_bearer(services))
    return app, account.id


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/v1/accounts/{id}/messages", {"folder": "inbox"}),
        ("/v1/accounts/{id}/drafts", {}),
        ("/v1/messages", {"folder": "all"}),
    ],
)
def test_every_list_refuses_a_changed_cursor(
    lists: tuple[TestClient, str], path: str, params: dict[str, str]
) -> None:
    app, account_id = lists
    url = path.format(id=account_id)
    first = app.get(url, params={**params, "limit": 1})
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor is not None
    assert (
        app.get(url, params={**params, "limit": 1, "cursor": cursor}).status_code == 200
    )
    changed = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    refused = app.get(url, params={**params, "limit": 1, "cursor": changed})
    assert refused.status_code == 400
    assert refused.json()["error"] == {
        "code": "bad_request",
        "message": "invalid cursor",
    }


async def test_the_threads_refuse_an_unsealed_cursor(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    """The threads of an IMAP folder, which keeps them: the memory
    provider keeps none."""
    for uid, day in ((101, 1), (102, 2)):
        imap_server.add(
            "INBOX", uid, make_message(f"Mail {day}", date=START + timedelta(days=day))
        )
    await imap_services.sync.sync_account(imap_account_id)
    mailbox = imap_services.mailbox
    first = await mailbox.list_threads(
        ADMIN, imap_account_id, folder_id="inbox", limit=1, cursor=None
    )
    cursor = first.next_cursor
    assert cursor is not None
    await mailbox.list_threads(
        ADMIN, imap_account_id, folder_id="inbox", limit=1, cursor=cursor
    )
    # The cursor of the list itself, without the seal: one a caller can make.
    unsealed = cursor.rpartition(".")[0] or cursor
    with pytest.raises(BadRequestError, match="invalid cursor"):
        await mailbox.list_threads(
            ADMIN, imap_account_id, folder_id="inbox", limit=1, cursor=unsealed
        )
