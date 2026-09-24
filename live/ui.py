"""Live check of the configuration UI against the test accounts.

    uv run python live/ui.py

Starts a service of its own with a throwaway database, as mcp_stdio.py
does, adds the first test account through the API, and then uses the UI
the way a browser does: signs in with the admin key, connects the second
test account through discovery and the form, makes a user, a role and a
token and signs in with that token, opens the pages and follows their
forms. Nothing in the mailboxes is written. Credentials and mail
content are never printed.
"""

from __future__ import annotations

import re
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

import httpx
from mcp_stdio import free_port, service_env, start_service
from register import register
from smoke import ENV_FILE, Run, accounts, imap_settings, read_env


def sign_in(browser: httpx.Client, token: str) -> bool:
    page = browser.get("/ui/login")
    nonce = re.search(r'name="nonce" value="([^"]+)"', page.text)
    if nonce is None:
        return False
    answer = browser.post("/ui/login", data={"token": token, "nonce": nonce.group(1)})
    return answer.status_code == 200 and "Signed in as" in answer.text


def check_frame(run: Run, browser: httpx.Client, emails: list[str]) -> None:
    home = browser.get("/ui")
    run.check(
        "the overview lists the test accounts",
        home.status_code == 200 and all(e in home.text.lower() for e in emails),
    )
    run.check(
        "the admin key is warned: reads and sends anywhere",
        "reads and sends anywhere" in home.text,
    )
    run.check(
        "security headers",
        "frame-ancestors 'none'" in home.headers.get("content-security-policy", ""),
    )


def csrf_of(html: str) -> str:
    found = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return found.group(1) if found else ""


def check_accounts(
    run: Run,
    browser: httpx.Client,
    env: dict[str, str],
    account: dict[str, str],
    admin_key: str,
) -> str | None:
    """The second test account, connected through the UI; its id."""
    csrf = csrf_of(browser.get("/ui/accounts").text)
    found = browser.post(
        "/ui/accounts/discover", data={"csrf_token": csrf, "email": account["email"]}
    )
    run.check(
        "discovery answers on the page",
        found.status_code == 200 and "What the sources answered" in found.text,
    )
    host = re.search(r'name="host" value="([^"]*)"', found.text)
    fields = {
        key: str(value)
        for key, value in imap_settings(
            env, account, {"host": host.group(1) if host else ""}
        ).items()
    }
    created = browser.post(
        "/ui/accounts",
        data={
            "csrf_token": csrf,
            "email": account["email"],
            "provider": "imap",
            "password": account["password"],
            **fields,
        },
    )
    account_id = created.url.path.rpartition("/")[2]
    if not run.check(
        "connect through the form",
        created.status_code == 200 and account_id.startswith("acc_"),
        "connected" if "connected." in created.text else "not connected",
    ):
        return None
    listed = browser.get("/ui/accounts").text
    run.check("both test accounts in the list", listed.count("/ui/accounts/acc_") >= 2)
    verified = browser.post(
        f"/ui/accounts/{account_id}/verify", data={"csrf_token": csrf}
    )
    run.check(
        "verify signs in to the provider",
        "Status: connected." in verified.text,
    )
    renamed = browser.post(
        f"/ui/accounts/{account_id}",
        data={"csrf_token": csrf, "display_name": "UI live check"},
    )
    run.check("rename", "Saved." in renamed.text and "UI live check" in renamed.text)
    detail = browser.get(f"/ui/accounts/{account_id}").text
    host_shown = re.search(r'name="host" value="([^"]+)"', detail)
    run.check(
        "the form shows the servers, never the password",
        host_shown is not None and account["password"] not in detail,
    )
    api = browser.get(
        f"/v1/accounts/{account_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    ).text
    run.check(
        "the API shows the settings, never the password",
        "host" in api and account["password"] not in api,
    )
    return account_id


def check_users(run: Run, browser: httpx.Client, url: str, account_id: str) -> None:
    """A reader of the first test account made through the pages, its
    token, a sign-in with it, and the token revoked."""
    csrf = csrf_of(browser.get("/ui/users").text)
    role = browser.post(
        "/ui/roles",
        data={
            "csrf_token": csrf,
            "id": "ui-live-reader",
            "grants": "1",
            "g0_accounts": account_id,
            "g0_allow": ["accounts.read", "mail.read"],
        },
    )
    run.check("create a role", "Role ui-live-reader created." in role.text)
    created = browser.post(
        "/ui/users",
        data={
            "csrf_token": csrf,
            "name": "ui-live-reader",
            "roles": "ui-live-reader",
            "grants": "1",
            "g0_accounts": account_id,
            "g0_allow": "send",
            "g0_recipients": "*@example.invalid",
            "g0_max": "1",
        },
    )
    user_path = created.url.path
    if not run.check(
        "create a user with a role and a narrowed grant",
        "ui-live-reader created." in created.text and "/ui/users/usr_" in user_path,
    ):
        return
    page = browser.post(
        f"{user_path}/tokens", data={"csrf_token": csrf, "name": "live", "days": "1"}
    ).text
    shown = re.search(r'<code class="secret">([^<]+)</code>', page)
    run.check("the new token is shown once", shown is not None)
    run.check(
        "and never again",
        shown is not None and shown.group(1) not in browser.get(user_path).text,
    )
    if shown is None:
        return
    with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as other:
        run.check("sign in with the new token", sign_in(other, shown.group(1)))
        home = other.get("/ui").text
        run.check(
            "it sees the first test account and may read and send",
            "mail.read" in home and "send" in home,
        )
        run.check(
            "its sending is narrowed, so no warning",
            "reads and sends anywhere" not in home,
        )
        token_id = re.search(
            r"/tokens/(tok_[0-9a-f]+)/revoke", browser.get(user_path).text
        )
        if token_id is None:
            run.check("the token can be revoked", False)
            return
        browser.post(
            f"{user_path}/tokens/{token_id.group(1)}/revoke", data={"csrf_token": csrf}
        )
        run.check(
            "a revoked token is signed out at once",
            "/ui/login" in str(other.get("/ui").url),
        )
    deleted = browser.post(f"{user_path}/delete", data={"csrf_token": csrf})
    run.check("delete the user", "User deleted" in deleted.text)
    gone = browser.post("/ui/roles/ui-live-reader/delete", data={"csrf_token": csrf})
    run.check("delete the role", "Role ui-live-reader deleted." in gone.text)


def main() -> int:
    env = read_env(ENV_FILE)
    test_accounts = accounts(env)[:2]
    run = Run()
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    admin_key = secrets.token_urlsafe(32)
    data_dir = tempfile.mkdtemp(prefix="mailbox-ui-live-")
    process = start_service(service_env(data_dir, port, admin_key), url)
    try:
        with httpx.Client(
            base_url=url, headers={"Authorization": f"Bearer {admin_key}"}, timeout=60
        ) as client:
            account_id, outcome = register(client, env, test_accounts[0])
            if not run.check(
                "account 1 in the service", account_id is not None, outcome
            ):
                return 1
        with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as browser:
            print("\n== signing in")
            if not run.check("sign in with the admin key", sign_in(browser, admin_key)):
                return 1
            print("\n== accounts")
            check_accounts(run, browser, env, test_accounts[1], admin_key)
            print("\n== users, tokens, roles")
            assert account_id is not None
            check_users(run, browser, url, account_id)
            print("\n== the frame")
            check_frame(run, browser, [a["email"].lower() for a in test_accounts])
    finally:
        process.terminate()
        process.wait(timeout=10)
        shutil.rmtree(Path(data_dir), ignore_errors=True)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
