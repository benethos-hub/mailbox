"""Live check of IDLE and of an id that survives a move by another client.

    uv run python live/changes.py

Writes, on the first two test accounts in ``live/.env`` and nowhere else:

1. watches the inbox of account 1 over IDLE,
2. sends one test mail from account 2 to account 1 over SMTP,
3. checks that IDLE reported it and that the API lists it,
4. moves it, the way another mail client would, into a folder it creates,
5. checks that its id still answers, now in that folder,
6. deletes the test mail and the folder again.

Nothing else in the mailboxes is touched. The service runs in-process with
memory storage and a throwaway master key. Credentials are never printed.
"""

from __future__ import annotations

import imaplib
import re
import smtplib
import ssl
import sys
import time
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any

import anyio
from fastapi.testclient import TestClient
from pydantic import SecretStr
from smoke import ENV_FILE, Run, accounts, imap_settings, read_env

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.errors import MailboxApiError
from benethos_mailbox_api.main import build_services, create_app

IDLE_WAIT = 90.0
# How long the mail may take from SMTP to the inbox.
DELIVERY_TRIES = 10
DELIVERY_PAUSE = 3.0


def smtp_server(
    client: TestClient, env: dict[str, str], sender: dict[str, str]
) -> dict[str, Any] | None:
    """From ``LIVE_SMTP_HOST`` if set, otherwise what autodiscovery finds for
    the sender's address."""
    if "LIVE_SMTP_HOST" in env:
        return {
            "host": env["LIVE_SMTP_HOST"],
            "port": int(env.get("LIVE_SMTP_PORT", "465")),
            "security": env.get("LIVE_SMTP_SECURITY", "tls"),
        }
    found = client.post("/v1/discovery", json={"email": sender["email"]})
    for candidate in found.json().get("candidates", []):
        for server in candidate["servers"]:
            if server["protocol"] == "smtp":
                return dict(server)
    return None


def send_test_mail(
    server: dict[str, Any], sender: dict[str, str], recipient: str, subject: str
) -> None:
    """One mail, to one of the test accounts only."""
    message = EmailMessage()
    message["From"] = sender["email"]
    message["To"] = recipient
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=sender["email"].rpartition("@")[2])
    message.set_content(
        "Automatic test mail of live/changes.py in the mailbox-api repository.\n"
        "It deletes itself when the check is over.\n"
    )
    host, port = server["host"], int(server["port"])
    context = ssl.create_default_context()
    smtp: smtplib.SMTP
    if server["security"] == "tls":
        smtp = smtplib.SMTP_SSL(host, port, context=context, timeout=30)
    else:
        smtp = smtplib.SMTP(host, port, timeout=30)
        smtp.starttls(context=context)
    with smtp:
        smtp.login(sender["username"], sender["password"])
        smtp.send_message(message, from_addr=sender["email"], to_addrs=[recipient])


class OtherClient:
    """A plain imaplib connection, standing in for another mail client."""

    def __init__(self, env: dict[str, str], account: dict[str, str]) -> None:
        host = env["LIVE_IMAP_HOST"]
        port = int(env.get("LIVE_IMAP_PORT", "993"))
        context = ssl.create_default_context()
        if env.get("LIVE_IMAP_SECURITY", "tls") == "tls":
            self.conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                host, port, ssl_context=context
            )
        else:
            self.conn = imaplib.IMAP4(host, port)
            self.conn.starttls(ssl_context=context)
        self.conn.login(account["username"], account["password"])

    def folder_name(self, name: str) -> str:
        """``name`` inside the personal namespace, e.g. ``INBOX.name`` on
        servers that keep every folder below the inbox."""
        status, data = self.conn.namespace()
        match = re.match(rb'\(\("([^"]*)" (?:"([^"]*)"|NIL)\)', data[0] or b"")
        if status != "OK" or match is None:
            return name
        return match.group(1).decode() + name

    def create_folder(self, folder: str) -> None:
        status, data = self.conn.create(_quoted(folder))
        if status != "OK":
            raise RuntimeError(f"CREATE failed: {data!r}")

    def delete_folder(self, folder: str) -> bool:
        self.conn.select("INBOX")
        status, _ = self.conn.delete(_quoted(folder))
        return status == "OK"

    def uids(self, folder: str, subject: str) -> list[bytes]:
        status, _ = self.conn.select(_quoted(folder))
        if status != "OK":
            return []
        _, data = self.conn.uid("SEARCH", "SUBJECT", _quoted(subject))
        return data[0].split() if data and data[0] else []

    def move(self, uid: bytes, target: str) -> None:
        status, data = self.conn.uid("MOVE", uid.decode(), _quoted(target))
        if status != "OK":
            raise RuntimeError(f"MOVE failed: {data!r}")

    def delete_mail(self, folder: str, subject: str) -> int:
        found = self.uids(folder, subject)
        for uid in found:
            self.conn.uid("STORE", uid.decode(), "+FLAGS.SILENT", r"(\Deleted)")
        if found:
            self.conn.uid("EXPUNGE", b",".join(found).decode())
        return len(found)

    def close(self) -> None:
        try:
            self.conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def idle_while_sending(provider: Any, send: Any) -> bool:
    """Start IDLE, send once IDLE runs, and return what IDLE reported."""
    result: dict[str, bool] = {}

    async def watch() -> None:
        result["changed"] = await provider.wait_for_change(IDLE_WAIT)

    async with anyio.create_task_group() as group:
        group.start_soon(watch)
        # Login and SELECT of the IDLE connection take a moment. A mail
        # that arrives before IDLE starts would not be reported.
        await anyio.sleep(5)
        await anyio.to_thread.run_sync(send)
    return result.get("changed", False)


