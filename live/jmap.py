"""Live check of the JMAP adapter against the test mail server of our own
(containers/test-mail-server/, Stalwart), never against another server.

    uv run python live/jmap.py

A service of its own runs as a process, with SQLite in a temporary folder.
Both accounts of the test server connect over JMAP with their passwords,
then the service starts again, so its worker takes them up at once. It
polls only every ten minutes: what it reports in between came through the
server's push. Then:

1. the first sends one mail to the second through JMAP, and keeps a read
   copy in its sent folder,
2. the push wakes the worker, and the change feed of the second names the
   mail as created,
3. the second reads it, marks it read and starred with a keyword, puts it
   in a new folder as well as the inbox and back, renames and deletes that
   folder, and the change feed names the mail as updated,
4. a reply draft is stored, replaced and deleted,
5. the mail goes to the trash and then for good, and the change feed
   names it as deleted. The sent copy is deleted for good as well.

A mail of an earlier run that is left over is deleted. The accounts come
from the file ``LIVE_TEST_SERVER_ACCOUNTS`` in ``live/.env`` names. The
server's test CA is trusted through ``SSL_CERT_FILE``, for the service's
process alone.
"""

from __future__ import annotations

import json
import secrets
import shutil
import sys
import tempfile
from typing import Any

import httpx
from _common import (
    Run,
    bootstrap,
    free_port,
    messages_with_subject,
    polled,
    read_env,
    service_env,
    start_service,
    stop,
    test_server_accounts,
)

HOST = "127.0.0.1"
JMAP_PORT = 30443
TITLE = "jmap live check"
# Long enough that only a push brings a change in time.
INTERVAL = 600
CAPABILITIES = {
    "send",
    "drafts",
    "flags",
    "folders",
    "search",
    "labels",
    "push",
    "delta",
    "stable_ids",
}


def settings(account: dict[str, str]) -> dict[str, Any]:
    return {"host": HOST, "port": JMAP_PORT, "username": account["username"]}


def main() -> int:
    env = read_env()
    folder, test_accounts = test_server_accounts(env)
    sender, receiver = test_accounts[:2]
    run = Run()

    data_dir = tempfile.mkdtemp(prefix="mailbox-jmap-")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    service = {
        **service_env(data_dir, port),
        "SSL_CERT_FILE": str(folder / "tls" / "ca.pem"),
        "MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS": json.dumps([HOST]),
        "MAILBOX_SERVICE_SYNC_INTERVAL": str(INTERVAL),
        "MAILBOX_SERVICE_SYNC_IDLE": "true",
    }
    process = start_service(service, url)
    try:
        admin = bootstrap(service, url)
        headers = {"Authorization": f"Bearer {admin.token}"}
        with httpx.Client(base_url=url, headers=headers, timeout=60) as client:
            ids = connect(run, client, sender, receiver)
        if ids is None:
            return run.finish()
        stop(process)
        process = start_service(service, url, init_keys=False)
        with httpx.Client(base_url=url, headers=headers, timeout=60) as client:
            checks(run, client, ids, receiver)
    finally:
        stop(process)
        shutil.rmtree(data_dir, ignore_errors=True)
    return run.finish()


def connect(
    run: Run, client: httpx.Client, sender: dict[str, str], receiver: dict[str, str]
) -> tuple[str, str] | None:
    """Both accounts in the service, their ids, None if one did not connect."""
    ids = []
    for account in (sender, receiver):
        created = client.post(
            "/v1/accounts",
            json={
                "provider": "jmap",
                "email": account["email"],
                "settings": settings(account),
                "credentials": {"password": account["password"]},
            },
        )
        if not run.check(
            "a JMAP account connects with its password",
            created.status_code == 201,
            str(created.status_code),
        ):
            return None
        ids.append(created.json()["id"])
    return ids[0], ids[1]


