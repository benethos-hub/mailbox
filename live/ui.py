"""Live check of the configuration UI against the test accounts.

    uv run python live/ui.py

Starts a service of its own with a throwaway database, as mcp_stdio.py
does, and adds the first test account through the API. Then it uses the
UI the way a browser does. It signs in as the user `users create-admin`
made and connects the second test account through discovery and the
form. It makes a user, a role and a token, uses the token on the API,
and sets the user's password, which the user changes at its sign-in.
It reads mail, opens the pages and follows their forms. It opens the
status, adds and removes a webhook, shows the recovery key of its own
service, reads its log, makes a user with a one-time password, and reads
what it did in the audit, on its page, a user's page and the API. A user
of its own adds two devices of a second factor from the keys of their QR
codes, signs in with a code of each and a recovery code, makes new
codes and removes them, and the admin and the host remove them too. It
writes on the test accounts only: a folder and a draft on the first,
which it removes again, and one mail from the first to the second,
deleted for good on both sides. Credentials and mail content are never
printed.
"""

from __future__ import annotations

import re
import sys

import httpx
from checks.accounts import accounts, imap_settings, read_env, register
from checks.admin import Admin, csrf_of, ui_sign_in
from checks.run import Run
from checks.service import throwaway_service
from checks.ui_factor import check_second_factor
from checks.ui_mail import check_mail, check_writing
from checks.ui_users import check_users


def check_sign_in(run: Run, browser: httpx.Client, admin: Admin) -> bool:
    """The admin came from `users create-admin`: its one-time password led
    to one of its own, which signs in (see bootstrap)."""
    wrong = ui_sign_in(browser, admin.name, "not the password at all")
    run.check(
        "a wrong password is refused", "Wrong user name or password" in wrong.text
    )
    signed = ui_sign_in(browser, admin.name, admin.password)
    return run.check(
        "sign in with the password that replaced the one-time password",
        signed.status_code == 200 and "Signed in as" in signed.text,
    )


def check_frame(run: Run, browser: httpx.Client, emails: list[str]) -> None:
    home = browser.get("/ui")
    run.check(
        "the overview lists the test accounts",
        home.status_code == 200 and all(e in home.text.lower() for e in emails),
    )
    run.check(
        "the admin is warned: reads and sends anywhere",
        "reads and sends anywhere" in home.text,
    )
    run.check(
        "security headers",
        "frame-ancestors 'none'" in home.headers.get("content-security-policy", ""),
    )


def check_service(
    run: Run, browser: httpx.Client, url: str, admin: Admin, emails: list[str]
) -> None:
    """The state of the service on the overview and the accounts list, a
    webhook, the recovery key, the log and a user with a one-time
    password. Nothing here touches a mailbox."""
    home = browser.get("/ui")
    accounts = browser.get("/ui/accounts")
    run.check(
        "the overview names the worker, the accounts list both accounts"
        " and their last sync",
        "<dt>Sync worker</dt>" in home.text
        and all(e in accounts.text.lower() for e in emails)
        and "<th>Last sync</th>" in accounts.text,
    )
    csrf = csrf_of(browser.get("/ui/webhooks").text)
    # Port 9 (discard): nothing takes the posts, the log shows the failures.
    hook = browser.post(
        "/ui/webhooks",
        data={
            "csrf_token": csrf,
            "url": "http://127.0.0.1:9/ui-live",
            "events": "message.created",
            "every": "1",
        },
    )
    run.check(
        "a webhook shows its secret once",
        "Webhook created." in hook.text and "shown this once" in hook.text,
    )
    listed = browser.get("/ui/webhooks").text
    run.check("the webhook is listed", "127.0.0.1:9/ui-live" in listed)
    changed = browser.post(
        hook.url.path,
        data={
            "csrf_token": csrf,
            "url": "http://127.0.0.1:9/ui-live-changed",
            "events": ["message.created", "message.sent"],
            "every": "1",
        },
    )
    run.check(
        "change its URL and events",
        "Saved." in changed.text
        and "127.0.0.1:9/ui-live-changed" in changed.text
        and 'name="events" value="message.sent" checked' in changed.text,
    )
    renewed = browser.post(f"{hook.url.path}/secret", data={"csrf_token": csrf})
    run.check(
        "give it a new secret, shown once",
        "New secret made." in renewed.text and "shown this once" in renewed.text,
    )
    removed = browser.post(f"{hook.url.path}/delete", data={"csrf_token": csrf})
    run.check("remove the webhook", "Webhook removed." in removed.text)

    wrong = browser.post(
        "/ui/recovery-key",
        data={"csrf_token": csrf, "password": "not the admin password at all"},
    )
    run.check(
        "the recovery key wants the password",
        "the password is not right" in wrong.text and "<code" not in wrong.text,
    )
    shown = browser.post(
        "/ui/recovery-key", data={"csrf_token": csrf, "password": admin.password}
    )
    key = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', shown.text)
    run.check("the recovery key is shown after it", key is not None)
    run.check(
        "and only once",
        key is not None and key.group(1) not in browser.get("/ui/recovery-key").text,
    )
    # Searched: the access lines of every page came since.
    signed = browser.get("/ui/log", params={"text": "signed in to the UI"}).text
    told = browser.get("/ui/log", params={"text": "was shown the recovery key"}).text
    run.check(
        "the log names the sign-in and to whom the key was shown, not the key",
        f"{admin.name} (usr_" in signed
        and f"{admin.name} (usr_" in told
        and (key is None or key.group(1) not in signed + told),
    )

    once = browser.post(
        "/ui/users",
        data={
            "csrf_token": csrf,
            "name": "ui-live-once",
            "grants": "0",
            "signs_in_to": "ui",
            "one_time": "1",
        },
    )
    password = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', once.text)
    if not run.check("a new user gets a one-time password", password is not None):
        return
    assert password is not None
    with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as other:
        landed = ui_sign_in(other, "ui-live-once", password.group(1))
        run.check(
            "it signs in and must choose its own",
            landed.url.path == "/ui/password",
        )
    gone = browser.post(f"{once.url.path}/delete", data={"csrf_token": csrf})
    run.check("delete that user", "User deleted" in gone.text)

    api = browser.post(
        "/ui/users", data={"csrf_token": csrf, "name": "ui-live-api", "grants": "0"}
    )
    access = browser.get(f"{api.url.path}?tab=access").text
    run.check(
        "a new user is an API user by default",
        "off: an API user, tokens only" in access and "Set password" not in access,
    )
    gone = browser.post(f"{api.url.path}/delete", data={"csrf_token": csrf})
    run.check("delete the API user", "User deleted" in gone.text)


