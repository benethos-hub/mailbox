"""Sharing an attachment as a link (CONCEPT 6.3): who may, what the link
says, where it points, how long it holds."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from benethos_mailbox_common.values import secret
from benethos_mailbox_service.config import Settings, load_settings
from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.storage import InMemoryLinkRepository

from ...conftest import ADMIN
from .links_helpers import PDF, linked


def test_a_link_has_a_secret_of_128_characters_kept_as_its_digest() -> None:
    link = linked()
    plain = link.secret()
    assert len(plain) == 128
    store = link.services.repositories.links
    assert isinstance(store, InMemoryLinkRepository)
    stored = store.find(secret.digest(plain))
    assert stored is not None
    assert plain not in repr(stored)
    assert stored.token_id == link.token_id


def test_sharing_needs_share_attachment() -> None:
    answer = linked("mail.read").share()
    assert answer.status_code == 403
    assert "share_attachment" in answer.json()["error"]["message"]


def test_sharing_needs_get_attachment_as_well() -> None:
    answer = linked("mail.share").share()
    assert answer.status_code == 403
    assert "get_attachment" in answer.json()["error"]["message"]


def test_with_both_rights_the_link_names_what_it_hands_out() -> None:
    link = linked()
    answer = link.share()
    assert answer.status_code == 201
    body = answer.json()
    assert body["content_type"] == "application/pdf"
    assert body["size"] == len(PDF)
    assert body["filename"] == "Report 7.pdf"
    expected = link.clock.now + timedelta(seconds=120)
    assert body["expires_at"] == expected.isoformat().replace("+00:00", "Z")


def test_a_grant_with_folders_keeps_the_link_to_them() -> None:
    link = linked()
    link.grant(
        Grant(
            accounts=[link.account_id],
            allow=["mail.read", "mail.share"],
            folders=["Archive"],
        )
    )
    assert link.share().status_code == 404
    link.grant(
        Grant(
            accounts=[link.account_id],
            allow=["mail.read", "mail.share"],
            folders=["inbox"],
        )
    )
    assert link.share().status_code == 201


def test_an_attachment_the_message_lacks_answers_404() -> None:
    link = linked()
    answer = link.client.post(
        link.share_url(attachment_id="att_9"), headers=link.bearer
    )
    assert answer.status_code == 404


def test_an_account_outside_the_grants_answers_404() -> None:
    link = linked()
    other = link.services.users.create_user(ADMIN, "other", [], [])
    plain = link.services.auth.issue_token(other.id, "t").plain
    answer = link.client.post(
        link.share_url(), headers={"Authorization": f"Bearer {plain}"}
    )
    assert answer.status_code == 404


def test_the_url_is_at_the_public_address() -> None:
    link = linked(public_url="https://mail.example.org/")
    url = link.share().json()["url"]
    assert url.startswith("https://mail.example.org/v1/links/")


def test_without_a_public_address_the_url_is_where_the_request_came() -> None:
    url = linked().share().json()["url"]
    assert url.startswith("http://testserver/v1/links/")


def test_a_shorter_time_holds_that_long() -> None:
    link = linked()
    body = link.share(expires_in=30).json()
    expected = link.clock.now + timedelta(seconds=30)
    assert body["expires_at"] == expected.isoformat().replace("+00:00", "Z")


def test_a_longer_time_than_the_settings_answers_400() -> None:
    answer = linked().share(expires_in=121)
    assert answer.status_code == 400
    assert "120" in answer.json()["error"]["message"]


def test_no_time_at_all_is_not_valid() -> None:
    assert linked().share(expires_in=0).status_code == 422


def test_the_share_is_audited_without_the_secret() -> None:
    link = linked()
    url = link.share().json()["url"]
    plain = url.rpartition("/")[2]
    [record] = [
        r
        for r in link.services.audit.list_activity(ADMIN, limit=50).items
        if r.activity == "mailbox.link_shared"
    ]
    assert record.user_id == link.user_id
    assert record.credential == f"token:{link.token_id}"
    assert record.record is not None and record.record.startswith("lnk_")
    assert link.account_id in record.detail and "att_0" in record.detail
    assert plain not in record.detail and "/v1/links" not in record.detail


def test_a_link_holds_120_seconds_by_default() -> None:
    assert Settings(storage="memory").link_seconds == 120


def test_a_link_of_no_seconds_stops_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAILBOX_SERVICE_LINK_SECONDS", "0")
    with pytest.raises(ValidationError):
        load_settings()


def test_an_hour_is_taken() -> None:
    link = linked(link_seconds=3600)
    assert link.share(expires_in=3600).status_code == 201
    assert link.share().json()["expires_at"].startswith("2026-09-26T13:00")