def checks(
    run: Run, client: httpx.Client, ids: tuple[str, str], receiver: dict[str, str]
) -> None:
    sender_id, receiver_id = ids
    base = f"/v1/accounts/{receiver_id}"
    offered = set(client.get(base).json()["capabilities"])
    run.check(
        "the account names what it can do",
        CAPABILITIES <= offered,
        ", ".join(sorted(CAPABILITIES - offered)),
    )

    for account_id in ids:
        clean_up(client, account_id)

    def ready() -> bool:
        accounts = {a["id"]: a for a in client.get("/v1/status").json()["accounts"]}
        found = accounts.get(receiver_id) or {}
        return bool(found.get("last_sync_at") and found.get("watching"))

    if not run.check(
        "the worker synced it and waits for a push",
        bool(polled(ready, tries=30, pause=1.0)),
    ):
        return
    since = client.get(f"{base}/changes").json()["state"]

    title = f"{TITLE} {secrets.token_hex(4)}"
    sent = client.post(
        f"/v1/accounts/{sender_id}/send",
        json={
            "to": [{"email": receiver["email"]}],
            "subject": title,
            "text": "Sent by live/jmap.py between the test accounts.",
        },
    )
    run.check("the first account sends through JMAP", sent.status_code == 200)
    copies = messages_with_subject(client, sender_id, title, folder="sent")
    run.check(
        "a read copy is in its sent folder",
        len(copies) == 1 and not copies[0]["unread"],
        str(len(copies)),
    )

    arrived = messages_with_subject(client, receiver_id, title, folder="inbox")
    if not run.check("the mail arrives in the second account", bool(arrived)):
        return
    message_id = arrived[0]["id"]
    url = f"{base}/messages/{message_id}"

    def named(kind: str, after: str) -> bool:
        changes = client.get(f"{base}/changes", params={"since": after}).json()
        return (kind, message_id) in [(c["type"], c["id"]) for c in changes["changes"]]

    run.check(
        "the push brings it into the change feed",
        bool(polled(lambda: named("message.created", since), tries=30, pause=1.0)),
    )
    message = client.get(url).json()
    run.check(
        "it reads the whole mail",
        "live/jmap.py" in (message.get("text_body") or ""),
    )

    mark = client.get(f"{base}/changes").json()["state"]
    flagged = client.patch(
        url, json={"unread": False, "starred": True, "keywords": ["live"]}
    ).json()
    run.check(
        "read, starred, with a keyword",
        not flagged.get("unread")
        and flagged.get("starred")
        and flagged.get("keywords") == ["live"],
    )
    folders_url = f"{base}/folders"
    name = f"{TITLE} {secrets.token_hex(3)}"
    made = client.post(folders_url, json={"name": name})
    folder_id = made.json().get("id", "?")
    run.check("a new folder", made.status_code == 201, str(made.status_code))
    both = client.patch(url, json={"folder_ids": ["inbox", folder_id]}).json()
    run.check(
        "in the inbox and the new folder at once, the id stays",
        both.get("id") == message_id and len(both.get("folder_ids", [])) == 2,
    )
    back = client.patch(url, json={"folder_ids": ["inbox"]}).json()
    run.check("back in the inbox alone", len(back.get("folder_ids", [])) == 1)
    renamed = client.patch(f"{folders_url}/{folder_id}", json={"name": f"{name} 2"})
    removed = client.delete(f"{folders_url}/{folder_id}")
    run.check(
        "the folder renamed and deleted",
        renamed.status_code == 200 and removed.status_code == 204,
        f"{renamed.status_code} {removed.status_code}",
    )
    run.check(
        "the change feed names the changes",
        bool(polled(lambda: named("message.updated", mark), tries=30, pause=1.0)),
    )

    drafts = f"{base}/drafts"
    draft = client.post(
        drafts,
        json={
            "reference": {"message_id": message_id, "action": "reply"},
            "text": "Draft of live/jmap.py, never sent.",
        },
    )
    draft_id = draft.json().get("id", "?")
    replaced = client.put(
        f"{drafts}/{draft_id}",
        json={
            "reference": {"message_id": message_id, "action": "reply"},
            "text": "Draft of live/jmap.py, replaced, never sent.",
        },
    )
    # JMAP keeps a message as it was stored: the new draft has a new id.
    current = replaced.json().get("id", "?")
    listed = [d["id"] for d in client.get(drafts).json().get("items", [])]
    deleted = client.delete(f"{drafts}/{current}")
    run.check(
        "a draft stored, replaced, listed and deleted",
        draft.status_code == 201
        and replaced.status_code == 200
        and listed == [current]
        and deleted.status_code == 204,
        f"{draft.status_code} {replaced.status_code} {deleted.status_code}",
    )

    mark = client.get(f"{base}/changes").json()["state"]
    trashed = client.delete(url)
    again = client.delete(url)
    gone = client.delete(url, params={"permanent": True})
    run.check(
        "into the trash, once, then for good",
        trashed.status_code in (200, 204)
        and again.status_code == 409
        and gone.status_code == 204
        and client.get(url).status_code == 404,
        f"{trashed.status_code} {again.status_code} {gone.status_code}",
    )
    run.check(
        "the change feed names it deleted",
        bool(polled(lambda: named("message.deleted", mark), tries=30, pause=1.0)),
    )
    for copy in copies:
        client.delete(
            f"/v1/accounts/{sender_id}/messages/{copy['id']}",
            params={"permanent": True},
        )


def clean_up(client: httpx.Client, account_id: str) -> None:
    """Mails and drafts of an earlier run, in any folder, deleted for good,
    and its folders where they are empty."""
    base = f"/v1/accounts/{account_id}"
    page = client.get(f"{base}/messages", params={"subject": TITLE, "limit": 50}).json()
    old = [m for m in page.get("items", []) if TITLE in (m.get("subject") or "")]
    for message in old:
        client.delete(f"{base}/messages/{message['id']}", params={"permanent": True})
    folders = [
        f
        for f in client.get(f"{base}/folders").json()
        if f["name"].startswith(TITLE) and not f.get("total")
    ]
    for folder in folders:
        client.delete(f"{base}/folders/{folder['id']}")
    if old or folders:
        print(
            f"      deleted {len(old)} mail(s) and {len(folders)} folder(s) "
            "of an earlier run"
        )


if __name__ == "__main__":
    sys.exit(main())
