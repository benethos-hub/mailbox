"""The mail of the Microsoft live check: sent to the first test account,
its copy in Sent Items read, answered and labelled, a large mail beside
it, and inline images read where the inbox has them."""

from __future__ import annotations

import base64
import time

import httpx

from benethos_mailbox_client import SyncMailboxClient

from .mail import feed_types, messages_with_subject, thread_holds
from .run import Run, polled

# A keyword of this check alone, set and taken off again.
KEYWORD = "mailbox-live"
# What the mail of the check says, and the file it carries.
TEXT = "Sent by the live check; deleted again at once."
FILE = b"A file of the mailbox-service live check."
# The files of the large mail: one just below the size Graph takes in
# one request, one through an upload session. About 7 MB together.
LARGE = {"below.bin": 2_999_999, "session.bin": 4_000_000}


def find(
    mailbox: SyncMailboxClient, account_id: str, folder: str, subject: str, tries: int
) -> str | None:
    """The id of the message with ``subject`` in the folder, once it is there."""
    found = messages_with_subject(
        mailbox, account_id, subject, folder=folder, tries=tries, pause=5
    )
    return found[0].id if found else None


def send_and_check(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    sending: tuple[str, str, str],
    bot: dict[str, str],
    bot_id: str,
    wait: float,
) -> None:
    """One mail with a file to the first test account. ``sending`` is the
    Microsoft account, the change feed's state before and the subject.
    ``wait`` is how long the change feed may take."""
    ms_id, since, subject = sending
    base = f"/v1/accounts/{ms_id}"
    data = base64.b64encode(FILE).decode()
    sent = client.post(
        f"{base}/send",
        json={
            "to": [{"email": bot["email"]}],
            "subject": subject,
            "text": TEXT,
            "attachments": [{"filename": "check.txt", "data": data}],
        },
    )
    if not run.check("send", sent.status_code == 200, _said(sent)):
        return
    header = sent.json().get("message_id_header")
    # Outlook.com may take minutes to deliver, seen live.
    arrived = find(mailbox, bot_id, "inbox", subject, tries=60)
    if run.check("it arrives", arrived is not None):
        there = client.get(f"/v1/accounts/{bot_id}/messages/{arrived}").json()
        said = there.get("message_id_header") == header
        run.check("under the Message-ID the send answered", said)
        mailbox.delete_message(bot_id, str(arrived), permanent=True)
    copy = find(mailbox, ms_id, "sent", subject, tries=6)
    run.check(
        "the send answered the copy's id",
        copy is not None and sent.json().get("sent_copy_id") == copy,
    )
    if copy is not None:
        types = feed_types(mailbox, ms_id, since, copy, wait=wait)
        run.check(
            "the change feed names the copy in Sent Items (Graph delta)",
            "message.created" in types,
            " ".join(types) or "nothing",
        )
    if run.check("the copy in Sent Items", copy is not None):
        _contents(run, client, base, str(copy))
        _reply(run, client, mailbox, (base, str(copy), header, subject), bot, bot_id)
        _keywords(run, client, base, str(copy))
        held, said = thread_holds(client, base, str(copy))
        run.check("its conversation holds it, by conversationId", held, said)
        # Deleted for good straight from Sent Items: the adapter goes through
        # the trash, since Graph's delete outside it only moves there. Right
        # after a move Exchange may not find the message yet, so three tries.
        for attempt in range(3):
            purged = client.delete(
                f"{base}/messages/{copy}", params={"permanent": "true"}
            )
            if purged.status_code == 204:
                break
            error = purged.json().get("error", {})
            code, text = error.get("code"), error.get("message")
            print(f"      try {attempt + 1}: {purged.status_code} {code}: {text}")
            time.sleep(3)
        run.check(
            "deleted for good", purged.status_code == 204, f"after {attempt + 1} tries"
        )
        run.check(
            "and not in the trash",
            find(mailbox, ms_id, "trash", subject, tries=1) is None,
        )


def inline(run: Run, client: httpx.Client, base: str) -> None:
    """Inline images of a mail in the inbox, where one has them, listed
    and downloaded. Graph lists none for a mail with inline images only."""
    listed = client.get(f"{base}/messages", params={"folder": "inbox", "limit": 20})
    for item in listed.json().get("items", []):
        url = f"{base}/messages/{item['id']}"
        files = client.get(url).json().get("attachments", [])
        inline = [a for a in files if a["inline"]]
        if inline:
            data = client.get(f"{url}/attachments/{inline[0]['id']}")
            run.check(
                "an inline image listed, and it downloads",
                data.status_code == 200 and len(data.content) == inline[0]["size"],
                str(data.status_code),
            )
            return
    print("      no mail with inline images among the inbox's first 20")


