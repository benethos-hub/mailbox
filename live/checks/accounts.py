"""The test accounts of ``live/.env``, and adding them to a service."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from benethos_mailbox_client import ApiError, SyncMailboxClient

from .run import Run

ENV_FILE = Path(__file__).parents[1] / ".env"


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
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
    """The test accounts, in the order of ``live/.env``. Only these are
    confirmed test accounts (CLAUDE.md, golden rule 1)."""
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


def imap_settings(
    env: dict[str, str], account: dict[str, str], discovered: dict[str, Any]
) -> dict[str, Any]:
    """The IMAP settings of a test account: ``LIVE_IMAP_*`` where set, else
    what discovery found."""
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


def register(
    mailbox: SyncMailboxClient, env: dict[str, str], account: dict[str, str]
) -> tuple[str | None, str]:
    """The test account in the service, added through the API with IMAP and
    the SMTP server discovery finds: its id, and what happened. An account
    whose address the service has already is not added again."""
    known = mailbox.list_accounts(address=account["email"])
    for existing in known.items:
        if existing.email.lower() == account["email"].lower():
            return existing.id, "already there"
    found = mailbox.discover_account(account["email"])
    discovered: dict[str, Any] = next(
        (c.settings for c in found.candidates if c.settings), {}
    )
    try:
        created = mailbox.create_account(
            "imap",
            account["email"],
            settings=imap_settings(env, account, discovered),
            credentials={"password": account["password"]},
        )
    except ApiError as exc:
        return None, f"{exc.status} {exc.message}"
    return created.id, "added"


def register_all(
    run: Run,
    mailbox: SyncMailboxClient,
    env: dict[str, str],
    wanted: list[dict[str, str]],
) -> list[str]:
    """The ids of ``wanted`` in the service, one check each. Fewer ids than
    accounts means one did not connect."""
    ids: list[str] = []
    for account in wanted:
        account_id, outcome = register(mailbox, env, account)
        if run.check(
            f"account {len(ids) + 1} in the service", account_id is not None, outcome
        ):
            ids.append(str(account_id))
    return ids
