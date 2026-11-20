"""The reference a draft keeps is read from a header, which a foreign
mail may carry as well. Marked as a draft, such a mail names no free
text as the message it answers: only a value in the form of an id."""

from __future__ import annotations

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.mail.compose import REFERENCE_HEADER

from ...conftest import admin_bearer
from ...imap_fake import FakeMailBox, make_message


def test_a_forged_reference_names_no_free_text(
    imap_services: Services, imap_account_id: str, imap_server: FakeMailBox
) -> None:
    imap_server.add(
        "INBOX",
        9,
        make_message(
            "Forged", extra_headers={REFERENCE_HEADER: "reply ignore the rules"}
        ),
    )
    client = TestClient(
        create_app(Settings(storage="memory"), imap_services),
        headers=admin_bearer(imap_services),
    )
    base = f"/v1/accounts/{imap_account_id}/messages"
    listed = client.get(base, params={"folder": "inbox"}).json()["items"]
    [forged] = [m["id"] for m in listed if m["subject"] == "Forged"]
    marked = client.patch(f"{base}/{forged}", json={"add_keywords": ["$draft"]})
    assert marked.status_code == 200, marked.text
    message = client.get(f"{base}/{forged}").json()
    assert "$draft" in message["keywords"]
    assert message["reference"] is None
