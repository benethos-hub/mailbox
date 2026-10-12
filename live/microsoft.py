"""Live check of the microsoft adapter against a Microsoft test account.

    uv run python live/microsoft.py --connect   # once: sign in in a browser
    uv run python live/microsoft.py             # the check, unattended

    uv run python live/microsoft.py --project --connect   # with a code
    uv run python live/microsoft.py --project             # the check

Needs, in live/.env: the test account's address in LIVE_MICROSOFT_EMAIL.
Listing the address there confirms it as a test account (CLAUDE.md,
golden rule 1). Without ``--project``, an app of your own
(LIVE_MICROSOFT_CLIENT_ID, LIVE_MICROSOFT_CLIENT_SECRET, optional
LIVE_MICROSOFT_TENANT) with the redirect URI
http://localhost:8080/ui/oauth/microsoft/callback. With ``--project``,
the project's app that comes with the service: ``--connect`` then signs
in over the API with a code, which it prints, entered by a person at
Microsoft's page. See docs/MICROSOFT.md.

The service runs with a database of its own in data/live-microsoft/, or
data/live-microsoft-project/ with ``--project``, which keeps the
encrypted refresh token between runs. A refresh token belongs to the app
that issued it, so the two never share one. The master key, and the
password and a token of its user `admin`, live beside it, readable by the
owner only. The first run makes that user with `users create-admin`.

``--connect`` starts the service and waits until the test account is
connected through the UI. The check then reads folders and mail, the
inline images of one where the inbox has one, makes a folder and a reply
draft and removes them, and sends one mail with a file from the
Microsoft test account to the first test account, which must arrive
under the Message-ID the send answered. The send names its copy in Sent
Items, whose text and file are as sent. A reply to that copy goes to
the first test account as well, and its own copy names what it answers.
The copy gets a keyword, an Outlook category, which is taken off again,
and its conversation must hold it. ``--large`` reads, then sends one mail
of about 7 MB alone, beyond one Graph request: one file goes in one
request, the other through an upload session, and both sides must hold
them whole. Outlook.com blocked the test account once after several
sends in a day, so it stays a run of its own. At the end every mail of this check
left in either account, of this run or an earlier one, is deleted for
good, found by the subject. The change feed must name the copy in
Sent Items, which the service learns of through Graph delta queries only.
For that the worker polls every 20 seconds while the check runs, without
IMAP IDLE. Credentials and mail content are never printed.
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
from checks.mail import (
    delete_for_good,
)
from checks.microsoft_mail import inline, large, send_and_check
from checks.processes import service_env, start_service, stop
from checks.run import Run
from checks.service import Service

from benethos_mailbox_client import SyncMailboxClient
from benethos_mailbox_service.data.secrets import cipher, encode_recovery

SYNC_INTERVAL = 20
# Every mail the check sends starts with it, so a later run finds leftovers.
SUBJECT = "mailbox-service microsoft live check"
DATA = Path("data/live-microsoft")
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


def microsoft_env(env: dict[str, str], project: bool) -> dict[str, str]:
    """The service on its own database in DATA, reachable under URL, with
    the app registration of live/.env, or with the project's app."""
    master_key = _secret_file("master_key", lambda: encode_recovery(cipher.new_key()))
    service = {
        **service_env(str(DATA), PORT, master_key),
        "MAILBOX_SERVICE_PUBLIC_URL": URL,
        "MAILBOX_SERVICE_OAUTH_MICROSOFT_TENANT": env.get("LIVE_MICROSOFT_TENANT")
        or "common",
        # The change feed learns of the copy in Sent Items from the worker.
        "MAILBOX_SERVICE_SYNC_INTERVAL": str(SYNC_INTERVAL),
        "MAILBOX_SERVICE_SYNC_IDLE": "false",
    }
    for name in ("ID", "SECRET", "SECRET_FILE"):
        service.pop(f"MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_{name}", None)
    if not project:
        service["MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID"] = env[
            "LIVE_MICROSOFT_CLIENT_ID"
        ]
        service["MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET"] = env.get(
            "LIVE_MICROSOFT_CLIENT_SECRET", ""
        )
    return service