def check_accounts(
    run: Run,
    browser: httpx.Client,
    env: dict[str, str],
    account: dict[str, str],
    token: str,
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
        headers={"Authorization": f"Bearer {token}"},
    ).text
    run.check(
        "the API shows the settings, never the password",
        "host" in api and account["password"] not in api,
    )
    return account_id


def check_sends(
    run: Run, browser: httpx.Client, sender_id: str, receiver_email: str
) -> None:
    """The send before is in the audit, as sent, without its content."""
    page = browser.get("/ui/sends", params={"account": sender_id}).text
    run.check(
        "the audit names the send and its recipient",
        receiver_email in page and '<span class="tag ok">sent</span>' in page,
    )
    run.check("never its content", "deleted again at once" not in page)
    together = browser.get("/ui/sends").text
    run.check("every account's sends together", receiver_email in together)


def check_audit(run: Run, browser: httpx.Client, url: str, admin: Admin) -> None:
    """The audit of administration names what this run did, never a
    secret. Read-only."""
    page = browser.get("/ui/audit").text
    kinds = set(re.findall(r'<span class="mono">(\w+\.\w+)</span>', page))
    wanted = {
        "auth.signed_in",
        "users.created",
        "users.token_issued",
        "users.role_created",
        "webhooks.created",
        "webhooks.changed",
        "webhooks.secret_renewed",
        "webhooks.removed",
        "system.recovery_shown",
        "system.log_read",
    }
    run.check(
        "the Audit page names what this run did",
        wanted <= kinds,
        ", ".join(sorted(wanted - kinds)),
    )
    run.check("and no token", "mbx_" not in page)
    hooks = browser.get("/ui/audit", params={"activity": "webhooks"}).text
    run.check(
        "its filter keeps an area",
        set(re.findall(r'<span class="mono">(\w+\.\w+)</span>', hooks))
        == {
            "webhooks.created",
            "webhooks.changed",
            "webhooks.secret_renewed",
            "webhooks.removed",
        },
    )
    own = re.search(r'href="(/ui/users/usr_\w+)"', browser.get("/ui").text)
    card = browser.get(f"{own.group(1)}?tab=activity").text if own else ""
    # The newest ten: this run did more since its sign-in.
    run.check(
        "the own page shows its recent activity",
        "Recent activity" in card
        and len(re.findall(r'<span class="mono">\w+\.\w+</span>', card)) == 10,
    )
    with httpx.Client(
        base_url=url, headers={"Authorization": f"Bearer {admin.token}"}, timeout=30
    ) as api:
        answer = api.get("/v1/audit", params={"activity": "auth", "limit": 5})
        items = answer.json().get("items", []) if answer.status_code == 200 else []
        run.check(
            "GET /v1/audit names the sign-ins through the UI",
            any(
                i["activity"] == "auth.signed_in" and i["credential"] == "password"
                for i in items
            ),
            str(answer.status_code),
        )


def main() -> int:
    env = read_env()
    test_accounts = accounts(env)[:2]
    run = Run()
    with throwaway_service("mailbox-ui-live-") as service:
        url, admin = service.url, service.admin_user
        with service.mailbox() as mailbox:
            account_id, outcome = register(mailbox, env, test_accounts[0])
            if not run.check(
                "account 1 in the service", account_id is not None, outcome
            ):
                return 1
        with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as browser:
            print("\n== signing in")
            if not check_sign_in(run, browser, admin):
                return 1
            print("\n== accounts")
            second_id = check_accounts(run, browser, env, test_accounts[1], admin.token)
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
            emails = [a["email"].lower() for a in test_accounts]
            print("\n== the frame")
            check_frame(run, browser, emails)
            print("\n== status, webhooks, recovery key, log")
            check_service(run, browser, url, admin, emails)
            print("\n== the audit of administration")
            check_audit(run, browser, url, admin)
            print("\n== the second factor")
            check_second_factor(run, url, admin, browser, service.env)
    return run.finish()


if __name__ == "__main__":
    sys.exit(main())
