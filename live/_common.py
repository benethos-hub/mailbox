"""What the live checks share: the test accounts of ``live/.env``, the
outcome of a run, a service of their own, and waiting for a mail.

Not a test and not part of a package. Every script under ``live/`` imports
from here, so a script can be run from the repository root with
``uv run python live/<name>.py``.
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import httpx

from benethos_mailbox_service.data.secrets import cipher, encode_recovery

ENV_FILE = Path(__file__).with_name(".env")
T = TypeVar("T")


class Run:
    """The checks of one run: each printed as it happens, counted at the end."""

    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
        self.failures += not ok
        return ok

    def finish(self) -> int:
        """The closing line, and the exit code of the script."""
        print(f"\n{self.failures} failed" if self.failures else "\nall passed")
        return 1 if self.failures else 0


# --- the test accounts -------------------------------------------------------


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
    client: httpx.Client, env: dict[str, str], account: dict[str, str]
) -> tuple[str | None, str]:
    """The test account in the service, added through the API with IMAP and
    the SMTP server discovery finds: its id, and what happened. An account
    whose address the service has already is not added again."""
    known = client.get("/v1/accounts").json()
    for existing in known:
        if existing.get("email", "").lower() == account["email"].lower():
            return str(existing["id"]), "already there"
    found = client.post("/v1/discovery", json={"email": account["email"]}).json()
    discovered: dict[str, Any] = next(
        (c["settings"] for c in found.get("candidates", []) if c.get("settings")), {}
    )
    created = client.post(
        "/v1/accounts",
        json={
            "provider": "imap",
            "email": account["email"],
            "settings": imap_settings(env, account, discovered),
            "credentials": {"password": account["password"]},
        },
    )
    if created.status_code != 201:
        message = created.json().get("error", {}).get("message", "")
        return None, f"{created.status_code} {message}"
    return str(created.json()["id"]), "added"


def register_all(
    run: Run, client: httpx.Client, env: dict[str, str], wanted: list[dict[str, str]]
) -> list[str]:
    """The ids of ``wanted`` in the service, one check each. Fewer ids than
    accounts means one did not connect."""
    ids: list[str] = []
    for account in wanted:
        account_id, outcome = register(client, env, account)
        if run.check(
            f"account {len(ids) + 1} in the service", account_id is not None, outcome
        ):
            ids.append(str(account_id))
    return ids


def user_token(
    client: httpx.Client,
    account_ids: list[str],
    allow: list[str],
    **constraints: Any,
) -> str:
    """A user with ``allow`` on the accounts, and a token for it."""
    user = client.post(
        "/v1/users",
        json={
            "name": f"live check {'+'.join(allow)}",
            "grants": [{"accounts": account_ids, "allow": allow, **constraints}],
        },
    ).json()
    created = client.post(f"/v1/users/{user['id']}/tokens", json={"name": "live"})
    return str(created.json()["token"])


# --- waiting for a mail ------------------------------------------------------


def polled(look: Callable[[], T], tries: int, pause: float) -> T | None:
    """What ``look`` finds, tried again after ``pause`` seconds until it finds
    something or ``tries`` are used up."""
    for attempt in range(tries):
        found = look()
        if found:
            return found
        if attempt + 1 < tries:
            time.sleep(pause)
    return None


def messages_with_subject(
    client: httpx.Client,
    account_id: str,
    subject: str,
    folder: str | None = None,
    tries: int = 10,
    pause: float = 3.0,
) -> list[dict[str, Any]]:
    """The messages with exactly ``subject`` in the account, polled through
    the API until one is there. Delivery takes a moment."""
    params: dict[str, Any] = {"subject": subject, "limit": 10}
    if folder is not None:
        params["folder"] = folder

    def look() -> list[dict[str, Any]]:
        page = client.get(f"/v1/accounts/{account_id}/messages", params=params).json()
        return [m for m in page.get("items", []) if m.get("subject") == subject]

    return polled(look, tries, pause) or []


# --- a service of the script's own -------------------------------------------


def program(name: str) -> str:
    """The console script ``name``, which ``uv run`` puts on the path."""
    command = shutil.which(name)
    if command is None:
        sys.exit(f"{name} not found: run this with uv run")
    return command


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def started(process: subprocess.Popen[bytes], url: str, what: str) -> None:
    """Returns once ``url`` answers, else ends the process and the script."""
    for _ in range(60):
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.TransportError:
            time.sleep(0.5)
    process.terminate()
    sys.exit(f"{what} did not start")


def stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    process.wait(timeout=10)


def service_env(
    data_dir: str, port: int, admin_key: str, master_key: str | None = None
) -> dict[str, str]:
    """The environment of a service on ``port`` with SQLite in ``data_dir``,
    the master key in the environment, and no background sync."""
    return {
        **os.environ,
        "MAILBOX_SERVICE_DATA_DIR": data_dir,
        "MAILBOX_SERVICE_STORAGE": "sqlite",
        "MAILBOX_SERVICE_KEY_PROVIDER": "env",
        "MAILBOX_SERVICE_MASTER_KEY": master_key or encode_recovery(cipher.new_key()),
        "MAILBOX_SERVICE_KEY": admin_key,
        "MAILBOX_SERVICE_HOST": "127.0.0.1",
        "MAILBOX_SERVICE_PORT": str(port),
        "MAILBOX_SERVICE_SYNC_INTERVAL": "0",
        "MAILBOX_SERVICE_SYNC_IDLE": "false",
    }


def start_service(
    env: dict[str, str], url: str, init_keys: bool = True
) -> subprocess.Popen[bytes]:
    """``benethos-mailbox-service serve`` with ``env``, once it answers."""
    command = program("benethos-mailbox-service")
    if init_keys:
        subprocess.run(
            [command, "keys", "init"], env=env, check=True, capture_output=True
        )
    process = subprocess.Popen(
        [command, "serve"],
        env=env,
        stdout=subprocess.DEVNULL,
        # Nobody reads it: a pipe would fill up and block the service.
        stderr=subprocess.DEVNULL,
    )
    started(process, f"{url}/health", "the service")
    return process


@dataclass(frozen=True)
class Service:
    """A running service and the key that administers it."""

    url: str
    admin_key: str

    def admin(self, timeout: float = 60) -> httpx.Client:
        return httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {self.admin_key}"},
            timeout=timeout,
        )


@contextmanager
def throwaway_service(prefix: str) -> Iterator[Service]:
    """A service of the script's own on a free port, with a database and a
    master key that are gone at the end."""
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    admin_key = secrets.token_urlsafe(32)
    data_dir = tempfile.mkdtemp(prefix=prefix)
    process = start_service(service_env(data_dir, port, admin_key), url)
    try:
        yield Service(url, admin_key)
    finally:
        stop(process)
        shutil.rmtree(Path(data_dir), ignore_errors=True)
