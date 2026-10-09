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

from checks.accounts import accounts, read_env, register
from checks.run import Run

from benethos_mailbox_client import ApiError, SyncMailboxClient

DEFAULT_URL = "http://127.0.0.1:8080"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--count", type=int, default=2)
    options = parser.parse_args()
    token = os.environ.get("MAILBOX_SERVICE_TOKEN")
    if not token:
        sys.exit(
            "set MAILBOX_SERVICE_TOKEN to a token with accounts.connect, "
            "and accounts.manage and mail.read on every account"
        )
    env = read_env()
    run = Run()
    with SyncMailboxClient(options.url, token) as mailbox:
        for account in accounts(env)[: options.count]:
            print(f"\n== {account['email']}")
            account_id, outcome = register(mailbox, env, account)
            if account_id is None:
                run.check("in the service", False, outcome)
                continue
            run.check("in the service", True, outcome)
            run.check("its id", True, account_id)
            check_account(run, mailbox, account_id)
    return run.finish()


def check_account(run: Run, mailbox: SyncMailboxClient, account_id: str) -> None:
    """Verify, the folders, the newest of the inbox, the status: each a
    check, a refusal of the API named with its code."""
    try:
        verified = mailbox.verify_account(account_id)
        run.check("verify logs in over IMAP and SMTP", True, verified.status)
        roles = sorted(f.role for f in mailbox.list_folders(account_id) if f.role)
        run.check("folders", True, ", ".join(roles) or "no roles")
        inbox = mailbox.list_messages(account_id, limit=3)
        run.check("the inbox lists", True, f"{len(inbox.items)} shown")
        status = mailbox.get_account(account_id).status
        run.check("status", status == "connected", status)
    except ApiError as exc:
        run.check("the account answers", False, f"{exc.status} {exc.code}")


if __name__ == "__main__":
    sys.exit(main())
