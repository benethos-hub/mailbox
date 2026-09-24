"""Live check of the configuration UI against the test accounts.

    uv run python live/ui.py

Starts a service of its own with a throwaway database, as mcp_stdio.py
does, adds the first two test accounts through the API, and then uses the
UI the way a browser does: signs in with the admin key, opens the pages
and follows their forms. Nothing in the mailboxes is written. Credentials
and mail content are never printed.
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
from smoke import ENV_FILE, Run, accounts, read_env


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
            for number, account in enumerate(test_accounts, 1):
                account_id, outcome = register(client, env, account)
                if not run.check(
                    f"account {number} in the service", account_id is not None, outcome
                ):
                    return 1
        with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as browser:
            print("\n== signing in")
            if not run.check("sign in with the admin key", sign_in(browser, admin_key)):
                return 1
            check_frame(run, browser, [a["email"].lower() for a in test_accounts])
    finally:
        process.terminate()
        process.wait(timeout=10)
        shutil.rmtree(Path(data_dir), ignore_errors=True)
    print(f"\n{run.failures} failed" if run.failures else "\nall passed")
    return 1 if run.failures else 0


if __name__ == "__main__":
    sys.exit(main())
