"""Register the test accounts of ``live/.env`` in a running service, through
its REST API, and check that they work.

    MAILBOX_SERVICE_TOKEN=... uv run python live/register.py [--url URL] [--count N]
    uv run python live/register.py --own-service [--count N]

For each of the first ``N`` test accounts (default 2): discovery for its
address, ``POST /v1/accounts`` with IMAP and the SMTP server discovery
finds, then ``verify``, its folders and the newest messages of its inbox.
An account whose address the service has already is not added again, only
checked. Nothing in the mailboxes is written. Credentials are never printed.

With ``--own-service`` it starts a service of its own on a free port, with
a database of its own, makes its admin as an operator does and uses the
admin's token. The service and its folder are removed afterwards.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

from checks.accounts import accounts, read_env, register
from checks.admin import bootstrap
from checks.processes import free_port, service_env, start_service, stop
from checks.run import Run

from benethos_mailbox_client import ApiError, SyncMailboxClient

DEFAULT_URL = "http://127.0.0.1:8080"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--url", default=DEFAULT_URL)
    where.add_argument("--own-service", action="store_true")
    parser.add_argument("--count", type=int, default=2)
    options = parser.parse_args()
    if options.own_service:
        return with_own_service(options.count)
    token = os.environ.get("MAILBOX_SERVICE_TOKEN")
    if not token:
        sys.exit(
            "set MAILBOX_SERVICE_TOKEN to a token with accounts.connect, "
            "and accounts.manage and mail.read on every account, "
            "or use --own-service"
        )
    return check_all(options.url, token, options.count)


def with_own_service(count: int) -> int:
    """The checks against a service of its own, removed afterwards."""
    data_dir = tempfile.mkdtemp(prefix="mailbox-register-")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    service = service_env(data_dir, port)
    process = start_service(service, url)
    try:
        return check_all(url, bootstrap(service, url).token, count)
    finally:
        stop(process)
        shutil.rmtree(data_dir, ignore_errors=True)


def check_all(url: str, token: str, count: int) -> int:
    """Each of the first ``count`` test accounts in the service at
    ``url``: added, then checked."""
    env = read_env()
    run = Run()
    with SyncMailboxClient(url, token) as mailbox:
        for account in accounts(env)[:count]:
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
