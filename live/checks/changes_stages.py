"""The stages of ``live/changes.py`` that change the test mail once it is
there: flags, a folder of its own, a move by another client, replies and
forwards, a batch, drafts, and deleting it."""

from __future__ import annotations

import anyio
from fastapi.testclient import TestClient

from benethos_mailbox_client import SyncMailboxClient

from .changes_trip import Trip, find_by_subject
from .imap import OtherClient
from .mail import feed_types
from .run import Run

FLAGGED = chr(92) + "Flagged"
# Set and cleared again on the test mail.
LIVE_KEYWORD = "$mailbox-service-live"


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
