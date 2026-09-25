"""Register the test accounts of ``live/.env`` in a running service, through
its REST API, and check that they work.

    MAILBOX_SERVICE_TOKEN=... uv run python live/register.py [--url URL] [--count N]

For each of the first ``N`` test accounts (default 2): discovery for its
address, ``POST /v1/accounts`` with IMAP and the SMTP server discovery
finds, then ``verify``, its folders and the newest messages of its inbox.
An account whose address the service has already is not added again, only
checked. Nothing in the mailboxes is written. Credentials are never printed.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from _common import Run, accounts, read_env, register

DEFAULT_URL = "http://127.0.0.1:8080"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--count", type=int, default=2)
    options = parser.parse_args()
    token = os.environ.get("MAILBOX_SERVICE_TOKEN")
    if not token:
        sys.exit(
            "set MAILBOX_SERVICE_TOKEN to a token with accounts.manage and mail.read"
        )
    env = read_env()
    run = Run()
    with httpx.Client(
        base_url=options.url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    ) as client:
        for account in accounts(env)[: options.count]:
            print(f"\n== {account['email']}")
            account_id, outcome = register(client, env, account)
            if not run.check("in the service", account_id is not None, outcome):
                continue
            base = f"/v1/accounts/{account_id}"
            record = client.get(base).json()
            run.check("its id", True, str(account_id))
            verified = client.post(f"{base}/verify")
            run.check(
                "verify logs in over IMAP and SMTP",
                verified.status_code == 200,
                str(verified.status_code),
            )
            folders = client.get(f"{base}/folders")
            roles = sorted(f["role"] for f in folders.json() if f.get("role"))
            run.check(
                "folders", folders.status_code == 200, ", ".join(roles) or "no roles"
            )
            inbox = client.get(f"{base}/messages", params={"limit": 3})
            run.check(
                "the inbox lists",
                inbox.status_code == 200,
                f"{len(inbox.json().get('items', []))} shown",
            )
            status = client.get(base).json().get("status", record.get("status"))
            run.check("status", status == "connected", str(status))
    return run.finish()


if __name__ == "__main__":
    sys.exit(main())
