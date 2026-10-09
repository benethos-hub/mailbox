"""Live check of the gmail adapter against a Gmail test account.

    uv run python live/gmail.py --connect   # once: sign in in a browser
    uv run python live/gmail.py             # the check, unattended

Needs, in live/.env: the test account's address in LIVE_GMAIL_EMAIL, and
the Google client of a Google Cloud project in LIVE_GOOGLE_CLIENT_ID and
LIVE_GOOGLE_CLIENT_SECRET, with the redirect URI
http://localhost:8080/ui/oauth/gmail/callback (docs/GOOGLE.md). Listing
the address there confirms it as a test account (CLAUDE.md, golden
rule 1).

The service runs with a database of its own in data/live-gmail/, which
keeps the encrypted refresh token between runs. The master key, and the
password and a token of its user `admin`, live beside it, readable by the
owner only. The first run makes that user with `users create-admin`.

``--connect`` starts the service and waits until the test account is
connected through the UI. The check then reads folders and mail, makes a
label inside a label, renames the outer one and removes both, writes and
replaces a draft and deletes it, and sends one mail from the Gmail test
account to the first test account. There it is deleted for good. In
Gmail the copy in Sent is starred, given the label, archived and deleted
for good. The change feed must name it, which the service learns of
through Gmail's history only. Then the first test account sends one mail
to the Gmail test account, with umlauts in its subject. It must arrive
in the inbox, be found by a search, open with its body and source, be
named by the change feed, and turn read. It is deleted for good in
Gmail and in the first test account's sent folder. For that the worker polls every 20
seconds while the check runs. At the end every mail of this check left
in either account, of this run or an earlier one, is deleted for good,
found by the subject's prefix. Credentials and mail content are never
printed.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from checks.accounts import accounts, read_env, register
from checks.admin import Admin, bootstrap
from checks.mail import delete_for_good, feed_types, messages_with_subject
from checks.processes import service_env, start_service, stop
from checks.run import Run
from checks.service import Service

from benethos_mailbox_client import SyncMailboxClient
from benethos_mailbox_service.data.secrets import cipher, encode_recovery

SYNC_INTERVAL = 20
# Every mail the check sends starts with it, so a later run finds leftovers.
SUBJECT = "mailbox-service gmail live check"
LABEL = "mailbox-service live check"
DATA = Path("data/live-gmail")
PORT = 8080
URL = f"http://localhost:{PORT}"
WAIT = 600


def _secret_file(name: str, make: Any) -> str:
    """A value kept in DATA, readable by the owner only, made once."""
    path = DATA / name
    if not path.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(make())
    return path.read_text(encoding="utf-8").strip()


def _admin(service: dict[str, str]) -> Admin:
    """The service's user `admin`, made on the first run the way an
    operator makes it, and kept in DATA."""
    if not (DATA / "admin_token").exists():
        made = bootstrap(service, URL)
        _secret_file("admin_password", lambda: made.password)
        _secret_file("admin_token", lambda: made.token)
    return Admin(
        "admin", _secret_file("admin_password", str), _secret_file("admin_token", str)
    )


def gmail_env(env: dict[str, str]) -> dict[str, str]:
    """The service on its own database in DATA, reachable under URL, with
    the Google client of live/.env."""
    master_key = _secret_file("master_key", lambda: encode_recovery(cipher.new_key()))
    service = {
        **service_env(str(DATA), PORT, master_key),
        "MAILBOX_SERVICE_PUBLIC_URL": URL,
        # The change feed learns of the copy in Sent from the worker.
        "MAILBOX_SERVICE_SYNC_INTERVAL": str(SYNC_INTERVAL),
        "MAILBOX_SERVICE_SYNC_IDLE": "false",
    }
    service.pop("MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_SECRET_FILE", None)
    service["MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_ID"] = env["LIVE_GOOGLE_CLIENT_ID"]
    service["MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_SECRET"] = env[
        "LIVE_GOOGLE_CLIENT_SECRET"
    ]
    return service


def gmail_account(client: httpx.Client, email: str) -> dict[str, Any] | None:
    found = client.get("/v1/accounts", params={"address": email}).json()
    for account in found["items"]:
        if account["provider"] == "gmail" and account["email"] == email:
            return dict(account)
    return None


def connect(client: httpx.Client, email: str) -> int:
    print(f"Open {URL}/ui and sign in as admin, password in {DATA / 'admin_password'}.")
    print("Then: Accounts, Connect an account, the test account's address,")
    print("Sign in with Google. Google warns that it has not verified the app:")
    print("Advanced, Go to Mailbox. Waiting up to ten minutes...")
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        account = gmail_account(client, email)
        if account is not None and account["status"] == "connected":
            print("connected; run the check without --connect now")
            return 0
        time.sleep(3)
    print("not connected in time")
    return 1


def check(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    gmail: dict[str, str],
    bot: dict[str, str],
    bot_id: str,
) -> None:
    """What the API answers is checked with ``client``. ``mailbox``, the
    Python client, finds and deletes the test mail. ``gmail``: the Gmail
    test account's id and address."""
    gmail_id = gmail["id"]
    base = f"/v1/accounts/{gmail_id}"
    print("\n== reading")
    verified = client.post(f"{base}/verify")
    if not run.check(
        "the token works",
        verified.status_code == 200,
        f"{verified.status_code} {verified.json().get('error', {}).get('code', '')}",
    ):
        print("connect the account again with --connect, then run this again")
        return
    folders = client.get(f"{base}/folders").json()
    roles = {f.get("role") for f in folders}
    run.check(
        "folders with their roles",
        {"inbox", "sent", "drafts", "trash", "junk", "all"} <= roles,
        " ".join(sorted(r for r in roles if r)),
    )
    inbox = client.get(f"{base}/messages", params={"folder": "inbox", "limit": 5})
    run.check("the inbox lists", inbox.status_code == 200)
    items = inbox.json().get("items", [])
    if items:
        one = client.get(f"{base}/messages/{items[0]['id']}")
        run.check("a message opens", one.status_code == 200)
        raw = client.get(f"{base}/messages/{items[0]['id']}/raw")
        run.check("its source", raw.status_code == 200 and b":" in raw.content[:200])
    searched = client.get(f"{base}/messages", params={"q": "zz-no-such-mail-zz"})
    run.check("a search", searched.status_code == 200 and not searched.json()["items"])
    _folders(run, client, base)
    _drafts(run, client, base)

    print("\n== sending, to the first test account only")
    since = client.get(f"{base}/changes").json()["state"]
    subject = f"{SUBJECT} {secrets.token_hex(4)}"
    try:
        _send_and_check(run, client, mailbox, gmail_id, bot, bot_id, since, subject)
    finally:
        _sweep(mailbox, [(bot_id, "inbox"), (gmail_id, None)])

    print("\n== receiving, from the first test account only")
    since = client.get(f"{base}/changes").json()["state"]
    subject = f"{SUBJECT} {secrets.token_hex(4)} Grüße"
    try:
        _receive_and_check(run, client, mailbox, gmail, bot_id, since, subject)
    finally:
        _sweep(mailbox, [(bot_id, "sent"), (gmail_id, None)])


