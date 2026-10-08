"""The first user of a service, the way an operator makes it, and users
with narrower rights for a check."""

from __future__ import annotations

import re
import secrets
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import httpx

from benethos_mailbox_client import SyncMailboxClient
from benethos_mailbox_service.assembly import Services
from benethos_mailbox_service.domain.rights import ADMIN_SERVICE, permissions
from benethos_mailbox_service.domain.rights.access import Access

from .processes import program, run_dir


@dataclass(frozen=True)
class Admin:
    """A user with every right: its name, its password for the UI, and a
    token for the API."""

    name: str
    password: str
    token: str


def csrf_of(html: str) -> str:
    found = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return found.group(1) if found else ""


def ui_sign_in(browser: httpx.Client, name: str, password: str) -> httpx.Response:
    """The sign-in form, sent with the nonce of its page."""
    page = browser.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    return browser.post(
        "/ui/login",
        data={
            "name": name,
            "password": password,
            "nonce": nonce.group(1) if nonce else "",
        },
    )


def bootstrap(env: dict[str, str], url: str) -> Admin:
    """The first user of a running service, the way an operator makes it:
    `users create-admin` on the host prints a one-time password, the UI
    asks for one of the user's own, and the user's page makes a token."""
    made = subprocess.run(
        [program("benethos-mailbox-service"), "users", "create-admin"],
        env=env,
        cwd=run_dir(env),
        check=True,
        capture_output=True,
        text=True,
    )
    one_time = made.stdout.strip()
    own = secrets.token_urlsafe(18)
    with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as browser:
        asked = ui_sign_in(browser, "admin", one_time)
        if asked.url.path != "/ui/password":
            sys.exit("bootstrap: the one-time password did not lead to /ui/password")
        changed = browser.post(
            "/ui/password",
            data={
                "csrf_token": csrf_of(asked.text),
                "current_password": one_time,
                "new_password": own,
                "repeat_password": own,
            },
        )
        users = browser.get("/ui/users").text
        user_id = re.search(r'href="/ui/users/(usr_[0-9a-f]+)"', users)
        if "Password changed." not in changed.text or user_id is None:
            sys.exit("bootstrap: the password or the user page did not work")
        made_token = browser.post(
            f"/ui/users/{user_id.group(1)}/tokens",
            data={"csrf_token": csrf_of(users), "name": "live check"},
        )
        token = re.search(r'<code class="secret">([^<]+)</code>', made_token.text)
        if token is None:
            sys.exit("bootstrap: no token on the user page")
    return Admin("admin", own, token.group(1))


def user_token(
    mailbox: SyncMailboxClient,
    account_ids: list[str],
    allow: list[str],
    **constraints: Any,
) -> str:
    """A user with ``allow`` on the accounts, and a token for it. User
    names are unique, so each gets a random end."""
    user = mailbox.request(
        "POST",
        "/v1/users",
        json={
            "name": f"live check {'+'.join(allow)} {secrets.token_hex(3)}",
            "grants": [{"accounts": account_ids, "allow": allow, **constraints}],
        },
    )
    created = mailbox.request(
        "POST", f"/v1/users/{user['id']}/tokens", json={"name": "live"}
    )
    return str(created["token"])


def admin_token(services: Services, name: str = "live") -> str:
    """A token of a new user with every right, for a script that runs the
    services in its own process."""
    caller = Access("usr_live_script", "live script", [], service=ADMIN_SERVICE)
    user = services.users.create_user(caller, name, [], [], service=[permissions.ADMIN])
    return services.auth.issue_token(user.id, "live check")[1]
