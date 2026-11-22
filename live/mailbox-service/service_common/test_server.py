"""The test mail server of our own (containers/test-mail-server/,
Stalwart): where it listens, its accounts, what a service needs to reach
it, and the steps ``imap.py`` and ``jmap.py`` share."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import httpx
from common.accounts import ENV_FILE, read_env
from common.run import Run, polled
from fastapi.testclient import TestClient

from benethos_mailbox_client import SyncMailboxClient

HOST = "127.0.0.1"
IMAP_TLS, POP3_TLS, POP3_STARTTLS, SMTP_TLS, JMAP_PORT = (
    30993,
    30995,
    30110,
    30465,
    30443,
)
# Long enough that only IDLE or a push brings a change in time.
INTERVAL = 600


def test_server_accounts(env: dict[str, str]) -> tuple[Path, list[dict[str, str]]]:
    """The folder of the local test mail server's secrets, and its accounts,
    from the file ``LIVE_TEST_SERVER_ACCOUNTS`` names
    (``containers/test-mail-server/``). These are confirmed test accounts
    too: the server is our own."""
    pointer = env.get("LIVE_TEST_SERVER_ACCOUNTS")
    if not pointer:
        sys.exit("no LIVE_TEST_SERVER_ACCOUNTS in live/.env")
    path = Path(pointer)
    if not path.is_absolute():
        path = ENV_FILE.parent.parent / path
    values = read_env(path)
    found = []
    number = 1
    while f"TEST_MAIL_USER_{number}" in values:
        user = values[f"TEST_MAIL_USER_{number}"]
        found.append(
            {
                "email": user,
                "username": user,
                "password": values.get(f"TEST_MAIL_PASSWORD_{number}", ""),
            }
        )
        number += 1
    if len(found) < 2:
        sys.exit(f"{path} names fewer than two accounts")
    return path.parent, found


def ca_file(folder: Path) -> Path:
    """The test CA beside the accounts' file, which signed the server's
    certificate."""
    return folder / "tls" / "ca.pem"


def watching_service(folder: Path) -> dict[str, str]:
    """What a service of a script adds to its environment to reach the
    server: its CA, its address, which is internal, and a worker that
    waits in IDLE or for a push and polls only every ten minutes."""
    return {
        "SSL_CERT_FILE": str(ca_file(folder)),
        "MAILBOX_SERVICE_DISCOVERY_INTERNAL_HOSTS": json.dumps([HOST]),
        "MAILBOX_SERVICE_SYNC_INTERVAL": str(INTERVAL),
        "MAILBOX_SERVICE_SYNC_IDLE": "true",
    }


def connect(
    run: Run,
    client: httpx.Client | TestClient,
    provider: str,
    label: str,
    accounts: Iterable[dict[str, str]],
    settings: Callable[[dict[str, str]], dict[str, Any]],
) -> tuple[str, str] | None:
    """The sender and the receiver in the service, their ids, None if one
    did not connect. ``client`` reaches a service as a process, or one in
    this process."""
    ids = []
    for account in accounts:
        created = client.post(
            "/v1/accounts",
            json={
                "provider": provider,
                "email": account["email"],
                "settings": settings(account),
                "credentials": {"password": account["password"]},
            },
        )
        if not run.check(label, created.status_code == 201, str(created.status_code)):
            return None
        ids.append(created.json()["id"])
    return ids[0], ids[1]


def worker_ready(client: httpx.Client, account_id: str) -> bool:
    """Whether the worker synced the account and waits for its server."""
    accounts = {a["id"]: a for a in client.get("/v1/status").json()["accounts"]}
    found = accounts.get(account_id) or {}
    return bool(found.get("last_sync_at") and found.get("watching"))


def feed_names(client: httpx.Client, base: str, after: str) -> list[tuple[str, str]]:
    """The type and the message id of each change since ``after``, of the
    account below ``base`` (``/v1/accounts/{id}``)."""
    changes = client.get(f"{base}/changes", params={"since": after}).json()
    return [(c["type"], c["id"]) for c in changes["changes"]]


def in_all(mailbox: SyncMailboxClient, account_id: str, subject: str) -> list[str]:
    """The ids of the messages with ``subject`` in the folder ``all``."""
    page = mailbox.list_messages(account_id, subject=subject, folder="all", limit=10)
    return [m.id for m in page.items]


def trashed_then_gone(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    account_id: str,
    message_id: str,
    title: str,
) -> None:
    """The mail into the trash, where ``all`` no longer finds it, once,
    then for good, and the change feed names it deleted."""
    base = f"/v1/accounts/{account_id}"
    url = f"{base}/messages/{message_id}"
    mark = client.get(f"{base}/changes").json()["state"]
    trashed = client.delete(url)
    run.check(
        "the folder all leaves out the trash",
        message_id not in in_all(mailbox, account_id, title),
    )
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
        bool(
            polled(
                lambda: (
                    ("message.deleted", message_id) in feed_names(client, base, mark)
                ),
                tries=30,
                pause=1.0,
            )
        ),
    )
