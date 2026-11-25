"""The outbox through the API: a send put in answers `202` with its job,
a send without it is as before; the jobs listed, read and cancelled with
the rights each needs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.data.models import Grant

from ....conftest import bearer_for, memory_of
from .drafts_helpers import drafts_url

MAIL = {"to": [{"email": "bob@example.com"}], "subject": "Plan", "text": "Ready."}


def send_url(account_id: str) -> str:
    return f"/v1/accounts/{account_id}/send"


def outbox_url(account_id: str, job_id: str = "") -> str:
    return f"/v1/accounts/{account_id}/outbox" + (f"/{job_id}" if job_id else "")


def as_user(services: Services, account_id: str, *allow: str) -> dict[str, str]:
    return bearer_for(services, Grant(accounts=[account_id], allow=list(allow)))


def test_a_send_put_into_the_outbox_answers_its_job(
    client: TestClient, services: Services, account_id: str
) -> None:
    answer = client.post(send_url(account_id), json={**MAIL, "outbox": True})
    assert answer.status_code == 202
    job = answer.json()
    assert job["state"] == "queued" and job["recipients"] == ["bob@example.com"]
    assert "digest" not in job and "credential_id" not in job
    assert memory_of(services, account_id).outbox == []
    drafts = client.get(drafts_url(account_id)).json()["items"]
    assert [d["id"] for d in drafts] == [job["draft_id"]]
    assert client.get(outbox_url(account_id, job["id"])).json() == job


def test_a_send_at_puts_it_into_the_outbox(client: TestClient, account_id: str) -> None:
    later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    answer = client.post(send_url(account_id), json={**MAIL, "send_at": later})
    assert answer.status_code == 202
    assert datetime.fromisoformat(answer.json()["send_at"]) == datetime.fromisoformat(
        later
    )


def test_a_send_without_the_outbox_is_as_before(
    client: TestClient, services: Services, account_id: str
) -> None:
    answer = client.post(send_url(account_id), json=MAIL)
    assert answer.status_code == 200
    assert answer.json()["sent_copy_id"]
    assert len(memory_of(services, account_id).outbox) == 1


def test_a_draft_goes_into_the_outbox_with_a_body_only(
    client: TestClient, services: Services, account_id: str
) -> None:
    draft = client.post(drafts_url(account_id), json=MAIL).json()
    url = f"{drafts_url(account_id, draft['id'])}/send"
    queued = client.post(url, json={"outbox": True})
    assert queued.status_code == 202
    assert queued.json()["draft_id"] == draft["id"]
    other = client.post(drafts_url(account_id), json=MAIL).json()
    sent = client.post(f"{drafts_url(account_id, other['id'])}/send")
    assert sent.status_code == 200
    assert len(memory_of(services, account_id).outbox) == 1


def test_a_sender_sees_its_own_jobs_an_auditor_every_one(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    anna = as_user(services, account_id, "send")
    bert = as_user(services, account_id, "send")
    auditor = as_user(services, account_id, "audit")
    mine = app_client.post(
        send_url(account_id), json={**MAIL, "outbox": True}, headers=anna
    ).json()
    theirs = app_client.post(
        send_url(account_id), json={**MAIL, "outbox": True}, headers=bert
    ).json()

    def listed(headers: dict[str, str]) -> set[str]:
        page = app_client.get(outbox_url(account_id), headers=headers).json()
        return {job["id"] for job in page["items"]}

    assert listed(anna) == {mine["id"]}
    assert listed(auditor) == {mine["id"], theirs["id"]}
    seen = app_client.get(outbox_url(account_id, theirs["id"]), headers=anna)
    assert seen.status_code == 404
    reader = as_user(services, account_id, "mail.read")
    assert app_client.get(outbox_url(account_id), headers=reader).status_code == 403


def test_a_list_narrows_to_a_state(client: TestClient, account_id: str) -> None:
    job = client.post(send_url(account_id), json={**MAIL, "outbox": True}).json()
    client.delete(outbox_url(account_id, job["id"]))
    client.post(send_url(account_id), json={**MAIL, "outbox": True})
    page = client.get(outbox_url(account_id), params={"state": "cancelled"}).json()
    assert [j["id"] for j in page["items"]] == [job["id"]]


def test_a_sender_cancels_its_own_job_and_the_draft_stays(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    anna = as_user(services, account_id, "send", "drafts")
    job = app_client.post(
        send_url(account_id), json={**MAIL, "outbox": True}, headers=anna
    ).json()
    cancelled = app_client.delete(outbox_url(account_id, job["id"]), headers=anna)
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["last_error"] == "cancelled_by_user"
    again = app_client.delete(outbox_url(account_id, job["id"]), headers=anna)
    assert again.status_code == 409
    drafts = app_client.get(drafts_url(account_id), headers=anna).json()["items"]
    assert [d["id"] for d in drafts] == [job["draft_id"]]


def test_who_manages_the_account_cancels_any_job_an_auditor_none(
    app_client: TestClient, services: Services, account_id: str
) -> None:
    anna = as_user(services, account_id, "send")
    job = app_client.post(
        send_url(account_id), json={**MAIL, "outbox": True}, headers=anna
    ).json()
    auditor = as_user(services, account_id, "audit")
    refused = app_client.delete(outbox_url(account_id, job["id"]), headers=auditor)
    assert refused.status_code == 403
    manager = as_user(services, account_id, "accounts.manage")
    assert app_client.get(outbox_url(account_id), headers=manager).json()["items"]
    done = app_client.delete(outbox_url(account_id, job["id"]), headers=manager)
    assert done.status_code == 200 and done.json()["state"] == "cancelled"


def test_the_same_key_queues_once(client: TestClient, account_id: str) -> None:
    headers = {"Idempotency-Key": "k-1"}
    body = {**MAIL, "outbox": True}
    first = client.post(send_url(account_id), json=body, headers=headers).json()
    again = client.post(send_url(account_id), json=body, headers=headers)
    assert again.status_code == 202 and again.json()["id"] == first["id"]
    page = client.get(outbox_url(account_id)).json()
    assert len(page["items"]) == 1
