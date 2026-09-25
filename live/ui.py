"""Live check of the configuration UI against the test accounts.

    uv run python live/ui.py

Starts a service of its own with a throwaway database, as mcp_stdio.py
does, and adds the first test account through the API. Then it uses the
UI the way a browser does. It signs in with the admin key and connects the
second test account through discovery and the form. It makes a user, a
role and a token and signs in with that token. It reads mail, opens the
pages and follows their forms. It writes on the test accounts only: a
folder and a draft on the first, which it removes again, and one mail
from the first to the second, deleted for good on both sides. Credentials
and mail content are never printed.
"""

from __future__ import annotations

import html
import re
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    """Connects the second test account through the UI, returns its id."""
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
    for attempt in range(tries):
        listing = browser.get(
            f"/ui/accounts/{account_id}/mail",
            params={"folder": folder, "subject": token},
        ).text
        found = re.search(
            rf'href="(/ui/accounts/{account_id}/mail/msg_[0-9a-f]+)"', listing
        )
        if found is not None:
            return found.group(1)
        if attempt + 1 < tries:
            time.sleep(5)
    return None


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
    created = browser.post(
        f"{base}/folders", data={"csrf_token": csrf, "name": "ui-live-check"}
    )
    folder = parse_qs(urlsplit(str(created.url)).query).get("folder", [""])[0]
    run.check("create a folder", "ui-live-check created." in created.text)
    renamed = browser.post(
        f"{base}/folders/rename",
        data={"csrf_token": csrf, "folder": folder, "name": "ui-live-check-2"},
    )
    run.check("rename it", "Renamed." in renamed.text)
    folder = parse_qs(urlsplit(str(renamed.url)).query).get("folder", [""])[0]
    deleted = browser.post(
        f"{base}/folders/delete", data={"csrf_token": csrf, "folder": folder}
    )
    run.check("delete it", "Folder deleted." in deleted.text)

    token = f"mailbox-api UI live check {secrets.token_hex(4)}"
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


def check_sends(
    run: Run, browser: httpx.Client, sender_id: str, receiver_email: str
) -> None:
    """The send before is in the audit, as sent, without its content."""
    page = browser.get(f"/ui/accounts/{sender_id}/sends").text
    run.check(
        "the audit names the send and its recipient",
        receiver_email in page and '<span class="tag ok">sent</span>' in page,
    )
    run.check("never its content", "deleted again at once" not in page)
    together = browser.get("/ui/sends").text
    run.check("every account's sends together", receiver_email in together)


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
            second_id = check_accounts(run, browser, env, test_accounts[1], admin_key)
            print("\n== users, tokens, roles")
            assert account_id is not None
            check_users(run, browser, url, account_id)
            print("\n== reading mail")
            check_mail(run, browser, account_id)
            if second_id is not None:
                print("\n== writing and sending")
                check_writing(
                    run, browser, account_id, second_id, test_accounts[1]["email"]
                )
                print("\n== the send audit")
                check_sends(run, browser, account_id, test_accounts[1]["email"])
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
