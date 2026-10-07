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
import imaplib
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

import anyio
from checks.accounts import accounts, read_env, register
from checks.imap import OtherClient
from checks.mail import feed_types, messages_with_subject
from checks.receiver import Receiver
from checks.run import Run
from checks.service import in_process_service, mailbox_of
from fastapi.testclient import TestClient

from benethos_mailbox_client import SyncMailboxClient
from benethos_mailbox_service.errors import MailboxServiceError

IDLE_WAIT = 90.0
FLAGGED = chr(92) + "Flagged"
# How long the mail may take from SMTP to the inbox.
DELIVERY_TRIES = 10
DELIVERY_PAUSE = 3.0
# Set and cleared again on the test mail.
LIVE_KEYWORD = "$mailbox-service-live"
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


def check_drafts(
    run: Run,
    client: TestClient,
    mailbox: SyncMailboxClient,
    other: OtherClient,
    account_id: str,
    message_id: str,
    subject: str,
    sender_id: str,
    sender_email: str,
) -> None:
    """A reply draft to the test mail: stored, replaced, listed, deleted
    and never sent. Then a draft sent to account 2."""
    drafts = other.drafts_folder()
    url = f"/v1/accounts/{account_id}/drafts"
    reply = f"Re: {subject}"
    created = client.post(
        url,
        json={
            "reference": {"message_id": message_id, "action": "reply"},
            "text": "Automatic draft of live/changes.py, never sent.",
        },
    )
    draft_id = created.json().get("id", "?")
    run.check(
        "POST drafts stores a draft, another client sees it",
        created.status_code == 201
        and drafts is not None
        and "\\Draft" in other.flags(drafts, reply),
        f"{created.status_code}, {drafts}",
    )
    replaced = client.put(
        f"{url}/{draft_id}",
        json={
            "reference": {"message_id": message_id, "action": "reply"},
            "text": "Automatic draft of live/changes.py, replaced, never sent.",
        },
    )
    run.check(
        "PUT replaces it, the id stays, the old one is gone",
        replaced.status_code == 200
        and replaced.json().get("id") == draft_id
        and drafts is not None
        and len(other.uids(drafts, reply)) == 1,
        str(replaced.status_code),
    )
    listed = [d["id"] for d in client.get(url).json().get("items", [])]
    run.check("GET drafts lists it", draft_id in listed)
    deleted = client.delete(f"{url}/{draft_id}")
    run.check(
        "DELETE removes it for good",
        deleted.status_code == 204
        and drafts is not None
        and not other.uids(drafts, reply),
        str(deleted.status_code),
    )

    # Sent to account 2, the one other test account: nobody else.
    title = f"{subject} draft"
    to_send = client.post(
        url,
        json={
            "to": [{"email": sender_email}],
            "subject": title,
            "text": "Automatic draft of live/changes.py, sent to the test account.",
        },
    )
    send_id = to_send.json().get("id", "?")
    sent = client.post(f"{url}/{send_id}/send")
    arrived = find_by_subject(mailbox, sender_id, title)
    run.check(
        "POST drafts/{id}/send sends it, it arrives, the draft is gone",
        sent.status_code == 200
        and arrived is not None
        and drafts is not None
        and not other.uids(drafts, title),
        str(sent.status_code),
    )


def find_by_subject(
    mailbox: SyncMailboxClient, account_id: str, subject: str
) -> dict[str, Any] | None:
    found = messages_with_subject(
        mailbox, account_id, subject, tries=DELIVERY_TRIES, pause=DELIVERY_PAUSE
    )
    return found[0] if found else None


