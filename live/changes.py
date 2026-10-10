"""Live check of sending, IDLE, changing a message, folders, and ids that
survive moves.

    uv run python live/changes.py [--keep]

Writes, on the first two test accounts in ``live/.env`` and nowhere else:

1. watches the inbox of account 1 over IDLE,
2. sends one test mail through the API from account 2 to account 1, and
   checks the read copy in account 2's sent folder,
3. checks that IDLE reported it and that the API lists it,
4. marks it read, starred, with a keyword, and back, through the API,
5. creates a folder and moves the mail into it through the API: the id
   stays,
6. moves it back the way another mail client would: the id still answers,
   and, where the server offers CONDSTORE, flags it the same way: the
   change feed names that,
7. replies and forwards through the API, back to account 2 only, and
   checks the flags on the original,
8. renames and deletes the folder, runs a batch, stores, replaces and
   deletes a reply draft, and sends a draft to account 2,
9. deletes the mail through the API, into the trash, then for good, and
   the sent copy,
10. checks that the change feed names the mail as created, updated and
   deleted, and that a webhook on a receiver of its own at 127.0.0.1
   hears the same, signed, with the send as well.

With ``--keep`` the mail stays in the inbox and the copy in the sent
folder, to look at in a mail client.

Nothing else in the mailboxes is touched. The service runs in-process with
memory storage and a throwaway master key. Credentials are never printed.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import anyio
from checks.accounts import accounts, read_env, register
from checks.changes_stages import (
    batch,
    condstore,
    deleted,
    flags,
    folder_renamed_and_deleted,
    into_a_folder,
    moved_back_by_another,
    reply_and_forward,
)
from checks.changes_trip import Trip, clean_up, find_by_subject
from checks.imap import OtherClient
from checks.mail import feed_types
from checks.receiver import Receiver
from checks.run import Run
from checks.service import in_process_service, mailbox_of

from benethos_mailbox_service.errors import MailboxServiceError

IDLE_WAIT = 90.0
TEXT = (
    "Automatic test mail of live/changes.py in the mailbox-service repository.\n"
    "It deletes itself when the check is over.\n"
)
KEPT_TEXT = (
    "Automatic test mail of live/changes.py in the mailbox-service repository.\n"
    "It was kept for inspection (--keep): delete it by hand.\n"
)


async def idle_while_sending(provider: Any, send: Any) -> bool:
    """Start IDLE, send once IDLE runs, and return what IDLE reported."""
    result: dict[str, bool] = {}

    async def watch() -> None:
        result["changed"] = await provider.wait_for_change(IDLE_WAIT)

    async with anyio.create_task_group() as group:
        group.start_soon(watch)
        # Login and SELECT of the IDLE connection take a moment. A mail
        # that arrives before IDLE starts would not be reported.
        await anyio.sleep(5)
        await anyio.to_thread.run_sync(send)
    return result.get("changed", False)


def connect(trip: Trip) -> bool:
    """Both test accounts, the change feed's start, a webhook."""
    client, run = trip.client, trip.run
    account_id, _ = register(trip.mailbox, trip.env, trip.receiver)
    sender_id, _ = register(trip.mailbox, trip.env, trip.sender)
    if not run.check(
        "connect both test accounts, the sender with SMTP",
        account_id is not None and sender_id is not None,
    ):
        return False
    assert account_id is not None and sender_id is not None
    trip.account_id, trip.sender_id = account_id, sender_id
    anyio.run(trip.services.sync.sync_account, account_id)
    trip.since = client.get(f"/v1/accounts/{account_id}/changes").json()["state"]
    trip.hooked = Receiver()
    trip.hook = client.post(
        "/v1/webhooks",
        json={"url": trip.hooked.url, "accounts": [account_id, sender_id]},
    ).json()
    return True


