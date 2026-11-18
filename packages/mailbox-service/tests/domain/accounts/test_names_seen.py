"""The names receiving servers wrote into an account's newest mails,
counted for whoever may change the account."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant, ProviderType
from benethos_mailbox_service.data.providers import ServerNames
from benethos_mailbox_service.domain.accounts import SeenName, takes_server_name
from benethos_mailbox_service.errors import ForbiddenError

from ...conformance_helpers import KINDS, box
from ...conftest import ADMIN, admin_bearer, bearer_for
from ...imap_fake import FakeMailBox, make_message


def entry(name: str) -> dict[str, str]:
    return {"Authentication-Results": f"{name}; dmarc=pass header.from=example.com"}


async def test_the_most_frequent_name_first(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    for uid, name in (
        (5, "mx.example.net"),
        (6, "mx.example.org"),
        (7, "MX.example.org"),
    ):
        imap_server.add(
            "INBOX", uid, make_message(f"Mail {uid}", extra_headers=entry(name))
        )
    found = await imap_services.accounts.server_names(ADMIN, imap_account_id)
    # Seven mails in the inbox, all of them read.
    assert found == [
        SeenName("mx.example.org", 2, 7),
        SeenName("mx.example.net", 1, 7),
    ]


async def test_it_needs_the_right_to_change_the_account(
    imap_services: Services, imap_account_id: str
) -> None:
    bearer = bearer_for(
        imap_services, Grant(accounts=[imap_account_id], allow=["mail.read"])
    )
    reader = imap_services.auth.authenticate(bearer["Authorization"].split()[1])
    with pytest.raises(ForbiddenError):
        await imap_services.accounts.server_names(reader, imap_account_id)


async def test_an_account_that_names_its_server_itself_reads_none(
    imap_services: Services,
) -> None:
    """The memory adapter stands for Gmail and Microsoft: it reads no names."""
    account = await imap_services.accounts.create(
        ADMIN, ProviderType.MEMORY, "m@example.com"
    )
    assert await imap_services.accounts.server_names(ADMIN, account.id) == []


@pytest.mark.parametrize("kind", [k for k in KINDS if k != "memory"])
def test_the_kinds_that_take_a_name_are_those_that_read_names(kind: str) -> None:
    """A person names the receiving server exactly where the adapter
    reads the names of the newest mails."""
    found = box(kind)
    takes = takes_server_name(found.provider)
    assert takes == isinstance(found.make(), ServerNames)


# --- through the API -------------------------------------------------------------


def api(services: Services) -> TestClient:
    return TestClient(create_app(Settings(storage="memory"), services))


async def test_the_api_lists_the_names_counted(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    for uid, name in ((5, "mx.example.org"), (6, "mx.example.org")):
        imap_server.add(
            "INBOX", uid, make_message(f"Mail {uid}", extra_headers=entry(name))
        )
    client = api(imap_services)
    url = f"/v1/accounts/{imap_account_id}/server-names"
    answer = client.get(url, headers=admin_bearer(imap_services))
    assert answer.status_code == 200
    assert answer.json() == {"items": [{"id": "mx.example.org", "count": 2, "of": 6}]}
    reader = bearer_for(
        imap_services, Grant(accounts=[imap_account_id], allow=["mail.read"])
    )
    assert client.get(url, headers=reader).status_code == 403
    gone = client.get(
        "/v1/accounts/acc_missing/server-names", headers=admin_bearer(imap_services)
    )
    assert gone.status_code == 404


async def test_the_api_lists_none_for_an_account_that_names_its_server(
    imap_services: Services,
) -> None:
    account = await imap_services.accounts.create(
        ADMIN, ProviderType.MEMORY, "m@example.com"
    )
    answer = api(imap_services).get(
        f"/v1/accounts/{account.id}/server-names",
        headers=admin_bearer(imap_services),
    )
    assert answer.json() == {"items": []}