def clean_up(
    env: dict[str, str],
    receiver: dict[str, str],
    sender: dict[str, str],
    other: OtherClient | None,
    base: str,
    subject: str,
) -> None:
    """Delete the test mail wherever it is, its copy in the sender's sent
    folder, and the test folder."""
    if other is None:
        try:
            other = OtherClient(env, receiver)
        except (imaplib.IMAP4.error, OSError) as exc:
            print(f"cleanup failed, remove '{subject}' by hand: {exc}")
            return
    # A subject search finds the replies and forwards ("Re: ...") too.
    folders = [other.folder_name(base), other.folder_name(base + "-renamed")]
    places = [
        *folders,
        "INBOX",
        other.trash_folder(),
        other.sent_folder(),
        other.drafts_folder(),
    ]
    removed = sum(other.delete_mail(place, subject) for place in places if place)
    left = [f for f in folders if f in other.all_folders()]
    for folder in left:
        other.delete_folder(folder)
    other.close()
    try:
        outbox = OtherClient(env, sender)
    except (imaplib.IMAP4.error, OSError) as exc:
        print(f"cleanup failed, remove the sent copy of '{subject}' by hand: {exc}")
        return
    for place in ("INBOX", outbox.sent_folder(), outbox.trash_folder()):
        removed += outbox.delete_mail(place, subject) if place else 0
    outbox.close()
    print(
        f"\n== cleanup: {removed} test mail(s) and {len(left)} leftover "
        "folder(s) deleted"
    )


@dataclass
class Trip:
    """One run of the check: the test accounts, the test mail, the service
    and what the stages learn on the way."""

    env: dict[str, str]
    receiver: dict[str, str]
    sender: dict[str, str]
    keep: bool
    services: Any
    client: TestClient
    mailbox: SyncMailboxClient
    run: Run
    token: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    other: OtherClient | None = None
    account_id: str = ""
    sender_id: str = ""
    since: str = ""
    hooked: Receiver | None = None
    hook: dict[str, Any] = field(default_factory=dict)
    message_id: str = ""
    inbox_folder: str = ""
    sent_copy_id: str | None = None
    folder: str = ""
    test_folder: str = "?"

    @property
    def subject(self) -> str:
        return f"mailbox-service live check {self.token}"

    @property
    def base(self) -> str:
        return f"mailbox-service-live-{self.token}"

    @property
    def message_url(self) -> str:
        return f"/v1/accounts/{self.account_id}/messages/{self.message_id}"

    @property
    def folders_url(self) -> str:
        return f"/v1/accounts/{self.account_id}/folders"

    def seen_by_other(self) -> OtherClient:
        """The receiver's mailbox as another mail client sees it."""
        if self.other is None:
            self.other = OtherClient(self.env, self.receiver)
        return self.other


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
    run.check("it has a date", found.get("date") is not None, str(found.get("date")))
    trip.message_id = found["id"]
    trip.inbox_folder = found["folder_ids"][0]
    types = feed_types(trip.mailbox, trip.account_id, trip.since, trip.message_id)
    run.check(
        "the change feed names it as created",
        types == ["message.created"],
        " ".join(types),
    )
    return True


def flags(trip: Trip) -> bool:
    """Read, starred, with a keyword through the API, as another client
    sees it, and back."""
    client, run, other, subject = (
        trip.client,
        trip.run,
        trip.seen_by_other(),
        trip.subject,
    )
    patched = client.patch(
        trip.message_url,
        json={"unread": False, "starred": True, "keywords": [LIVE_KEYWORD]},
    )
    run.check(
        "PATCH marks it read, starred, with a keyword",
        patched.status_code == 200
        and patched.json().get("id") == trip.message_id
        and patched.json().get("keywords") == [LIVE_KEYWORD],
        str(patched.status_code),
    )
    seen = other.flags("INBOX", subject)
    run.check(
        "another client sees the flags",
        {"\\Seen", "\\Flagged", LIVE_KEYWORD} <= set(seen),
        " ".join(seen),
    )
    client.patch(
        trip.message_url, json={"unread": True, "starred": False, "keywords": []}
    )
    run.check(
        "and back to unread, no star, no keyword",
        other.flags("INBOX", subject) == [],
        " ".join(other.flags("INBOX", subject)),
    )
    return True