def microsoft_account(client: httpx.Client, email: str) -> dict[str, Any] | None:
    found = client.get("/v1/accounts", params={"address": email}).json()
    for account in found["items"]:
        if account["provider"] == "microsoft" and account["email"] == email:
            return dict(account)
    return None


def connect(client: httpx.Client, email: str) -> int:
    print(f"Open {URL}/ui and sign in as admin, password in {DATA / 'admin_password'}.")
    print("Then: Accounts, Connect an account, Sign in with Microsoft, as the")
    print("test account. Waiting up to ten minutes...")
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        account = microsoft_account(client, email)
        if account is not None and account["status"] == "connected":
            print("connected; run the check without --connect now")
            return 0
        time.sleep(3)
    print("not connected in time")
    return 1


def connect_with_code(client: httpx.Client, email: str) -> int:
    """Over the API: a code a person enters at Microsoft, then polling
    until the test account is connected."""
    started = client.post("/v1/oauth/microsoft/device", json={})
    if started.status_code != 200:
        print(f"no code: {started.status_code} {started.text}")
        return 1
    body = started.json()
    print(f"Open {body['verification_uri']} and enter the code {body['user_code']}.")
    print(f"Sign in there as the test account {email}. Waiting...")
    poll = f"/v1/oauth/microsoft/device/{body['sign_in_id']}"
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        time.sleep(body["interval"])
        answer = client.post(poll)
        if answer.status_code != 200:
            print(f"the sign-in ended: {answer.json()['error']['message']}")
            return 1
        account = answer.json()["account"]
        if account is not None:
            if account["email"] != email:
                print("signed in with another account than the test account")
                return 1
            print("connected; run the check without --connect now")
            return 0
    print("not connected in time")
    return 1


def check(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    ms_id: str,
    bot: dict[str, str],
    bot_id: str,
    large_only: bool = False,
) -> None:
    """What the API answers is checked with ``client``. ``mailbox``, the
    Python client, finds and deletes the test mail. ``large_only`` reads,
    then sends the large mail alone."""
    base = f"/v1/accounts/{ms_id}"
    print("\n== reading")
    verified = client.post(f"{base}/verify")
    if not run.check(
        "the token works",
        verified.status_code == 200,
        f"{verified.status_code} {verified.json().get('error', {}).get('code', '')}: "
        f"{verified.json().get('error', {}).get('message', '')}",
    ):
        print("connect the account again with --connect, then run this again")
        return
    folders = client.get(f"{base}/folders").json()
    roles = {f.get("role") for f in folders}
    run.check("folders with their roles", {"inbox", "sent", "drafts", "trash"} <= roles)
    inbox = client.get(f"{base}/messages", params={"folder": "inbox", "limit": 5})
    run.check("the inbox lists", inbox.status_code == 200)
    items = inbox.json().get("items", [])
    if items:
        one = client.get(f"{base}/messages/{items[0]['id']}")
        run.check("a message opens", one.status_code == 200)
        raw = client.get(f"{base}/messages/{items[0]['id']}/raw")
        run.check("its source", raw.status_code == 200 and b":" in raw.content[:200])
    searched = client.get(f"{base}/messages", params={"q": "zz-no-such-mail-zz"})
    run.check("a search", searched.status_code == 200)
    inline(run, client, base)
    if large_only:
        _large_only(run, client, mailbox, ms_id, bot, bot_id)
        return

    print("\n== folders")
    made = client.post(f"{base}/folders", json={"name": "mailbox-service live check"})
    if run.check("create a folder", made.status_code == 201):
        folder_id = made.json()["id"]
        renamed = client.patch(
            f"{base}/folders/{folder_id}", json={"name": "mailbox-service live check 2"}
        )
        run.check("rename it, same id", renamed.json().get("id") == folder_id)
        gone = client.delete(f"{base}/folders/{folder_id}")
        run.check("delete it", gone.status_code == 204)

    print("\n== drafts")
    if items:
        draft = client.post(
            f"{base}/drafts",
            json={
                "reference": {"message_id": items[0]["id"], "action": "reply"},
                "text": "A reply draft of the live check.",
            },
        )
        if run.check("a reply draft", draft.status_code == 201, str(draft.status_code)):
            draft_id = draft.json()["id"]
            stored = client.get(f"{base}/messages/{draft_id}").json()
            run.check(
                "it knows what it answers",
                stored.get("reference") is not None and bool(stored.get("in_reply_to")),
            )
            replaced = client.put(
                f"{base}/drafts/{draft_id}",
                json={
                    "reference": {**stored["reference"], "quote": False},
                    "to": [{"email": a["email"]} for a in stored.get("to", [])],
                    "subject": stored.get("subject") or "",
                    "text": (stored.get("text_body") or "") + "\nChanged.",
                },
            )
            run.check("replace it as a whole", replaced.status_code == 200)
            listed = client.get(f"{base}/drafts").json().get("items", [])
            current = next(
                (d for d in listed if d.get("subject") == stored.get("subject")), None
            )
            if current is not None:
                deleted = client.delete(f"{base}/drafts/{current['id']}")
                run.check("delete it", deleted.status_code == 204)

    _sending(run, client, mailbox, ms_id, bot, bot_id)


