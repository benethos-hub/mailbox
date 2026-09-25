"""Live smoke run against the test accounts in ``live/.env``.

    uv run python live/smoke.py [--show] [--wrong-password]

Read-only: discovers each address, connects it, lists folders and messages,
reads one message and its source, and checks that reading changed no
unread flag and that ids stay the same. Then lists across all accounts and
syncs each account once. ``--show`` prints the messages of the first page:
sender, recipients, subject, attachment names and the start of the text.
``--wrong-password`` also tries one login with a wrong password, which the
server may count against the account.

Moves by another client and IDLE are checked by ``live/changes.py``, which
writes to the test accounts.

Runs in-process with memory storage and a throwaway master key, so nothing
is stored. Without ``--show`` it prints counts and sizes, never message
content. Credentials are never printed. Not a test: it is outside
``testpaths`` and needs the network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import anyio
from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
from benethos_mailbox_api.errors import MailboxApiError
from benethos_mailbox_api.main import build_services, create_app

ENV_FILE = Path(__file__).with_name(".env")


class Run:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
        self.failures += not ok
        return ok


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"{path} is missing; copy live/.env.example and fill it in")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return {k: v for k, v in values.items() if v}


def accounts(env: dict[str, str]) -> list[dict[str, str]]:
    found = []
    number = 1
    while f"LIVE_ACCOUNT_{number}_EMAIL" in env:
        prefix = f"LIVE_ACCOUNT_{number}_"
        found.append(
            {
                "email": env[prefix + "EMAIL"],
                "password": env.get(prefix + "PASSWORD", ""),
                "username": env.get(prefix + "USERNAME", env[prefix + "EMAIL"]),
            }
        )
        number += 1
    if not found:
        sys.exit("no LIVE_ACCOUNT_1_EMAIL in live/.env")
    return found


def imap_settings(
    env: dict[str, str], account: dict[str, str], discovered: dict[str, Any]
) -> dict[str, Any]:
    if "LIVE_IMAP_HOST" not in env:
        settings = dict(discovered)
    else:
        settings = {"host": env["LIVE_IMAP_HOST"]}
        if "LIVE_IMAP_PORT" in env:
            settings["port"] = int(env["LIVE_IMAP_PORT"])
        if "LIVE_IMAP_SECURITY" in env:
            settings["security"] = env["LIVE_IMAP_SECURITY"]
        # Sending: from LIVE_SMTP_* where set, else what discovery found.
        for key in ("smtp_host", "smtp_port", "smtp_security", "smtp_username"):
            if f"LIVE_{key.upper()}" in env:
                settings[key] = env[f"LIVE_{key.upper()}"]
            elif key in discovered:
                settings[key] = discovered[key]
    settings["username"] = account["username"]
    return settings


def unread_ids(client: TestClient, account_id: str) -> set[str]:
    page = client.get(
        f"/v1/accounts/{account_id}/messages", params={"unread": True, "limit": 50}
    ).json()
    return {m["id"] for m in page.get("items", [])}


def smoke_account(
    run: Run,
    client: TestClient,
    env: dict[str, str],
    account: dict[str, str],
    used: dict[str, dict[str, Any]],
    show: bool = False,
) -> str | None:
    """Connect and read one account. Records the settings in ``used``."""
    email = account["email"]
    print(f"\n== {email}")
    found = client.post("/v1/discovery", json={"email": email})
    candidates = found.json().get("candidates", []) if found.status_code == 200 else []
    run.check(
        "discovery",
        found.status_code == 200,
        f"{len(candidates)} candidates, sources "
        + ", ".join(
            f"{s['source']}={s['outcome']}" for s in found.json().get("sources", [])
        ),
    )
    for c in candidates:
        imap = c["servers"][0] if c["servers"] else {}
        print(
            f"      {c['source']:<10} confirmed={c['confirmed']!s:<5} "
            f"{imap.get('host')}:{imap.get('port')} {imap.get('security')} "
            f"reachable={imap.get('reachable')} credential={c['credential']}"
        )
    discovered = candidates[0]["settings"] if candidates else {}
    settings = imap_settings(env, account, discovered)
    if "host" not in settings:
        run.check("settings", False, "nothing discovered and no LIVE_IMAP_HOST")
        return None
    used[email] = settings

    created = client.post(
        "/v1/accounts",
        json={
            "provider": "imap",
            "email": email,
            "settings": settings,
            "credentials": {"password": account["password"]},
        },
    )
    if not run.check(
        "connect (IMAP and SMTP verified, then stored)"
        if "smtp_host" in settings
        else "connect (verify, then store)",
        created.status_code == 201,
        f"{created.status_code} {created.json().get('error', {}).get('code', '')}",
    ):
        return None
    account_id: str = created.json()["id"]

    folders = client.get(f"/v1/accounts/{account_id}/folders")
    roles = sorted(f["role"] for f in folders.json() if f.get("role"))
    subscribed = sum(1 for f in folders.json() if f.get("subscribed"))
    run.check(
        "folders",
        folders.status_code == 200,
        f"{len(folders.json())}, {subscribed} subscribed, roles {roles}",
    )

    before = unread_ids(client, account_id)
    listing = client.get(f"/v1/accounts/{account_id}/messages", params={"limit": 5})
    items = listing.json().get("items", [])
    run.check("messages", listing.status_code == 200, f"{len(items)} on the first page")
    if items:
        first = items[0]["id"]
        message = client.get(f"/v1/accounts/{account_id}/messages/{first}")
        body = message.json()
        run.check(
            "one message",
            message.status_code == 200,
            f"text {len(body.get('text_body') or '')} chars, "
            f"{len(body.get('attachments', []))} attachments",
        )
        raw = client.get(f"/v1/accounts/{account_id}/messages/{first}/raw")
        run.check("raw source", raw.status_code == 200, f"{len(raw.content)} bytes")
        if show:
            for item in items:
                show_message(client, account_id, item["id"])
        run.check(
            "reading left unread flags alone", unread_ids(client, account_id) == before
        )
        again = client.get(f"/v1/accounts/{account_id}/messages", params={"limit": 5})
        run.check(
            "ids stay the same",
            [m["id"] for m in again.json().get("items", [])]
            == [m["id"] for m in items],
            items[0]["id"][:4] + "...",
        )
        check_search(run, client, account_id, items[0])
    return account_id


def check_search(
    run: Run, client: TestClient, account_id: str, newest: dict[str, Any]
) -> None:
    """Every filter finds the newest mail when it fits and leaves it out
    when it does not. Nothing of the mail is printed."""
    url = f"/v1/accounts/{account_id}/messages"

    def found(**params: Any) -> bool | None:
        answer = client.get(url, params={"limit": 50, **params})
        if answer.status_code != 200:
            return None
        return newest["id"] in [m["id"] for m in answer.json().get("items", [])]

    by_role = client.get(url, params={"folder": "inbox", "limit": 1}).json()
    run.check(
        "folder by its role",
        [m["id"] for m in by_role.get("items", [])] == [newest["id"]],
    )
    words = [w for w in (newest.get("subject") or "").split() if len(w) >= 3]
    sender = (newest.get("from") or {}).get("email", "")
    day = (newest.get("date") or "")[:10]
    starred = bool(newest.get("starred"))
    attached = bool(newest.get("has_attachments"))
    cases = [
        ("subject", words and found(subject=words[0]), True),
        ("from", sender and found(**{"from": sender.split("@")[0]}), True),
        ("after its day", day and found(after=day), True),
        ("before its day", day and found(before=day), False),
        ("starred", found(starred=starred), True),
        ("starred, the other way", found(starred=not starred), False),
        ("has_attachments", found(has_attachments=attached), True),
        ("has_attachments, the other way", found(has_attachments=not attached), False),
    ]
    for name, result, expected in cases:
        if result == "" or result == []:
            continue  # the newest mail has no such field
        run.check(f"search: {name}", result is expected)
    injected = client.get(url, params={"q": "a\r\nX1 LOGOUT"})
    run.check(
        "search text with a line break is refused",
        injected.status_code == 422,
        str(injected.status_code),
    )


SHOW_CHARS = 1000


def address(value: dict[str, Any] | None) -> str:
    if not value:
        return "-"
    name, email = value.get("name"), value.get("email")
    return f"{name} <{email}>" if name else str(email)


def show_message(client: TestClient, account_id: str, message_id: str) -> None:
    response = client.get(f"/v1/accounts/{account_id}/messages/{message_id}")
    if response.status_code != 200:
        print(f"\n   --- {message_id}: {response.status_code}")
        return
    m = response.json()
    print("\n   ---")
    print(f"   From:    {address(m.get('from'))}")
    print(f"   To:      {', '.join(address(a) for a in m.get('to', [])) or '-'}")
    if m.get("cc"):
        print(f"   Cc:      {', '.join(address(a) for a in m['cc'])}")
    print(f"   Date:    {m.get('date') or '-'}")
    print(f"   Subject: {m.get('subject') or '-'}")
    print(f"   Unread:  {m.get('unread')}")
    for a in m.get("attachments", []):
        inline = ", inline" if a.get("inline") else ""
        print(
            f"   Attachment: {a.get('filename') or '(no name)'} "
            f"({a.get('content_type')}, {a.get('size')} bytes{inline})"
        )
    text = m.get("text_body")
    if not text and m.get("html_body"):
        text = "(HTML only, " + str(len(m["html_body"])) + " chars)"
    text = (text or "(no text)").strip()
    if len(text) > SHOW_CHARS:
        text = text[:SHOW_CHARS] + f"\n... ({len(text) - SHOW_CHARS} more chars)"
    print("   Body:")
    for line in text.splitlines():
        print(f"      {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--wrong-password", action="store_true")
    args = parser.parse_args()

    env = read_env(ENV_FILE)
    settings = Settings(
        storage="memory",
        api_key=SecretStr("live-smoke"),
        key_provider="env",
        master_key=SecretStr(encode_recovery(cipher.new_key())),
        sync_interval=0,
    )
    services = build_services(settings)
    services.vault.initialize()
    client = TestClient(
        create_app(settings, services),
        headers={"Authorization": "Bearer live-smoke"},
    )
    run = Run()
    used: dict[str, dict[str, Any]] = {}
    ids = [
        account_id
        for account in accounts(env)
        if (account_id := smoke_account(run, client, env, account, used, args.show))
    ]

    if ids:
        print("\n== across accounts")
        page = client.get("/v1/messages", params={"limit": 10}).json()
        run.check(
            "GET /v1/messages",
            not page.get("incomplete"),
            f"{len(page.get('items', []))} items, incomplete {page.get('incomplete')}",
        )
        me = client.get("/v1/me").json()
        listed = {a["id"]: a for a in me.get("accounts", [])}
        emails = {a["email"].lower() for a in accounts(env)}
        run.check(
            "GET /v1/me lists every account with its address",
            all(
                i in listed
                and listed[i]["email"].lower() in emails
                and listed[i]["operations"]
                for i in ids
            ),
            f"{len(listed)} accounts",
        )
        run.check(
            "GET /v1/me warns that the admin key may read and send anywhere",
            all(
                "read_and_send_anywhere" in listed.get(i, {}).get("warnings", [])
                for i in ids
            ),
        )

    for account_id in ids:
        print(f"\n== sync {account_id}")
        try:
            anyio.run(services.sync.sync_account, account_id)
            states = services.sync._index.folder_states(account_id)
            run.check("one pass", True, f"{len(states)} folders indexed")
            anyio.run(services.sync.sync_account, account_id)
            run.check("a second pass right after", True)
        except MailboxApiError as exc:
            run.check("one pass", False, f"{exc.code}: {exc.message}")

    if args.wrong_password and used:
        email, settings_used = next(iter(used.items()))
        print("\n== wrong password")
        wrong = client.post(
            "/v1/accounts",
            json={
                "provider": "imap",
                "email": email,
                "settings": settings_used,
                "credentials": {"password": "definitely-wrong"},
            },
        )
        run.check(
            "rejected, nothing stored",
            wrong.status_code == 502
            and wrong.json()["error"]["code"] == "provider_auth_failed",
            str(wrong.status_code),
        )

    anyio.run(services.aclose)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