def into_a_folder(trip: Trip) -> bool:
    """A new folder through the API, the mail moved into it: the id stays."""
    client, run, other = trip.client, trip.run, trip.seen_by_other()
    created = client.post(trip.folders_url, json={"name": trip.base})
    trip.folder = other.folder_name(trip.base)
    run.check(
        "POST creates a folder, subscribed, in the personal namespace",
        created.status_code == 201
        and created.json().get("subscribed") is True
        and trip.folder in other.subscribed_folders(),
        f"{created.status_code}, {trip.folder}",
    )
    names = {f["name"]: f["id"] for f in client.get(trip.folders_url).json()}
    trip.test_folder = names.get(trip.base, "?")
    moved = client.patch(trip.message_url, json={"folder_ids": [trip.test_folder]})
    run.check(
        "PATCH moves it, and the id stays",
        moved.status_code == 200
        and moved.json().get("id") == trip.message_id
        and moved.json().get("folder_ids") == [names.get(trip.base)],
        str(moved.status_code),
    )
    run.check(
        "another client finds it there, not in the inbox",
        len(other.uids(trip.folder, trip.subject)) == 1
        and not other.uids("INBOX", trip.subject),
    )
    return True


def moved_back_by_another(trip: Trip) -> bool:
    """Another client moves the mail back: the same id finds it."""
    client, run, other = trip.client, trip.run, trip.seen_by_other()
    uids = other.uids(trip.folder, trip.subject)
    if not run.check("another client moves it back", len(uids) == 1):
        return False
    other.move(uids[0], "INBOX")
    back = client.get(trip.message_url)
    run.check(
        "the same id finds it in the inbox again",
        back.status_code == 200
        and back.json().get("folder_ids") == [trip.inbox_folder],
        str(back.status_code),
    )
    run.check(
        "the subject matches",
        back.status_code == 200 and back.json().get("subject") == trip.subject,
    )
    return True


def condstore(trip: Trip) -> bool:
    """A flag another client sets reaches the change feed, where the
    server offers CONDSTORE."""
    other = trip.seen_by_other()
    if "CONDSTORE" not in other.capabilities():
        print("SKIP  the server offers no CONDSTORE")
        return True
    sync = trip.services.sync.sync_account
    anyio.run(sync, trip.account_id)
    changes = f"/v1/accounts/{trip.account_id}/changes"
    mark = trip.client.get(changes).json()["state"]
    other.set_flag("INBOX", trip.subject, FLAGGED, on=True)
    anyio.run(sync, trip.account_id)
    types = feed_types(trip.mailbox, trip.account_id, mark, trip.message_id)
    trip.run.check(
        "the change feed names a flag another client set (CONDSTORE)",
        types == ["message.updated"],
        " ".join(types),
    )
    other.set_flag("INBOX", trip.subject, FLAGGED, on=False)
    return True


def reply_and_forward(trip: Trip) -> bool:
    """Answered by account 1, so both go back to account 2 only."""
    client, run, other, subject = (
        trip.client,
        trip.run,
        trip.seen_by_other(),
        trip.subject,
    )
    send_url = f"/v1/accounts/{trip.account_id}/send"
    replied = client.post(
        send_url,
        json={
            "reference": {"message_id": trip.message_id, "action": "reply"},
            "text": "Automatic reply of live/changes.py.",
        },
    )
    reply = find_by_subject(trip.mailbox, trip.sender_id, f"Re: {subject}")
    run.check(
        "a reply goes back to the sender, as a reply",
        replied.status_code == 200 and reply is not None,
        str(replied.status_code),
    )
    run.check(
        "the original is marked answered",
        "\\Answered" in other.flags("INBOX", subject),
        " ".join(other.flags("INBOX", subject)),
    )
    forwarded = client.post(
        send_url,
        json={
            "reference": {
                "message_id": trip.message_id,
                "action": "forward",
                "forward_as": "attachment",
            },
            "to": [{"email": trip.sender["email"]}],
            "text": "Automatic forward of live/changes.py.",
        },
    )
    forward = find_by_subject(trip.mailbox, trip.sender_id, f"Fwd: {subject}")
    run.check(
        "a forward as attachment arrives",
        forwarded.status_code == 200 and forward is not None,
        str(forwarded.status_code),
    )
    run.check(
        "the original is marked forwarded",
        "$Forwarded" in other.flags("INBOX", subject),
        " ".join(other.flags("INBOX", subject)),
    )
    return True


