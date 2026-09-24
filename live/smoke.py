"""Live smoke run against the test accounts in ``live/.env``.

    uv run python live/smoke.py [--wrong-password]

Read-only: discovers each address, connects it, lists folders and messages,
reads one message and its source, and checks that reading changed no
unread flag. Then lists across all accounts. ``--wrong-password`` also
tries one login with a wrong password, which the server may count against
the account.

Runs in-process with memory storage and a throwaway master key, so nothing
is stored. Prints counts and sizes, never message content or credentials.
Not a test: it is outside ``testpaths`` and needs the network.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from benethos_mailbox_api.config import Settings
from benethos_mailbox_api.data.secrets import cipher, encode_recovery
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
        "connect (verify, then store)",
        created.status_code == 201,
        f"{created.status_code} {created.json().get('error', {}).get('code', '')}",
    ):
        return None
    account_id: str = created.json()["id"]

    folders = client.get(f"/v1/accounts/{account_id}/folders")
    roles = sorted(f["role"] for f in folders.json() if f.get("role"))
    run.check(
        "folders", folders.status_code == 200, f"{len(folders.json())}, roles {roles}"
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
        run.check(
            "reading left unread flags alone", unread_ids(client, account_id) == before
        )
    return account_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wrong-password", action="store_true")
    args = parser.parse_args()

    env = read_env(ENV_FILE)
    settings = Settings(
        storage="memory",
        api_key=SecretStr("live-smoke"),
        key_provider="env",
        master_key=SecretStr(encode_recovery(cipher.new_key())),
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
        if (account_id := smoke_account(run, client, env, account, used))
    ]

    if ids:
        print("\n== across accounts")
        page = client.get("/v1/messages", params={"limit": 10}).json()
        run.check(
            "GET /v1/messages",
            not page.get("incomplete"),
            f"{len(page.get('items', []))} items, incomplete {page.get('incomplete')}",
        )

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

    services.close()
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
