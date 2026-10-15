"""A service with a database of its own, for the checks of a provider
that signs in with OAuth (``gmail.py``, ``microsoft.py``).

Its folder keeps between runs what a sign-in left: the encrypted refresh
token in the database, the master key, and the password and a token of
its user ``admin``, each readable by the owner only. The first run makes
that user with ``users create-admin``, as an operator does.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from benethos_mailbox_service.data.secrets import cipher, encode_recovery

from .admin import Admin, bootstrap
from .processes import service_env

PORT = 8080
URL = f"http://localhost:{PORT}"
# The worker polls this often while a check runs, without IMAP IDLE: the
# change feed learns of a sent copy from it.
SYNC_INTERVAL = 20
# How long a person has to sign in.
WAIT = 600


@dataclass(frozen=True)
class OwnService:
    """The service's folder, ``data``."""

    data: Path

    def secret_file(self, name: str, make: Callable[[], str]) -> str:
        """A value kept in the folder, readable by the owner only, made
        once."""
        path = self.data / name
        if not path.exists():
            self.data.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(make())
        return path.read_text(encoding="utf-8").strip()

    def admin(self, service: Mapping[str, str]) -> Admin:
        """The service's user ``admin``, made on the first run."""
        if not (self.data / "admin_token").exists():
            made = bootstrap(dict(service), URL)
            self.secret_file("admin_password", lambda: made.password)
            self.secret_file("admin_token", lambda: made.token)
        return Admin(
            "admin",
            self.secret_file("admin_password", str),
            self.secret_file("admin_token", str),
        )

    def env(self, oauth_prefix: str, oauth: Mapping[str, str]) -> dict[str, str]:
        """The service on its own database, reachable under ``URL``, with
        the settings of ``oauth`` for the provider's app in place of any
        that start with ``oauth_prefix``."""
        master_key = self.secret_file(
            "master_key", lambda: encode_recovery(cipher.new_key())
        )
        service = {
            **service_env(str(self.data), PORT, master_key),
            "MAILBOX_SERVICE_PUBLIC_URL": URL,
            "MAILBOX_SERVICE_SYNC_INTERVAL": str(SYNC_INTERVAL),
            "MAILBOX_SERVICE_SYNC_IDLE": "false",
        }
        for name in [n for n in service if n.startswith(oauth_prefix)]:
            del service[name]
        return {**service, **oauth}

    @property
    def fresh(self) -> bool:
        """Whether no database is there yet: the keys are made first."""
        return not (self.data / "mailbox.db").exists()


def account_of(
    client: httpx.Client, provider: str, email: str
) -> dict[str, Any] | None:
    """The service's account of ``provider`` with the address ``email``."""
    found = client.get("/v1/accounts", params={"address": email}).json()
    for account in found["items"]:
        if account["provider"] == provider and account["email"] == email:
            return dict(account)
    return None


def wait_connected(
    own: OwnService, client: httpx.Client, provider: str, email: str, steps: str
) -> int:
    """Tell the person how to connect the test account in the UI, then
    wait until it is."""
    password = own.data / "admin_password"
    print(f"Open {URL}/ui and sign in as admin, password in {password}.")
    print(steps)
    print("Waiting up to ten minutes...")
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        account = account_of(client, provider, email)
        if account is not None and account["status"] == "connected":
            print("connected; run the check without --connect now")
            return 0
        time.sleep(3)
    print("not connected in time")
    return 1
