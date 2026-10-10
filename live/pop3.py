"""Live check of the POP3 adapter against the test mail server of our own
(containers/test-mail-server/, Stalwart), never against another server.

    uv run python live/pop3.py

Both accounts of the test server connect over POP3, with SMTP for sending,
in a service in this process. The first sends one mail to the second.
The second lists it, reads it, finds it in the change feed after a sync,
deletes it for good, and the next sync reports it gone. What POP3 cannot
do answers 501. A mail of an earlier run that is left over is deleted.

The accounts come from the file ``LIVE_TEST_SERVER_ACCOUNTS`` in
``live/.env`` names. The server's test CA is trusted through
``SSL_CERT_FILE`` for this process alone.
"""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Callable
from typing import Any

import anyio
from checks.accounts import read_env, test_server_accounts
from checks.admin import admin_token
from checks.run import Run, polled
from checks.service import mailbox_of
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_client import MessageSummary, SyncMailboxClient
from benethos_mailbox_service.assembly import build_services, create_app
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.data.models import ProviderType
from benethos_mailbox_service.data.providers import build_provider
from benethos_mailbox_service.data.secrets import cipher, encode_recovery

HOST = "127.0.0.1"
POP3_TLS, POP3_STARTTLS, SMTP_TLS = 30995, 30110, 30465
TITLE = "pop3 live check"


def settings(account: dict[str, str]) -> dict[str, Any]:
    return {
        "host": HOST,
        "port": POP3_TLS,
        "security": "tls",
        "username": account["username"],
        "smtp_host": HOST,
        "smtp_port": SMTP_TLS,
        "smtp_security": "tls",
    }


def start_service() -> tuple[Any, TestClient]:
    """A service of its own in memory, and a client with an admin's token."""
    service_settings = Settings(
        storage="memory",
        key_provider="env",
        master_key=SecretStr(encode_recovery(cipher.new_key())),
        sync_interval=0,
        discovery_internal_hosts=[HOST],
    )
    services = build_services(service_settings)
    services.vault.initialize()
    client = TestClient(
        create_app(service_settings, services),
        headers={"Authorization": f"Bearer {admin_token(services)}"},
    )
    return services, client


def connect(
    run: Run, client: TestClient, accounts: tuple[dict[str, str], ...]
) -> list[str] | None:
    """Each account connected over POP3 with TLS, its id. None when one
    does not connect."""
    ids = []
    for account in accounts:
        created = client.post(
            "/v1/accounts",
            json={
                "provider": "pop3",
                "email": account["email"],
                "settings": settings(account),
                "credentials": {"password": account["password"]},
            },
        )
        if not run.check(
            "a POP3 account connects over TLS",
            created.status_code == 201,
            str(created.status_code),
        ):
            return None
        ids.append(created.json()["id"])
    return ids


def mine(mailbox: SyncMailboxClient, account_id: str) -> list[MessageSummary]:
    """The mails of this check in the account."""
    items = mailbox.list_messages(account_id, limit=50).items
    return [m for m in items if (m.subject or "").startswith(TITLE)]


def check_inbox(run: Run, client: TestClient, receiver_id: str) -> None:
    """Mails of an earlier run deleted, then what the account can do."""
    mailbox = mailbox_of(client)
    leftovers = mine(mailbox, receiver_id)
    for old in leftovers:
        mailbox.delete_message(receiver_id, old.id, permanent=True)
    if leftovers:
        print(f"      deleted {len(leftovers)} mail(s) of an earlier run")
    base = f"/v1/accounts/{receiver_id}"
    account = client.get(base).json()
    run.check(
        "the account names what it can do",
        account["capabilities"] == ["send"],
        str(account["capabilities"]),
    )
    run.check(
        "its one folder is the inbox",
        [f["role"] for f in client.get(f"{base}/folders").json()] == ["inbox"],
    )


