"""Using a link to an attachment (CONCEPT 6.3): the bytes once, with the
rights of the token that made it as they are now, and one 404 for
everything else."""

from __future__ import annotations

import logging
from datetime import timedelta

import anyio
import pytest

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.data.storage import InMemoryLinkRepository, StoredLink
from benethos_mailbox_service.domain.mailbox import AttachmentLinks
from benethos_mailbox_service.errors import NotFoundError, ProviderUnavailableError

from ...conftest import ADMIN
from .links_helpers import PDF, Linked, linked

GONE = {"error": {"code": "not_found", "message": "no such link"}}


def kinds(link: Linked) -> list[str]:
    return [
        r.activity for r in link.services.audit.list_activity(ADMIN, limit=50).items
    ]


def test_a_link_hands_out_the_attachment_once() -> None:
    link = linked()
    plain = link.secret()
    answer = link.fetch(plain)
    assert answer.status_code == 200
    assert answer.content == PDF
    assert answer.headers["content-type"] == "application/pdf"
    assert answer.headers["content-length"] == str(len(PDF))
    assert "Report%207.pdf" in answer.headers["content-disposition"]
    assert answer.headers["cache-control"] == "no-store"
    again = link.fetch(plain)
    assert again.status_code == 404
    assert again.json() == GONE


def test_a_link_ends_at_its_time() -> None:
    link = linked()
    ended, kept = link.secret(), link.secret()
    link.clock.tick(seconds=119)
    assert link.fetch(kept).status_code == 200
    link.clock.tick(seconds=1)
    assert link.fetch(ended).json() == GONE


def test_a_revoked_token_ends_its_links() -> None:
    link = linked()
    plain = link.secret()
    link.services.tokens.revoke_token(ADMIN, link.user_id, link.token_id)
    assert link.fetch(plain).json() == GONE


def test_an_account_taken_from_the_grant_ends_its_links() -> None:
    link = linked()
    plain = link.secret()
    link.grant(Grant(accounts=["acc_other"], allow=["mail.read", "mail.share"]))
    assert link.fetch(plain).json() == GONE


def test_sharing_taken_away_ends_its_links() -> None:
    link = linked()
    plain = link.secret()
    link.grant(Grant(accounts=[link.account_id], allow=["mail.read"]))
    assert link.fetch(plain).json() == GONE


def test_reading_taken_away_ends_its_links() -> None:
    link = linked()
    plain = link.secret()
    link.grant(Grant(accounts=[link.account_id], allow=["mail.share"]))
    assert link.fetch(plain).json() == GONE


def test_a_folder_outside_the_grant_now_ends_its_links() -> None:
    link = linked()
    plain = link.secret()
    link.grant(
        Grant(
            accounts=[link.account_id],
            allow=["mail.read", "mail.share"],
            folders=["Archive"],
        )
    )
    assert link.fetch(plain).json() == GONE


def test_a_disabled_user_ends_its_links() -> None:
    link = linked()
    plain = link.secret()
    link.services.users.update_user(ADMIN, link.user_id, disabled=True)
    assert link.fetch(plain).json() == GONE


def test_an_unknown_secret_answers_the_same() -> None:
    link = linked()
    assert link.fetch("x" * 128).json() == GONE
    assert link.fetch("short").json() == GONE


def test_failures_lock_the_address_out_silently() -> None:
    """A wrong link counts as a wrong token. Once the address is locked,
    a valid link answers the same 404, and a wrong token 429."""
    link = linked(sign_in_failures=3)
    plain = link.secret()
    for _ in range(3):
        assert link.fetch("x" * 128).json() == GONE
    assert link.fetch(plain).json() == GONE
    wrong = link.client.get("/v1/me", headers={"Authorization": "Bearer mbx_wrong"})
    assert wrong.status_code == 429


