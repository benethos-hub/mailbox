"""The mail of ``live/ui.py``: reading it through the pages, and writing
on the test accounts. Folders and drafts, and one mail from the first
test account to the second, each removed again."""

from __future__ import annotations

import html
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx

from .admin import csrf_of
from .run import Run, polled


def check_mail(run: Run, browser: httpx.Client, account_id: str) -> None:
    """Every inbox, one account's folders, a message and its original. Only
    reads. Nothing of the mail is printed."""
    together = browser.get("/ui/mail")
    run.check(
        "every inbox together",
        together.status_code == 200 and "notice warn" not in together.text,
    )
    folders = browser.get(f"/ui/accounts/{account_id}/mail")
    run.check(
        "the first test account's folders and inbox",
        folders.status_code == 200 and 'aria-label="Folders"' in folders.text,
    )
    found = re.search(
        rf'href="(/ui/accounts/{account_id}/mail/msg_[0-9a-f]+)"', folders.text
    )
    if not run.check("its inbox lists a message", found is not None):
        return
    assert found is not None
    message = browser.get(found.group(1))
    run.check(
        "a message opens",
        message.status_code == 200 and "<dt>From</dt>" in message.text,
    )
    raw = browser.get(f"{found.group(1)}/raw")
    run.check(
        "its original downloads",
        raw.status_code == 200
        and raw.headers.get("content-disposition", "").startswith("attachment;"),
    )
    searched = browser.get(
        f"/ui/accounts/{account_id}/mail", params={"q": "zz-no-such-mail-zz"}
    )
    run.check("a search that finds nothing", "match the search" in searched.text)


def _find(
    browser: httpx.Client, account_id: str, folder: str, token: str, tries: int = 1
) -> str | None:
    """The page of the one message whose subject holds ``token``."""

    def look() -> str | None:
        listing = browser.get(
            f"/ui/accounts/{account_id}/mail",
            params={"folder": folder, "subject": token},
        ).text
        found = re.search(
            rf'href="(/ui/accounts/{account_id}/mail/msg_[0-9a-f]+)"', listing
        )
        return found.group(1) if found is not None else None

    return polled(look, tries, 5)


def check_writing(
    run: Run,
    browser: httpx.Client,
    sender_id: str,
    receiver_id: str,
    receiver_email: str,
) -> None:
    """Folders and a draft on the first test account, which clean up after
    themselves, and one mail from the first test account to the second,
    deleted for good on both sides afterwards."""
    csrf = csrf_of(browser.get("/ui").text)
    base = f"/ui/accounts/{sender_id}"
    token = f"mailbox-service UI live check {secrets.token_hex(4)}"
    check_folders(run, browser, csrf, base)
    check_draft(run, browser, csrf, base, receiver_email, token)
    check_reply_draft(run, browser, csrf, base)
    check_sent_mail(run, browser, csrf, (sender_id, receiver_id), receiver_email, token)


def check_folders(run: Run, browser: httpx.Client, csrf: str, base: str) -> None:
    """A folder made, renamed and deleted."""
    created = browser.post(
        f"{base}/folders", data={"csrf_token": csrf, "name": "ui-live-check"}
    )
    folder = parse_qs(urlsplit(str(created.url)).query).get("folder", [""])[0]
    run.check("create a folder", "ui-live-check created." in created.text)
    renamed = browser.post(
        f"{base}/folders/change",
        data={
            "csrf_token": csrf,
            "folder": folder,
            "was_name": "ui-live-check",
            "name": "ui-live-check-2",
        },
    )
    run.check("rename it", "Renamed." in renamed.text)
    folder = parse_qs(urlsplit(str(renamed.url)).query).get("folder", [""])[0]
    deleted = browser.post(
        f"{base}/folders/delete", data={"csrf_token": csrf, "folder": folder}
    )
    run.check("delete it", "Folder deleted." in deleted.text)


def check_draft(
    run: Run,
    browser: httpx.Client,
    csrf: str,
    base: str,
    receiver_email: str,
    token: str,
) -> None:
    """A draft saved, changed and deleted, never sent."""
    draft = browser.post(
        f"{base}/compose",
        data={
            "csrf_token": csrf,
            "to": receiver_email,
            "subject": f"{token} draft",
            "text": "A draft from the UI live check.",
            "do": "save",
        },
    )
    run.check("save a draft", "Draft saved." in draft.text)
    edited = browser.post(
        str(draft.url.path),
        data={
            "csrf_token": csrf,
            "to": receiver_email,
            "subject": f"{token} draft",
            "text": "Changed.",
            "do": "save",
        },
    )
    run.check("change it", "Draft saved." in edited.text and "Changed." in edited.text)
    gone = browser.post(str(draft.url.path), data={"csrf_token": csrf, "do": "delete"})
    run.check("delete it", "Draft deleted." in gone.text)