def send_under_idle(trip: Trip) -> bool:
    """Send from account 2 while IDLE watches account 1, once more with
    the same key, and look for the read copy in the sender's sent folder."""
    client, run = trip.client, trip.run
    provider = trip.services.adapters.get(trip.account_id)
    answer: dict[str, Any] = {}
    send_url = f"/v1/accounts/{trip.sender_id}/send"
    # Only ever to the other test account.
    outgoing = {
        "to": [{"email": trip.receiver["email"]}],
        "subject": trip.subject,
        "text": KEPT_TEXT if trip.keep else TEXT,
    }
    once = {"Idempotency-Key": f"live-{trip.token}"}

    def send() -> None:
        response = client.post(send_url, json=outgoing, headers=once)
        answer["status"], answer["body"] = response.status_code, response.json()

    try:
        changed = anyio.run(idle_while_sending, provider, send)
        run.check("IDLE reports the new mail", changed)
    except MailboxServiceError as exc:
        run.check("IDLE reports the new mail", False, f"{exc.code}: {exc.message}")
    body = answer.get("body", {})
    run.check(
        "POST send: the server accepted it",
        answer.get("status") == 200 and body.get("refused") == [],
        f"{answer.get('status')} {body.get('error', '')}",
    )
    retry = client.post(send_url, json=outgoing, headers=once)
    run.check(
        "a retry with the same Idempotency-Key returns the first result",
        retry.status_code == 200 and retry.json() == body,
        str(retry.status_code),
    )
    trip.sent_copy_id = body.get("sent_copy_id")
    check_sent_copy(trip)
    return True


def check_sent_copy(trip: Trip) -> None:
    outbox = OtherClient(trip.env, trip.sender)
    try:
        sent_folder = outbox.sent_folder()
        trip.run.check(
            "a read copy in the sender's sent folder",
            bool(trip.sent_copy_id)
            and sent_folder is not None
            and outbox.flags(sent_folder, trip.subject) == ["\\Seen"],
            str(sent_folder),
        )
    finally:
        outbox.close()


def listed(trip: Trip) -> bool:
    """The API lists the mail, with a date, and the feed names it."""
    run = trip.run
    found = find_by_subject(trip.mailbox, trip.account_id, trip.subject)
    if not run.check("the API lists it", found is not None):
        return False
    assert found is not None
    run.check("it has a date", found.date is not None, str(found.date))
    trip.message_id = found.id
    trip.inbox_folder = found.folder_ids[0]
    types = feed_types(trip.mailbox, trip.account_id, trip.since, trip.message_id)
    run.check(
        "the change feed names it as created",
        types == ["message.created"],
        " ".join(types),
    )
    return True


def webhook(trip: Trip) -> bool:
    """The webhook at 127.0.0.1 heard the same, signed, and the send."""
    assert trip.hooked is not None
    anyio.run(trip.services.deliveries.deliver_due)
    heard = trip.hooked.events()
    mail = [e["type"] for e in heard if e["id"] == trip.message_id]
    trip.run.check(
        "a webhook at 127.0.0.1 hears of it, signed",
        trip.hooked.signed(trip.hook.get("secret", ""))
        and mail[:1] == ["message.created"]
        and "message.updated" in mail,
        f"{len(trip.hooked.posts)} posts, " + " ".join(dict.fromkeys(mail)),
    )
    trip.run.check(
        "and of the send",
        any(
            e["type"] == "message.sent" and e["account_id"] == trip.sender_id
            for e in heard
        ),
    )
    trip.hooked.close()
    return True


# In order: one that answers False ends the run, with what failed named.
STAGES = (
    connect,
    send_under_idle,
    listed,
    flags,
    into_a_folder,
    moved_back_by_another,
    condstore,
    reply_and_forward,
    batch,
    folder_renamed_and_deleted,
    deleted,
    webhook,
)


def finish(trip: Trip) -> None:
    """Without ``--keep`` the test mail and the folder go, wherever they
    are. With it, the folder goes and the mail stays."""
    if trip.keep:
        if trip.other is not None:
            trip.other.delete_folder(trip.other.folder_name(trip.base))
            trip.other.close()
        print(
            f"\n== kept: '{trip.subject}' in the inbox of {trip.receiver['email']} "
            "and in the Sent folder of the sender: delete them by hand"
        )
    else:
        clean_up(
            trip.env, trip.receiver, trip.sender, trip.other, trip.base, trip.subject
        )
    anyio.run(trip.services.aclose)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the test mail and its folder, and put a copy into the "
        "sender's Sent folder, to look at in a mail client",
    )
    keep = parser.parse_args().keep
    env = read_env()
    listed_accounts = accounts(env)
    if len(listed_accounts) < 2 or "LIVE_IMAP_HOST" not in env:
        sys.exit("needs two test accounts and LIVE_IMAP_HOST")
    services, client = in_process_service()
    trip = Trip(
        env,
        receiver=listed_accounts[0],
        sender=listed_accounts[1],
        keep=keep,
        services=services,
        client=client,
        mailbox=mailbox_of(client),
        run=Run(),
    )
    print(f"== {trip.receiver['email']} receives from {trip.sender['email']}")
    try:
        for stage in STAGES:
            if not stage(trip):
                return 1
    finally:
        finish(trip)
    return trip.run.finish()


if __name__ == "__main__":
    sys.exit(main())