def find_by_subject(
    client: TestClient, account_id: str, subject: str
) -> dict[str, Any] | None:
    for _ in range(DELIVERY_TRIES):
        page = client.get(
            f"/v1/accounts/{account_id}/messages", params={"q": subject, "limit": 5}
        ).json()
        items = [m for m in page.get("items", []) if m.get("subject") == subject]
        if items:
            return items[0]
        time.sleep(DELIVERY_PAUSE)
    return None


def main() -> int:
    env = read_env(ENV_FILE)
    listed = accounts(env)
    if len(listed) < 2 or "LIVE_IMAP_HOST" not in env:
        sys.exit("needs two test accounts and LIVE_IMAP_HOST")
    receiver, sender = listed[0], listed[1]
    token = uuid.uuid4().hex[:12]
    subject = f"mailbox-api live check {token}"
    base = f"mailbox-api-live-{token}"
    folder = base

    settings = Settings(
        storage="memory",
        api_key=SecretStr("live-changes"),
        key_provider="env",
        master_key=SecretStr(encode_recovery(cipher.new_key())),
        sync_interval=0,
    )
    services = build_services(settings)
    services.vault.initialize()
    client = TestClient(
        create_app(settings, services),
        headers={"Authorization": "Bearer live-changes"},
    )
    run = Run()
    other: OtherClient | None = None
    print(f"== {receiver['email']} receives from {sender['email']}")
    try:
        created = client.post(
            "/v1/accounts",
            json={
                "provider": "imap",
                "email": receiver["email"],
                "settings": imap_settings(env, receiver, {}),
                "credentials": {"password": receiver["password"]},
            },
        )
        if not run.check("connect", created.status_code == 201):
            return 1
        account_id = created.json()["id"]
        anyio.run(services.sync.sync_account, account_id)

        smtp = smtp_server(client, env, sender)
        if not run.check(
            "an SMTP server for the sender",
            smtp is not None,
            f"{smtp['host']}:{smtp['port']} {smtp['security']}" if smtp else "",
        ):
            return 1
        assert smtp is not None

        provider = services.accounts.provider(account_id)
        try:
            changed = anyio.run(
                idle_while_sending,
                provider,
                lambda: send_test_mail(smtp, sender, receiver["email"], subject),
            )
            run.check("IDLE reports the new mail", changed)
        except MailboxApiError as exc:
            run.check("IDLE reports the new mail", False, f"{exc.code}: {exc.message}")

        found = find_by_subject(client, account_id, subject)
        if not run.check("the API lists it", found is not None):
            return 1
        assert found is not None
        message_id = found["id"]
        inbox_folder = found["folder_ids"][0]

        other = OtherClient(env, receiver)
        folder = other.folder_name(base)
        other.create_folder(folder)
        uids = other.uids("INBOX", subject)
        if not run.check("another client finds it", len(uids) == 1, f"{len(uids)}"):
            return 1
        other.move(uids[0], folder)
        print(f"      moved into {folder} by another client")

        moved = client.get(f"/v1/accounts/{account_id}/messages/{message_id}")
        folder_ids = (
            moved.json().get("folder_ids", []) if moved.status_code == 200 else []
        )
        names = {
            f["id"]: f["name"]
            for f in client.get(f"/v1/accounts/{account_id}/folders").json()
        }
        where = names.get(folder_ids[0], "?") if folder_ids else "-"
        run.check(
            "the same id finds it in the new folder",
            moved.status_code == 200 and folder_ids != [inbox_folder] and where == base,
            f"{moved.status_code}, now in {where}",
        )
        run.check(
            "the subject matches",
            moved.status_code == 200 and moved.json().get("subject") == subject,
        )
    finally:
        if other is None:
            try:
                other = OtherClient(env, receiver)
            except (imaplib.IMAP4.error, OSError) as exc:
                print(f"cleanup failed, remove '{subject}' by hand: {exc}")
        if other is not None:
            folder = other.folder_name(base)
            removed = other.delete_mail(folder, subject) + other.delete_mail(
                "INBOX", subject
            )
            gone = other.delete_folder(folder)
            print(
                f"\n== cleanup: {removed} test mail(s) deleted, "
                + ("the folder too" if gone else "no folder to delete")
            )
            other.close()
        anyio.run(services.accounts.close)
        services.close()

    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