def _folders(run: Run, client: httpx.Client, base: str) -> None:
    print("\n== folders")
    outer = client.post(f"{base}/folders", json={"name": LABEL})
    if not run.check("create a label", outer.status_code == 201, outer.text[:80]):
        return
    outer_id = outer.json()["id"]
    inner = client.post(
        f"{base}/folders", json={"name": "inner", "parent_id": outer_id}
    )
    if run.check("a label inside it", inner.status_code == 201):
        inner_id = inner.json()["id"]
        renamed = client.patch(
            f"{base}/folders/{outer_id}", json={"name": f"{LABEL} 2"}
        )
        run.check("rename the outer one, same id", renamed.json().get("id") == outer_id)
        listed = {f["id"]: f for f in client.get(f"{base}/folders").json()}
        run.check(
            "the inner one stays inside", listed[inner_id].get("parent_id") == outer_id
        )
        client.delete(f"{base}/folders/{inner_id}")
    gone = client.delete(f"{base}/folders/{outer_id}")
    run.check("delete them", gone.status_code == 204)


def _drafts(run: Run, client: httpx.Client, base: str) -> None:
    print("\n== drafts")
    draft = client.post(
        f"{base}/drafts",
        json={"subject": f"{SUBJECT} draft", "text": "A draft of the live check."},
    )
    if not run.check("a draft", draft.status_code == 201, str(draft.status_code)):
        return
    draft_id = draft.json()["id"]
    replaced = client.put(
        f"{base}/drafts/{draft_id}",
        json={"subject": f"{SUBJECT} draft", "text": "Changed."},
    )
    run.check("replace it as a whole", replaced.status_code == 200)
    current = replaced.json().get("id", draft_id)
    source = client.get(f"{base}/messages/{current}/raw")
    run.check("its source is the new one", b"Changed." in source.content)
    deleted = client.delete(f"{base}/drafts/{current}")
    run.check("delete it", deleted.status_code == 204)