def send_one(
    run: Run, client: TestClient, ids: list[str], receiver: dict[str, str]
) -> str | None:
    """One mail from the first account to the second, its id there once
    it arrived."""
    sender_id, receiver_id = ids
    title = f"{TITLE} {secrets.token_hex(4)}"
    sent = client.post(
        f"/v1/accounts/{sender_id}/send",
        json={
            "to": [{"email": receiver["email"]}],
            "subject": title,
            "text": "Sent by live/pop3.py between the test accounts.",
        },
    )
    run.check(
        "the first account sends over SMTP",
        sent.status_code == 200,
        str(sent.status_code),
    )
    mailbox = mailbox_of(client)
    arrived = polled(
        lambda: [m for m in mine(mailbox, receiver_id) if m.subject == title],
        tries=10,
        pause=2.0,
    )
    if not run.check("the mail arrives in the second account", bool(arrived)):
        return None
    return arrived[0].id if arrived else None


def check_handling(
    run: Run,
    sync: Callable[[], None],
    client: TestClient,
    base: str,
    message_id: str,
    since: str,
) -> None:
    """Read, reported, refused where POP3 cannot, deleted for good and
    reported deleted."""
    url = f"{base}/messages/{message_id}"
    message = client.get(url).json()
    run.check(
        "it reads the whole mail",
        "live/pop3.py" in (message.get("text_body") or ""),
    )
    sync()
    changes = client.get(f"{base}/changes", params={"since": since}).json()
    run.check(
        "the sync reports it in the change feed",
        ("message.created", message_id)
        in [(c["type"], c["id"]) for c in changes["changes"]],
    )
    for name, answer in [
        ("starring", client.patch(url, json={"starred": True})),
        ("the trash", client.delete(url)),
        ("a search", client.get(f"{base}/messages", params={"unread": "true"})),
        ("a new folder", client.post(f"{base}/folders", json={"name": "Archive"})),
    ]:
        run.check(
            f"{name} answers 501", answer.status_code == 501, str(answer.status_code)
        )
    gone = client.delete(url, params={"permanent": "true"})
    run.check("deleting for good works", gone.status_code == 204, str(gone.status_code))
    receiver_id = base.rsplit("/", 1)[1]
    run.check(
        "it is gone from the mailbox",
        not [m for m in mine(mailbox_of(client), receiver_id) if m.id == message_id],
    )
    sync()
    later = client.get(f"{base}/changes", params={"since": changes["state"]}).json()
    run.check(
        "the change feed reports it deleted",
        ("message.deleted", message_id)
        in [(c["type"], c["id"]) for c in later["changes"]],
    )


def check_starttls(run: Run, receiver: dict[str, str]) -> None:
    async def starttls() -> None:
        adapter = build_provider(
            ProviderType.POP3,
            {**settings(receiver), "port": POP3_STARTTLS, "security": "starttls"},
            lambda _field: SecretStr(receiver["password"]),
        )
        await adapter.verify()
        await adapter.close()

    try:
        anyio.run(starttls)
        run.check("STARTTLS on 30110 logs in too", True)
    except Exception as exc:  # any failure is the answer
        run.check("STARTTLS on 30110 logs in too", False, type(exc).__name__)


def check(
    run: Run,
    services: Any,
    client: TestClient,
    ids: list[str],
    receiver: dict[str, str],
) -> bool:
    """The test mail through the receiver's account. False when it did not
    arrive."""
    receiver_id = ids[1]
    base = f"/v1/accounts/{receiver_id}"
    check_inbox(run, client, receiver_id)

    def sync() -> None:
        anyio.run(services.sync.sync_account, receiver_id)

    sync()
    since = client.get(f"{base}/changes").json()["state"]
    message_id = send_one(run, client, ids, receiver)
    if message_id is None:
        return False
    check_handling(run, sync, client, base, message_id, since)
    return True


def main() -> int:
    env = read_env()
    folder, test_accounts = test_server_accounts(env)
    sender, receiver = test_accounts[:2]
    os.environ["SSL_CERT_FILE"] = str(folder / "tls" / "ca.pem")
    run = Run()
    services, client = start_service()
    ids = connect(run, client, (sender, receiver))
    if ids is not None and check(run, services, client, ids, receiver):
        check_starttls(run, receiver)
    services.close()
    return run.finish()


if __name__ == "__main__":
    sys.exit(main())