def check_reply_draft(run: Run, browser: httpx.Client, csrf: str, base: str) -> None:
    """A reply draft to a message in the inbox: linked, changed as a
    whole, quoted once, deleted."""
    inbox = browser.get(f"{base}/mail").text
    original = re.search(rf'href="{base}/mail/(msg_[0-9a-f]+)"', inbox)
    if run.check("a message to answer", original is not None):
        assert original is not None
        # The original may quote a message itself: the draft adds one quote.
        shown = html.unescape(browser.get(f"{base}/mail/{original.group(1)}").text)
        quoted_before = shown.count("wrote:")
        reply = browser.post(
            f"{base}/compose",
            data={
                "csrf_token": csrf,
                "original": original.group(1),
                "action": "reply",
                "text": "A reply draft of the UI live check.",
                "do": "save",
            },
        )
        run.check("save a reply draft", "stays linked" in reply.text)
        to = re.search(r'name="to" value="([^"]*)"', reply.text)
        text = re.search(r'name="text" rows="14">([^<]*)</textarea>', reply.text)
        subject = re.search(r'name="subject" value="([^"]*)"', reply.text)
        changed = browser.post(
            str(reply.url.path),
            data={
                "csrf_token": csrf,
                "to": html.unescape(to.group(1)) if to else "",
                "subject": html.unescape(subject.group(1)) if subject else "",
                "text": html.unescape(text.group(1)).replace(
                    "A reply", "Changed: a reply", 1
                )
                if text
                else "",
                "do": "save",
            },
        )
        run.check(
            "change it as a whole: still linked, quoted once",
            "Draft saved." in changed.text
            and "stays linked" in changed.text
            and "Changed: a reply" in changed.text
            and html.unescape(changed.text).count("wrote:") == quoted_before + 1,
        )
        gone = browser.post(
            str(reply.url.path), data={"csrf_token": csrf, "do": "delete"}
        )
        run.check("delete it", "Draft deleted." in gone.text)


def check_sent_mail(
    run: Run,
    browser: httpx.Client,
    csrf: str,
    ids: tuple[str, str],
    receiver_email: str,
    token: str,
) -> None:
    """One mail from the first test account to the second: starred, read,
    with a keyword and without, deleted for good on both sides."""
    sender_id, receiver_id = ids
    base = f"/ui/accounts/{sender_id}"
    form = browser.get(f"{base}/compose").text
    key = re.search(r'name="idempotency_key" value="([^"]+)"', form)
    sent = browser.post(
        f"{base}/compose",
        data={
            "csrf_token": csrf,
            "idempotency_key": key.group(1) if key else "",
            "to": receiver_email,
            "subject": token,
            "text": "Sent by the UI live check; deleted again at once.",
            "do": "send",
        },
    )
    if not run.check(
        "send from the first test account to the second", "Sent." in sent.text
    ):
        return
    received = _find(browser, receiver_id, "inbox", token, tries=12)
    if run.check("it arrives", received is not None):
        assert received is not None
        message_id = received.rpartition("/")[2]
        marked = browser.post(
            f"/ui/accounts/{receiver_id}/mail/batch",
            data={
                "csrf_token": csrf,
                "ids": message_id,
                "action": "star",
                "back": f"/ui/accounts/{receiver_id}/mail",
            },
        )
        run.check("star it through the list", "1 done." in marked.text)
        read = browser.post(
            f"{received}/flags", data={"csrf_token": csrf, "unread": "0"}
        )
        run.check("mark it read", "Mark unread" in read.text)
        tagged = browser.post(
            f"{received}/keywords", data={"csrf_token": csrf, "add": "live-check"}
        )
        run.check(
            "give it a keyword",
            "Remove live-check" in tagged.text and 'role="alert"' not in tagged.text,
        )
        untagged = browser.post(
            f"{received}/keywords", data={"csrf_token": csrf, "remove": "live-check"}
        )
        run.check(
            "take the keyword away",
            "Remove live-check" not in untagged.text
            and 'role="alert"' not in untagged.text,
        )
        trashed = browser.post(f"{received}/delete", data={"csrf_token": csrf})
        run.check("move it to the trash", "Moved to the trash." in trashed.text)
        purged = browser.post(
            f"{received}/delete", data={"csrf_token": csrf, "permanent": "1"}
        )
        run.check("delete it for good", "Deleted for good." in purged.text)
    copy = _find(browser, sender_id, "sent", token, tries=3)
    if run.check("the sent copy", copy is not None):
        assert copy is not None
        purged = browser.post(
            f"{copy}/delete", data={"csrf_token": csrf, "permanent": "1"}
        )
        run.check("delete the sent copy for good", "Deleted for good." in purged.text)
