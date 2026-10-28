"""Folder ids a caller made up. An id is not signed, so anyone can build
one: what it names never reaches a command of the mail server."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.common import opaque
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import Grant

from ...conftest import bearer_for
from ...imap_fake import FakeMailBox

# A name that would end SELECT and start a command of the caller's choosing.
FORGED = opaque.encode("f_", ['INBOX"\r\nZ99 DELETE "Important'])


@pytest.mark.parametrize("path", ["messages", "threads"])
def test_a_forged_folder_id_never_reaches_the_server(
    path: str, imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    grant = Grant(accounts=[imap_account_id], allow=["mail.read"])
    client = TestClient(
        create_app(Settings(storage="memory"), imap_services),
        headers=bearer_for(imap_services, grant),
    )
    answer = client.get(
        f"/v1/accounts/{imap_account_id}/{path}", params={"folder": FORGED}
    )
    assert answer.status_code == 400
    sent = [a for c in imap_server.calls for a in c[1:] if isinstance(a, str)]
    assert not [a for a in sent if "\r" in a or "\n" in a]
