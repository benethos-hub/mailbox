"""Live check of the microsoft adapter against a Microsoft test account.

    uv run python live/microsoft.py --connect   # once: sign in in a browser
    uv run python live/microsoft.py             # the check, unattended

Needs, in live/.env: the app registration (LIVE_MICROSOFT_CLIENT_ID,
LIVE_MICROSOFT_CLIENT_SECRET, optional LIVE_MICROSOFT_TENANT) with the
redirect URI http://localhost:8080/ui/oauth/microsoft/callback, and the
test account's address in LIVE_MICROSOFT_EMAIL. Listing the address there
confirms it as a test account (CLAUDE.md, golden rule 1). See
docs/microsoft.md.

The service runs with a database of its own in data/live-microsoft/, which
keeps the encrypted refresh token between runs. The master key and the
admin key live beside it, readable by the owner only.

``--connect`` starts the service and waits until the test account is
connected through the UI. The check then reads folders and mail, makes a
folder and a reply draft and removes them, and sends one mail from the
Microsoft test account to the first test account, which it deletes for
good on both sides afterwards. Credentials and mail content are never
printed.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from register import register
from smoke import ENV_FILE, Run, accounts, read_env

from benethos_mailbox_api.data.secrets import cipher, encode_recovery

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


def service_env(env: dict[str, str], admin_key: str) -> dict[str, str]:
    return {
        **os.environ,
        "MAILBOX_API_DATA_DIR": str(DATA),
        "MAILBOX_API_STORAGE": "sqlite",
        "MAILBOX_API_KEY_PROVIDER": "env",
        "MAILBOX_API_MASTER_KEY": _secret_file(
            "master_key", lambda: encode_recovery(cipher.new_key())
        ),
        "MAILBOX_API_KEY": admin_key,
        "MAILBOX_API_HOST": "127.0.0.1",
        "MAILBOX_API_PORT": str(PORT),
        "MAILBOX_API_PUBLIC_URL": URL,
        "MAILBOX_API_SYNC_INTERVAL": "0",
        "MAILBOX_API_SYNC_IDLE": "false",
        "MAILBOX_API_OAUTH_MICROSOFT_CLIENT_ID": env["LIVE_MICROSOFT_CLIENT_ID"],
        "MAILBOX_API_OAUTH_MICROSOFT_CLIENT_SECRET": env.get(
            "LIVE_MICROSOFT_CLIENT_SECRET", ""
        ),
        "MAILBOX_API_OAUTH_MICROSOFT_TENANT": env.get("LIVE_MICROSOFT_TENANT")
        or "common",
    }


def start(env: dict[str, str]) -> subprocess.Popen[bytes]:
    """The service on its own database. The keys are made on the first run."""
    command = shutil.which("benethos-mailbox-api")
    if command is None:
        sys.exit("benethos-mailbox-api not found: run this with uv run")
    if not (DATA / "mailbox.db").exists():
        subprocess.run(
            [command, "keys", "init"], env=env, check=True, capture_output=True
        )
    process = subprocess.Popen(
        [command, "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    for _ in range(60):
        try:
            if httpx.get(f"{URL}/health", timeout=1).status_code == 200:
                return process
        except httpx.TransportError:
            time.sleep(0.5)
    process.terminate()
    sys.exit("the service did not start")


def microsoft_account(client: httpx.Client, email: str) -> dict[str, Any] | None:
    for account in client.get("/v1/accounts").json():
        if account["provider"] == "microsoft" and account["email"] == email:
            return dict(account)
    return None


def connect(client: httpx.Client, email: str) -> int:
    print(f"Open {URL}/ui and sign in with the admin key in {DATA / 'admin_key'}.")
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


def _find(
    client: httpx.Client, account_id: str, folder: str, subject: str, tries: int
) -> str | None:
    for attempt in range(tries):
        page = client.get(
            f"/v1/accounts/{account_id}/messages",
            params={"folder": folder, "subject": subject, "limit": 10},
        ).json()
        found = [m for m in page.get("items", []) if m.get("subject") == subject]
        if found:
            return str(found[0]["id"])
        if attempt + 1 < tries:
            time.sleep(5)
    return None


def check(
    run: Run, client: httpx.Client, ms_id: str, bot: dict[str, str], bot_id: str
) -> None:
    base = f"/v1/accounts/{ms_id}"
    print("\n== reading")
    verified = client.post(f"{base}/verify")
    run.check("the token works", verified.status_code == 200, str(verified.status_code))
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

    print("\n== folders")
    made = client.post(f"{base}/folders", json={"name": "mailbox-api live check"})
    if run.check("create a folder", made.status_code == 201):
        folder_id = made.json()["id"]
        renamed = client.patch(
            f"{base}/folders/{folder_id}", json={"name": "mailbox-api live check 2"}
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
            run.check("it knows what it answers", stored.get("reference") is not None)
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

    print("\n== sending, to the first test account only")
    subject = f"mailbox-api microsoft live check {secrets.token_hex(4)}"
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
    # Outlook.com may take minutes to deliver, seen live.
    arrived = _find(client, bot_id, "inbox", subject, tries=60)
    if run.check("it arrives", arrived is not None):
        client.delete(
            f"/v1/accounts/{bot_id}/messages/{arrived}", params={"permanent": "true"}
        )
    copy = _find(client, ms_id, "sent", subject, tries=6)
    if run.check("the copy in Sent Items", copy is not None):
        moved = client.delete(f"{base}/messages/{copy}")
        run.check("to the trash", moved.status_code == 204)
        # Right after the move Exchange may not find the message yet: the
        # first answer is shown, then two more tries.
        for attempt in range(3):
            purged = client.delete(
                f"{base}/messages/{copy}", params={"permanent": "true"}
            )
            if purged.status_code == 204:
                break
            error = purged.json().get("error", {})
            code, text = error.get("code"), error.get("message")
            print(f"      try {attempt + 1}: {purged.status_code} {code}: {text}")
            time.sleep(3)
        run.check(
            "deleted for good", purged.status_code == 204, f"after {attempt + 1} tries"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--connect", action="store_true", help="connect the test account"
    )
    options = parser.parse_args()
    env = read_env(ENV_FILE)
    email = (env.get("LIVE_MICROSOFT_EMAIL") or "").strip().lower()
    if not env.get("LIVE_MICROSOFT_CLIENT_ID") or not email:
        print(
            "not set up: LIVE_MICROSOFT_CLIENT_ID and LIVE_MICROSOFT_EMAIL in live/.env"
        )
        return 2
    admin_key = _secret_file("admin_key", lambda: secrets.token_urlsafe(32))
    process = start(service_env(env, admin_key))
    run = Run()
    try:
        with httpx.Client(
            base_url=URL, headers={"Authorization": f"Bearer {admin_key}"}, timeout=120
        ) as client:
            if options.connect:
                return connect(client, email)
            account = microsoft_account(client, email)
            if not run.check("the test account is connected", account is not None):
                print("run with --connect first")
                return 1
            assert account is not None
            bot = accounts(env)[0]
            bot_id, outcome = register(client, env, bot)
            if not run.check(
                "the first test account in the service", bot_id is not None, outcome
            ):
                return 1
            assert bot_id is not None
            check(run, client, account["id"], bot, bot_id)
    finally:
        process.terminate()
        process.wait(timeout=10)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
