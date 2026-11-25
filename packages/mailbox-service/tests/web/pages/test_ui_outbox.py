"""The outbox in the configuration UI: a mail and a draft put in from the
mail form, the outbox page, cancelling a send, and the audit of sends
naming it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant

from ...conftest import browser_user, memory_of
from ...ui_helpers import post, sign_in


def _queue(ui: TestClient, account_id: str, **extra: str) -> str:
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "text": "Later.", "do": "queue", **extra},
    )
    assert answer.status_code == 200, answer.text
    return answer.text


def test_a_mail_put_in_the_outbox_waits_there(
    ui: TestClient, services: Services, account_id: str
) -> None:
    page = _queue(ui, account_id)
    assert "In the outbox" in page and "bob@example.org" in page
    assert ">queued<" in page
    assert memory_of(services, account_id).outbox == []


def test_a_send_at_too_far_ahead_keeps_the_form(
    ui: TestClient, account_id: str
) -> None:
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {
            "to": "bob@example.org",
            "text": "Far.",
            "do": "queue",
            "send_at": "2099-01-01T08:00",
        },
    )
    assert answer.status_code == 400
    assert "send_at lies more than 30 days ahead" in answer.text
    assert 'value="2099-01-01T08:00"' in answer.text


def test_a_send_at_is_read_as_utc(
    ui: TestClient, services: Services, account_id: str
) -> None:
    later = datetime.now(UTC) + timedelta(days=2)
    _queue(ui, account_id, send_at=later.strftime("%Y-%m-%dT%H:%M"))
    [job] = services.mailbox.outgoing.outbox.jobs.open()
    assert job.send_at == later.replace(second=0, microsecond=0)


def test_a_send_at_that_is_no_time_keeps_the_form(
    ui: TestClient, account_id: str
) -> None:
    answer = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "text": "Kept.", "do": "queue", "send_at": "soon"},
    )
    assert answer.status_code == 400
    assert "not a date and time" in answer.text and "Kept." in answer.text


def test_a_draft_goes_into_the_outbox(ui: TestClient, account_id: str) -> None:
    saved = post(
        ui,
        f"/ui/accounts/{account_id}/compose",
        {"to": "bob@example.org", "text": "Draft.", "do": "save"},
    )
    assert "Draft saved." in saved.text
    draft_url = str(saved.url).split("/ui", 1)[1]
    queued = post(
        ui,
        f"/ui{draft_url}",
        {"to": "bob@example.org", "text": "Draft.", "do": "queue"},
    )
    assert "In the outbox" in queued.text
    drafts = ui.get(f"/ui/accounts/{account_id}/drafts").text
    assert f'href="/ui/accounts/{account_id}/outbox"' in drafts


def test_a_send_is_cancelled_and_its_draft_stays(
    ui: TestClient, services: Services, account_id: str
) -> None:
    _queue(ui, account_id)
    [job] = services.mailbox.outgoing.outbox.jobs.open()
    done = post(ui, f"/ui/accounts/{account_id}/outbox/{job.id}/cancel")
    assert "Cancelled. Its draft stays." in done.text
    assert ">cancelled<" in done.text
    again = post(ui, f"/ui/accounts/{account_id}/outbox/{job.id}/cancel")
    assert "not waiting" in again.text
    filtered = ui.get(f"/ui/accounts/{account_id}/outbox?state=queued").text
    assert "Nothing in the outbox in this state." in filtered


def test_the_outbox_is_hidden_without_the_right(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(services, Grant(accounts=[account_id], allow=["mail.read"])),
    )
    answer = app_client.get(f"/ui/accounts/{account_id}/outbox")
    assert answer.status_code == 403
    form = app_client.get(f"/ui/accounts/{account_id}/compose").text
    assert 'value="queue"' not in form


def test_a_sender_sees_its_own_send_and_may_cancel_it(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    sign_in(
        app_client,
        *browser_user(
            services, Grant(accounts=[account_id], allow=["mail.read", "send"])
        ),
    )
    form = app_client.get(f"/ui/accounts/{account_id}/compose").text
    assert 'value="queue"' in form and 'name="send_at"' in form
    page = _queue(app_client, account_id)
    assert "Cancel send" in page


def test_the_audit_of_sends_names_the_outbox(ui: TestClient, account_id: str) -> None:
    _queue(ui, account_id)
    page = ui.get(f"/ui/sends?account={account_id}&outcome=queued").text
    assert ">queued<" in page
    assert f'href="/ui/accounts/{account_id}/outbox"' in page