def _contents(run: Run, client: httpx.Client, base: str, copy: str) -> None:
    """The copy read from its MIME: the text as sent, no HTML, the file."""
    found = client.get(f"{base}/messages/{copy}").json()
    run.check(
        "its text as sent, no HTML",
        (found.get("text_body") or "").strip() == TEXT and not found.get("html_body"),
    )
    files = [a for a in found.get("attachments", []) if a["filename"] == "check.txt"]
    if run.check("its file listed", len(files) == 1):
        data = client.get(f"{base}/messages/{copy}/attachments/{files[0]['id']}")
        run.check("and it downloads", data.content == FILE, str(data.status_code))


def _reply(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    original: tuple[str, str, str | None, str],
    bot: dict[str, str],
    bot_id: str,
) -> None:
    """A reply to the copy, to the first test account: its own copy names
    the Message-ID it answers. ``original`` is the base, the copy's id,
    its Message-ID and its subject."""
    base, copy, header, subject = original
    sent = client.post(
        f"{base}/send",
        json={
            "reference": {"message_id": copy, "action": "reply", "quote": False},
            "to": [{"email": bot["email"]}],
            "text": "Answered by the live check.",
        },
    )
    if not run.check("a reply to it", sent.status_code == 200, _said(sent)):
        return
    reply = sent.json().get("sent_copy_id")

    def answers() -> str | None:
        found = client.get(f"{base}/messages/{reply}")
        return found.json().get("in_reply_to") if found.status_code == 200 else None

    said = polled(answers, 5, 3) if reply else None
    run.check("its copy names what it answers", bool(header) and said == header)
    back = find(mailbox, bot_id, "inbox", f"Re: {subject}", tries=60)
    if run.check("the reply arrives", back is not None):
        mailbox.delete_message(bot_id, str(back), permanent=True)


def _keywords(run: Run, client: httpx.Client, base: str, copy: str) -> None:
    """A keyword on the copy, an Outlook category, added and taken off."""
    url = f"{base}/messages/{copy}"
    added = client.patch(url, json={"add_keywords": [KEYWORD]})
    run.check(
        "a keyword added, as an Outlook category",
        added.status_code == 200 and KEYWORD in added.json().get("keywords", []),
        str(added.status_code),
    )
    taken = client.patch(url, json={"remove_keywords": [KEYWORD]})
    run.check(
        "and taken off again",
        taken.status_code == 200 and KEYWORD not in taken.json().get("keywords", []),
        str(taken.status_code),
    )


def large(
    run: Run,
    client: httpx.Client,
    mailbox: SyncMailboxClient,
    base: str,
    bot: dict[str, str],
    bot_id: str,
    subject: str,
) -> None:
    """A mail beyond one Graph request, to the first test account: its
    files go one by one. Both sides hold them whole, then it is deleted for
    good on both."""
    files = [
        {"filename": name, "data": base64.b64encode(b"x" * size).decode()}
        for name, size in LARGE.items()
    ]
    sent = client.post(
        f"{base}/send",
        json={
            "to": [{"email": bot["email"]}],
            "subject": subject,
            "text": TEXT,
            "attachments": files,
        },
    )
    if not run.check("a mail of 7 MB", sent.status_code == 200, _said(sent)):
        return
    copy = sent.json().get("sent_copy_id")

    def sizes(url: str) -> dict[str, int]:
        found = client.get(url)
        listed = found.json().get("attachments", []) if found.status_code == 200 else []
        return {a["filename"]: a["size"] for a in listed}

    held = polled(lambda: sizes(f"{base}/messages/{copy}"), 5, 3) if copy else None
    run.check("its copy holds both files whole", held == LARGE, str(held))
    if copy:
        print(f"  its copy lies in: {_roles(client, base, copy)}")
    # A large mail may take longer, and once it did not arrive at all.
    arrived = find(mailbox, bot_id, "inbox", subject, tries=120)
    if arrived is None:
        arrived = find(mailbox, bot_id, "junk", subject, tries=1)
        if arrived is not None:
            print("  it arrived in junk")
    if run.check("it arrives", arrived is not None):
        got = sizes(f"/v1/accounts/{bot_id}/messages/{arrived}")
        run.check("with both files whole", got == LARGE, str(got))
        mailbox.delete_message(bot_id, str(arrived), permanent=True)
    if copy:
        gone = client.delete(f"{base}/messages/{copy}", params={"permanent": "true"})
        run.check("its copy deleted for good", gone.status_code == 204)


def _roles(client: httpx.Client, base: str, message_id: str) -> str:
    """The roles of the folders a message lies in, such as ``sent``, to
    tell a sent mail from one still waiting in Drafts or the Outbox."""
    message = client.get(f"{base}/messages/{message_id}")
    folders = client.get(f"{base}/folders")
    if message.status_code != 200 or folders.status_code != 200:
        return "unknown"
    role = {f["id"]: f["role"] or "no role" for f in folders.json()}
    return ", ".join(role.get(f, "unlisted") for f in message.json()["folder_ids"])


def _said(answer: httpx.Response) -> str:
    """The status, and for a failure the API's code and message: the
    provider's words, never a credential or the mail."""
    if answer.status_code < 400:
        return str(answer.status_code)
    error = answer.json().get("error", {})
    return f"{answer.status_code} {error.get('code')}: {error.get('message')}"