def test_the_limit_on_requests_answers_as_a_link_does(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request there counts against its address at once, whatever it
    carries, and a refusal is the same 404. Its line names the path
    masked."""
    link = linked(rate_limit_anonymous_per_minute=2)
    plain = link.secret()
    assert link.fetch("x" * 128).json() == GONE
    with caplog.at_level(logging.WARNING):
        refused = link.client.get(
            f"/v1/links/{plain}", headers={"Authorization": "Bearer anything"}
        )
    assert refused.status_code == 404
    assert refused.json() == GONE
    assert "retry-after" not in refused.headers
    [line] = [r for r in caplog.records if r.name.endswith("http.rate_limited")]
    assert "/v1/links/\u2026" in line.getMessage()
    assert plain not in line.getMessage()


def test_a_link_lost_to_another_fetch_answers_404() -> None:
    """Two fetches at once: the one that marks the link used first wins,
    the other sees it taken after its checks."""

    class Raced(InMemoryLinkRepository):
        def find(self, secret_hash: str) -> StoredLink | None:
            found = super().find(secret_hash)
            if found is not None:
                before = found.expires_at - timedelta(seconds=1)
                assert super().redeem(found.id, before, "203.0.113.3")
            return found

    link = linked()
    raced = Raced()
    links = AttachmentLinks(
        raced,
        link.services.mailbox,
        link.services.auth,
        clock=link.clock,
        activity=link.services.activity,
    )
    access = link.services.auth.token_access(link.token_id, "203.0.113.1")
    assert access is not None
    shared = anyio.run(links.share, access, link.account_id, "m0", "att_0")

    async def fetch() -> None:
        await links.redeem(shared.secret, "203.0.113.2")

    with pytest.raises(NotFoundError):
        anyio.run(fetch)
    assert "mailbox.link_used" not in kinds(link)


def test_the_audit_names_the_share_and_the_fetch_without_the_secret() -> None:
    link = linked()
    plain = link.secret()
    link.client.get(f"/v1/links/{plain}")
    records = link.services.audit.list_activity(ADMIN, limit=50).items
    used = [r for r in records if r.activity == "mailbox.link_used"]
    shared = [r for r in records if r.activity == "mailbox.link_shared"]
    assert len(used) == 1 and len(shared) == 1
    assert used[0].record == shared[0].record
    assert used[0].user_id == link.user_id
    assert used[0].source == "testclient"
    for record in records:
        assert plain not in record.detail
        assert "/v1/links" not in record.detail


def test_a_refused_link_is_logged_and_a_secret_that_is_none_is_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    link = linked()
    plain = link.secret()
    link.fetch(plain)
    with caplog.at_level(logging.INFO):
        link.fetch(plain)
        link.fetch("y" * 128)
    refused = [r for r in caplog.records if r.name.endswith("mailbox.link_refused")]
    assert len(refused) == 1
    assert "it was used" in refused[0].getMessage()
    ours = [r for r in caplog.records if r.name.startswith("benethos_mailbox_service")]
    assert not any(plain in r.getMessage() for r in ours)


def test_the_purge_takes_the_links_used_and_ended(
    caplog: pytest.LogCaptureFixture,
) -> None:
    link = linked()
    used, ended, kept = link.secret(), link.secret(), link.secret(expires_in=60)
    link.fetch(used)
    link.clock.tick(seconds=60)
    assert ended
    store = link.services.repositories.links
    assert isinstance(store, InMemoryLinkRepository)
    with caplog.at_level(logging.INFO):
        link.services.links.purge()
    assert "purged 2 links to attachments" in caplog.text
    assert kept and store.purge(link.clock.now) == 0


def test_a_mail_server_that_fails_hands_the_link_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was fetched: the link holds again, the audit says so, and
    the address that asked counts no failure."""
    link = linked(sign_in_failures=1)
    plain = link.secret()
    adapter = link.services.adapters.get(link.account_id)
    real = adapter.get_attachment

    async def down(*args: object, **kwargs: object) -> object:
        raise ProviderUnavailableError("the mail server does not answer")

    monkeypatch.setattr(adapter, "get_attachment", down)
    assert link.fetch(plain).json() == GONE
    assert "mailbox.link_used" in kinds(link)
    assert "mailbox.link_returned" in kinds(link)
    monkeypatch.setattr(adapter, "get_attachment", real)
    answer = link.fetch(plain)
    assert answer.status_code == 200
    assert answer.content == PDF
    assert link.fetch(plain).json() == GONE