def _sweep(mailbox: SyncMailboxClient, places: list[tuple[str, str | None]]) -> None:
    """What this check left of its mails, deleted for good: a mail that
    arrived after the check gave up, or one of an earlier run."""
    removed = delete_for_good(
        mailbox, places, SUBJECT, matches=lambda found: found.startswith(SUBJECT)
    )
    if removed:
        print(f"      cleanup: {removed} mail(s) of the check deleted for good")


def _send_and_check(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    gmail_id: str,
    bot: dict[str, str],
    bot_id: str,
    since: str,
    subject: str,
) -> None:
    base = f"/v1/accounts/{gmail_id}"
    sent = client.post(
        f"{base}/send",
        json={
            "to": [{"email": bot["email"]}],
            "subject": subject,
            "text": "Sent by the live check; deleted again at once.",
        },
    )
    if not run.check("send", sent.status_code == 200, str(sent.status_code)):
        return
    found = messages_with_subject(
        mailbox, bot_id, subject, folder="inbox", tries=40, pause=5
    )
    if run.check("it arrives", bool(found)):
        mailbox.delete_message(bot_id, found[0]["id"], permanent=True)
    copies = messages_with_subject(
        mailbox, gmail_id, subject, folder="sent", tries=6, pause=5
    )
    if not run.check("the copy in Sent", bool(copies)):
        return
    copy = copies[0]["id"]
    types = feed_types(mailbox, gmail_id, since, copy, wait=4 * SYNC_INTERVAL)
    run.check(
        "the change feed names it (Gmail history)",
        "message.created" in types,
        " ".join(types) or "nothing",
    )
    _labels(run, client, base, copy)
    purged = client.delete(f"{base}/messages/{copy}", params={"permanent": "true"})
    run.check("deleted for good", purged.status_code == 204, str(purged.status_code))
    gone = client.get(f"{base}/messages/{copy}")
    run.check("and gone", gone.status_code == 404)


