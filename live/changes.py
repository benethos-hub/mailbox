"""Live check of IDLE, of changing a message, and of an id that survives
moves.

    uv run python live/changes.py [--keep]

Writes, on the first two test accounts in ``live/.env`` and nowhere else:

1. watches the inbox of account 1 over IDLE,
2. sends one test mail from account 2 to account 1 over SMTP,
3. checks that IDLE reported it and that the API lists it,
4. marks it read, starred, with a keyword, and back, through the API,
5. moves it through the API into a folder it creates: the id stays,
6. moves it back the way another mail client would: the id still answers,
7. deletes it through the API: into the trash, then for good, and the
   folder. With ``--keep`` the mail
   stays in the inbox, and a copy goes into the Sent folder of account 2,
   as a mail client would put it there, to look at in a mail client.

Nothing else in the mailboxes is touched. The service runs in-process with
memory storage and a throwaway master key. Credentials are never printed.
"""

from __future__ import annotations

import argparse
import imaplib
import re
import smtplib
import ssl
import sys
import time
import uuid
from email.message import EmailMessage
from email.utils import format_datetime, localtime, make_msgid
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
# Set and cleared again on the test mail.
LIVE_KEYWORD = "$mailbox-api-live"


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
    server: dict[str, Any],
    sender: dict[str, str],
    recipient: str,
    subject: str,
    keep: bool,
) -> bytes:
    """One mail, to one of the test accounts only. Returns what was sent."""
    message = EmailMessage()
    message["From"] = sender["email"]
    message["To"] = recipient
    message["Subject"] = subject
    # RFC 5322 requires Date. Without it mail clients show no date.
    message["Date"] = format_datetime(localtime())
    message["Message-ID"] = make_msgid(domain=sender["email"].rpartition("@")[2])
    message.set_content(
        "Automatic test mail of live/changes.py in the mailbox-api repository.\n"
        + (
            "It was kept for inspection (--keep): delete it by hand.\n"
            if keep
            else "It deletes itself when the check is over.\n"
        )
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
    return message.as_bytes()


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

    def create_folder(self, folder: str, subscribe: bool = False) -> None:
        """``subscribe`` makes mail clients such as Outlook show it: they list
        only subscribed folders."""
        status, data = self.conn.create(_quoted(folder))
        if status != "OK":
            raise RuntimeError(f"CREATE failed: {data!r}")
        if subscribe:
            self.conn.subscribe(_quoted(folder))

    def all_folders(self) -> set[str]:
        return self._names(self.conn.list())

    def subscribed_folders(self) -> set[str]:
        return self._names(self.conn.lsub())

    def _names(self, answer: tuple[str, list[Any]]) -> set[str]:
        status, data = answer
        names = set()
        for line in data if status == "OK" else []:
            if isinstance(line, bytes):
                match = re.match(rb'\([^)]*\) (?:"[^"]*"|NIL) (.+)$', line)
                if match:
                    names.add(match.group(1).decode().strip('"'))
        return names

    def sent_folder(self) -> str | None:
        return self._special_folder(b"\\sent")

    def trash_folder(self) -> str | None:
        return self._special_folder(b"\\trash")

    def _special_folder(self, flag: bytes) -> str | None:
        """The folder with this special-use flag (RFC 6154)."""
        status, data = self.conn.list()
        for line in data if status == "OK" else []:
            if not isinstance(line, bytes):
                continue
            match = re.match(rb'\(([^)]*)\) (?:"[^"]*"|NIL) (.+)$', line)
            if match and flag in match.group(1).lower():
                return match.group(2).decode().strip('"')
        return None

    def append_sent(self, folder: str, raw: bytes) -> bool:
        """What a mail client does after sending: a read copy in Sent."""
        status, _ = self.conn.append(
            _quoted(folder), r"(\Seen)", imaplib.Time2Internaldate(time.time()), raw
        )
        return status == "OK"

    def delete_folder(self, folder: str) -> bool:
        self.conn.unsubscribe(_quoted(folder))
        self.conn.select("INBOX")
        status, _ = self.conn.delete(_quoted(folder))
        return status == "OK"

    def flags(self, folder: str, subject: str) -> list[str]:
        """The flags of the one test mail, as the server keeps them."""
        found = self.uids(folder, subject)
        if len(found) != 1:
            return [f"({len(found)} mails)"]
        _, data = self.conn.uid("FETCH", found[0].decode(), "(FLAGS)")
        match = re.search(rb"FLAGS \(([^)]*)\)", data[0] if data and data[0] else b"")
        flags = match.group(1).decode().split() if match else []
        return sorted(f for f in flags if f != "\\Recent")

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


def clean_up(
    env: dict[str, str],
    receiver: dict[str, str],
    other: OtherClient | None,
    base: str,
    subject: str,
) -> None:
    """Delete the test mail wherever it is, and the test folder."""
    if other is None:
        try:
            other = OtherClient(env, receiver)
        except (imaplib.IMAP4.error, OSError) as exc:
            print(f"cleanup failed, remove '{subject}' by hand: {exc}")
            return
    folders = [other.folder_name(base), other.folder_name(base + "-renamed")]
    places = [*folders, "INBOX", other.trash_folder()]
    removed = sum(other.delete_mail(place, subject) for place in places if place)
    left = [f for f in folders if f in other.all_folders()]
    for folder in left:
        other.delete_folder(folder)
    print(
        f"\n== cleanup: {removed} test mail(s) and {len(left)} leftover "
        "folder(s) deleted"
    )
    other.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the test mail and its folder, and put a copy into the "
        "sender's Sent folder, to look at in a mail client",
    )
    keep = parser.parse_args().keep
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
        sent: list[bytes] = []
        try:
            changed = anyio.run(
                idle_while_sending,
                provider,
                lambda: sent.append(
                    send_test_mail(smtp, sender, receiver["email"], subject, keep)
                ),
            )
            run.check("IDLE reports the new mail", changed)
        except MailboxApiError as exc:
            run.check("IDLE reports the new mail", False, f"{exc.code}: {exc.message}")

        if keep and sent:
            outbox = OtherClient(env, sender)
            try:
                sent_folder = outbox.sent_folder()
                run.check(
                    "a copy in the sender's Sent folder",
                    sent_folder is not None
                    and outbox.append_sent(sent_folder, sent[0]),
                    sent_folder or "no folder flagged \\Sent",
                )
            finally:
                outbox.close()

        found = find_by_subject(client, account_id, subject)
        if not run.check("the API lists it", found is not None):
            return 1
        assert found is not None
        run.check(
            "it has a date", found.get("date") is not None, str(found.get("date"))
        )
        message_id = found["id"]
        inbox_folder = found["folder_ids"][0]

        other = OtherClient(env, receiver)
        patched = client.patch(
            f"/v1/accounts/{account_id}/messages/{message_id}",
            json={"unread": False, "starred": True, "keywords": [LIVE_KEYWORD]},
        )
        run.check(
            "PATCH marks it read, starred, with a keyword",
            patched.status_code == 200
            and patched.json().get("id") == message_id
            and patched.json().get("keywords") == [LIVE_KEYWORD],
            str(patched.status_code),
        )
        seen = other.flags("INBOX", subject)
        run.check(
            "another client sees the flags",
            {"\\Seen", "\\Flagged", LIVE_KEYWORD} <= set(seen),
            " ".join(seen),
        )
        client.patch(
            f"/v1/accounts/{account_id}/messages/{message_id}",
            json={"unread": True, "starred": False, "keywords": []},
        )
        run.check(
            "and back to unread, no star, no keyword",
            other.flags("INBOX", subject) == [],
            " ".join(other.flags("INBOX", subject)),
        )
        folders_url = f"/v1/accounts/{account_id}/folders"
        created = client.post(folders_url, json={"name": base})
        folder = other.folder_name(base)
        run.check(
            "POST creates a folder, subscribed, in the personal namespace",
            created.status_code == 201
            and created.json().get("subscribed") is True
            and folder in other.subscribed_folders(),
            f"{created.status_code}, {folder}",
        )
        names = {f["name"]: f["id"] for f in client.get(folders_url).json()}
        moved = client.patch(
            f"/v1/accounts/{account_id}/messages/{message_id}",
            json={"folder_ids": [names.get(base, "?")]},
        )
        run.check(
            "PATCH moves it, and the id stays",
            moved.status_code == 200
            and moved.json().get("id") == message_id
            and moved.json().get("folder_ids") == [names.get(base)],
            str(moved.status_code),
        )
        run.check(
            "another client finds it there, not in the inbox",
            len(other.uids(folder, subject)) == 1 and not other.uids("INBOX", subject),
        )

        uids = other.uids(folder, subject)
        if not run.check("another client moves it back", len(uids) == 1):
            return 1
        other.move(uids[0], "INBOX")
        back = client.get(f"/v1/accounts/{account_id}/messages/{message_id}")
        run.check(
            "the same id finds it in the inbox again",
            back.status_code == 200 and back.json().get("folder_ids") == [inbox_folder],
            str(back.status_code),
        )
        run.check(
            "the subject matches",
            back.status_code == 200 and back.json().get("subject") == subject,
        )

        batch = client.post(
            f"/v1/accounts/{account_id}/messages/batch",
            json={
                "action": "update",
                "ids": [message_id, "msg_does_not_exist"],
                "changes": {"starred": True},
            },
        )
        outcomes = [r["ok"] for r in batch.json().get("results", [])]
        run.check(
            "a batch answers per id",
            batch.status_code == 200
            and outcomes == [True, False]
            and "\\Flagged" in other.flags("INBOX", subject),
            f"{batch.status_code} {outcomes}",
        )

        test_folder = names.get(base, "?")
        renamed = client.patch(
            f"{folders_url}/{test_folder}", json={"name": base + "-renamed"}
        )
        new_name = other.folder_name(base + "-renamed")
        run.check(
            "PATCH renames the folder, the subscription goes along",
            renamed.status_code == 200
            and new_name in other.subscribed_folders()
            and folder not in other.subscribed_folders(),
            str(renamed.status_code),
        )
        removed = client.delete(f"{folders_url}/{renamed.json().get('id', '?')}")
        run.check(
            "DELETE removes the empty folder",
            removed.status_code == 204 and new_name not in other.all_folders(),
            str(removed.status_code),
        )

        if not keep:
            url = f"/v1/accounts/{account_id}/messages/{message_id}"
            trash = other.trash_folder()
            deleted = client.delete(url)
            run.check(
                "DELETE moves it into the trash",
                deleted.status_code == 204
                and trash is not None
                and len(other.uids(trash, subject)) == 1
                and not other.uids("INBOX", subject),
                f"{deleted.status_code}, {trash}",
            )
            again = client.delete(url)
            run.check(
                "from the trash only with permanent=true",
                again.status_code == 409,
                str(again.status_code),
            )
            gone = client.delete(url, params={"permanent": True})
            run.check(
                "DELETE permanent=true removes it for good",
                gone.status_code == 204
                and trash is not None
                and not other.uids(trash, subject)
                and client.get(url).status_code == 404,
                str(gone.status_code),
            )
    finally:
        if keep:
            if other is not None:
                other.delete_folder(other.folder_name(base))
                other.close()
            print(
                f"\n== kept: '{subject}' in the inbox of {receiver['email']} and "
                "in the Sent folder of the sender: delete them by hand"
            )
        else:
            clean_up(env, receiver, other, base, subject)
        anyio.run(services.accounts.close)
        services.close()

    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