def batch(trip: Trip) -> bool:
    """A batch answers per id, the feed names the changes, then the drafts."""
    client, run, other = trip.client, trip.run, trip.seen_by_other()
    answered = client.post(
        f"/v1/accounts/{trip.account_id}/messages/batch",
        json={
            "action": "update",
            "ids": [trip.message_id, "msg_does_not_exist"],
            "changes": {"starred": True},
        },
    )
    outcomes = [r["ok"] for r in answered.json().get("results", [])]
    run.check(
        "a batch answers per id",
        answered.status_code == 200
        and outcomes == [True, False]
        and "\\Flagged" in other.flags("INBOX", trip.subject),
        f"{answered.status_code} {outcomes}",
    )
    types = feed_types(trip.mailbox, trip.account_id, trip.since, trip.message_id)
    run.check(
        "the change feed names its changes as updated",
        "message.updated" in types,
        " ".join(types),
    )
    check_drafts(
        run,
        client,
        trip.mailbox,
        other,
        trip.account_id,
        trip.message_id,
        trip.subject,
        trip.sender_id,
        trip.sender["email"],
    )
    return True


def folder_renamed_and_deleted(trip: Trip) -> bool:
    client, run, other = trip.client, trip.run, trip.seen_by_other()
    renamed = client.patch(
        f"{trip.folders_url}/{trip.test_folder}", json={"name": trip.base + "-renamed"}
    )
    new_name = other.folder_name(trip.base + "-renamed")
    run.check(
        "PATCH renames the folder, the subscription goes along",
        renamed.status_code == 200
        and new_name in other.subscribed_folders()
        and trip.folder not in other.subscribed_folders(),
        str(renamed.status_code),
    )
    removed = client.delete(f"{trip.folders_url}/{renamed.json().get('id', '?')}")
    run.check(
        "DELETE removes the empty folder",
        removed.status_code == 204 and new_name not in other.all_folders(),
        str(removed.status_code),
    )
    return True


def deleted(trip: Trip) -> bool:
    """Into the trash, then for good, and the sender's copy: not with
    ``--keep``."""
    if trip.keep:
        return True
    client, run, other, url = (
        trip.client,
        trip.run,
        trip.seen_by_other(),
        trip.message_url,
    )
    trash = other.trash_folder()
    first = client.delete(url)
    run.check(
        "DELETE moves it into the trash",
        first.status_code == 204
        and trash is not None
        and len(other.uids(trash, trip.subject)) == 1
        and not other.uids("INBOX", trip.subject),
        f"{first.status_code}, {trash}",
    )
    again = client.delete(url)
    run.check(
        "from the trash only with permanent=true",
        again.status_code == 409,
        str(again.status_code),
    )
    gone = client.delete(url, params={"permanent": True})
    run.check(
        "DELETE permanent=true removes it for good",
        gone.status_code == 204
        and trash is not None
        and not other.uids(trash, trip.subject)
        and client.get(url).status_code == 404,
        str(gone.status_code),
    )
    types = feed_types(trip.mailbox, trip.account_id, trip.since, trip.message_id)
    run.check(
        "the change feed names it as deleted, last",
        types[-1:] == ["message.deleted"],
        " ".join(types),
    )
    if trip.sent_copy_id:
        copy_gone = client.delete(
            f"/v1/accounts/{trip.sender_id}/messages/{trip.sent_copy_id}",
            params={"permanent": True},
        )
        run.check(
            "and the sender's copy too",
            copy_gone.status_code == 204,
            str(copy_gone.status_code),
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