def _receive_and_check(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    gmail: dict[str, str],
    bot_id: str,
    since: str,
    subject: str,
) -> None:
    base = f"/v1/accounts/{gmail['id']}"
    sent = client.post(
        f"/v1/accounts/{bot_id}/send",
        json={
            "to": [{"email": gmail["email"]}],
            "subject": subject,
            "text": "Sent to the Gmail test account by the live check. Grüße.",
        },
    )
    if not run.check("the first test account sends", sent.status_code == 200):
        return
    found = messages_with_subject(
        mailbox, gmail["id"], subject, folder="inbox", tries=40, pause=5
    )
    if not run.check("it arrives in the Gmail inbox", bool(found)):
        return
    message = found[0]
    run.check(
        "unread, in the inbox and All Mail",
        message.get("unread") is True
        and {"INBOX", "ALL_MAIL"} <= set(message.get("folder_ids", [])),
    )
    searched = client.get(
        f"{base}/messages", params={"q": subject.split()[-2], "folder": "inbox"}
    )
    run.check(
        "a search finds it",
        message["id"] in [m["id"] for m in searched.json().get("items", [])],
    )
    opened = client.get(f"{base}/messages/{message['id']}").json()
    run.check(
        "it opens with its body",
        "Grüße" in (opened.get("text_body") or "") and opened.get("subject") == subject,
    )
    raw = client.get(f"{base}/messages/{message['id']}/raw")
    run.check("its source", raw.status_code == 200 and b"Subject:" in raw.content)
    types = feed_types(
        mailbox, gmail["id"], since, message["id"], wait=4 * SYNC_INTERVAL
    )
    run.check(
        "the change feed names it",
        "message.created" in types,
        " ".join(types) or "nothing",
    )
    read = client.patch(f"{base}/messages/{message['id']}", json={"unread": False})
    run.check("it turns read", read.status_code == 200 and not read.json()["unread"])
    purged = client.delete(
        f"{base}/messages/{message['id']}", params={"permanent": "true"}
    )
    run.check("deleted for good in Gmail", purged.status_code == 204)


def _labels(run: Run, client: httpx.Client, base: str, copy: str) -> None:
    """Star the copy, give it a label, archive it, take the label off."""
    url = f"{base}/messages/{copy}"
    starred = client.patch(url, json={"starred": True, "unread": False})
    run.check("star it", starred.status_code == 200 and starred.json().get("starred"))
    label = client.post(f"{base}/folders", json={"name": f"{LABEL} mail"})
    if not run.check("a label for it", label.status_code == 201):
        return
    label_id = label.json()["id"]
    try:
        moved = client.patch(url, json={"folder_ids": [label_id]})
        folders = moved.json().get("folder_ids", [])
        run.check(
            "it carries the label, Sent stays",
            label_id in folders and "SENT" in folders,
            " ".join(folders),
        )
        archived = client.patch(url, json={"folder_ids": ["ALL_MAIL"]})
        run.check(
            "archived: the label is off",
            label_id not in archived.json().get("folder_ids", []),
        )
    finally:
        client.delete(f"{base}/folders/{label_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--connect", action="store_true", help="connect the test account"
    )
    options = parser.parse_args()
    env = read_env()
    email = (env.get("LIVE_GMAIL_EMAIL") or "").strip().lower()
    if not email or not env.get("LIVE_GOOGLE_CLIENT_ID"):
        print(
            "not set up: LIVE_GMAIL_EMAIL, LIVE_GOOGLE_CLIENT_ID and "
            "LIVE_GOOGLE_CLIENT_SECRET in live/.env"
        )
        return 2
    service = gmail_env(env)
    # The keys are made on the first run; the database keeps them after.
    process = start_service(service, URL, init_keys=not (DATA / "mailbox.db").exists())
    run = Run()
    try:
        running = Service(URL, _admin(service))
        with running.admin(timeout=120) as client, running.mailbox() as mailbox:
            if options.connect:
                return connect(client, email)
            account = gmail_account(client, email)
            if not run.check("the test account is connected", account is not None):
                print("run with --connect first")
                return 1
            assert account is not None
            bot = accounts(env)[0]
            bot_id, outcome = register(mailbox, env, bot)
            if not run.check(
                "the first test account in the service", bot_id is not None, outcome
            ):
                return 1
            assert bot_id is not None
            gmail = {"id": str(account["id"]), "email": email}
            check(run, client, mailbox, gmail, bot, bot_id)
    finally:
        stop(process)
    return run.finish()


if __name__ == "__main__":
    sys.exit(main())