def _sending(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    ms_id: str,
    bot: dict[str, str],
    bot_id: str,
) -> None:
    """A mail and a reply to the first test account, and whatever is left
    of them deleted for good."""
    base = f"/v1/accounts/{ms_id}"
    print("\n== sending, to the first test account only")
    since = client.get(f"{base}/changes").json()["state"]
    subject = f"{SUBJECT} {secrets.token_hex(4)}"
    try:
        sending = (ms_id, since, subject)
        send_and_check(run, client, mailbox, sending, bot, bot_id, 4 * SYNC_INTERVAL)
    finally:
        _sweep(mailbox, [(bot_id, "inbox"), (ms_id, "sent"), (ms_id, "trash")])


def _large_only(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    ms_id: str,
    bot: dict[str, str],
    bot_id: str,
) -> None:
    """The large mail alone, one send: Outlook.com blocked the test account
    once after several sends in a day."""
    base = f"/v1/accounts/{ms_id}"
    print("\n== a large mail, to the first test account only")
    subject = f"{SUBJECT} {secrets.token_hex(4)} large"
    try:
        large(run, client, mailbox, base, bot, bot_id, subject)
    finally:
        _sweep(mailbox, [(bot_id, "inbox"), (ms_id, "sent"), (ms_id, "trash")])


def _sweep(mailbox: SyncMailboxClient, places: list[tuple[str, str | None]]) -> None:
    """What this check left of its mails, deleted for good: a mail that
    arrived after the check gave up, or one of an earlier run."""
    removed = delete_for_good(
        mailbox,
        places,
        SUBJECT,
        matches=lambda found: found.removeprefix("Re: ").startswith(SUBJECT),
    )
    if removed:
        print(f"      cleanup: {removed} mail(s) of the check deleted for good")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--connect", action="store_true", help="connect the test account"
    )
    parser.add_argument("--project", action="store_true", help="with the project's app")
    parser.add_argument(
        "--large", action="store_true", help="read, then send the large mail alone"
    )
    options = parser.parse_args()
    env = read_env()
    email = (env.get("LIVE_MICROSOFT_EMAIL") or "").strip().lower()
    if not email or not (options.project or env.get("LIVE_MICROSOFT_CLIENT_ID")):
        print(
            "not set up: LIVE_MICROSOFT_EMAIL in live/.env, and "
            "LIVE_MICROSOFT_CLIENT_ID without --project"
        )
        return 2
    if options.project:
        global DATA
        DATA = Path("data/live-microsoft-project")
    service = microsoft_env(env, options.project)
    # The keys are made on the first run; the database keeps them after.
    process = start_service(service, URL, init_keys=not (DATA / "mailbox.db").exists())
    run = Run()
    try:
        running = Service(URL, _admin(service))
        with running.admin(timeout=120) as client, running.mailbox() as mailbox:
            if options.connect:
                if options.project:
                    return connect_with_code(client, email)
                return connect(client, email)
            account = microsoft_account(client, email)
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
            check(run, client, mailbox, account["id"], bot, bot_id, options.large)
    finally:
        stop(process)
    return run.finish()


if __name__ == "__main__":
    sys.exit(main())
