"""The users of ``live/ui.py``: a role, a user and its token made through
the pages, the user's own password, and all of it removed again."""

from __future__ import annotations

import re
import secrets

import httpx

from .admin import csrf_of, ui_sign_in
from .run import Run


def check_users(run: Run, browser: httpx.Client, url: str, account_id: str) -> None:
    """A reader of the first test account made through the pages, its
    token, a sign-in with it, and the token revoked."""
    csrf = csrf_of(browser.get("/ui/users").text)
    agent = browser.get("/ui/roles/new", params={"template": "agent"}).text
    run.check(
        "the template Agent fills the form of a new role",
        'name="id" value="agent"' in agent
        and 'name="g0_allow" value="drafts" checked' in agent
        and 'name="g0_allow" value="send" checked' not in agent,
    )
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
            "signs_in_to": "ui",
            "roles": "ui-live-reader",
            "service": "users.read",
            "grants": "1",
            "g0_accounts": account_id,
            "g0_allow": "send",
            "g0_recipients": "*@example.invalid",
            "g0_max": "1",
        },
    )
    user_path = created.url.path
    if not run.check(
        "create a user with a role, a service right and a narrowed grant",
        "ui-live-reader created." in created.text and "/ui/users/usr_" in user_path,
    ):
        return
    run.check(
        "its page ticks the service right users.read",
        'name="service" value="users.read" checked' in created.text,
    )
    refused = browser.post(
        "/ui/users",
        data={
            "csrf_token": csrf,
            "name": "ui-live-refused",
            "grants": "1",
            "g0_accounts": "*",
            "g0_more": "users.manage",
        },
    )
    run.check(
        "a right of the service in a grant is refused",
        refused.status_code == 400 and "is a right of the service" in refused.text,
    )
    page = browser.post(
        f"{user_path}/tokens", data={"csrf_token": csrf, "name": "live", "days": "1"}
    ).text
    shown = re.search(r'<code class="secret"[^>]*>([^<]+)</code>', page)
    run.check("the new token is shown once", shown is not None)
    run.check(
        "and never again",
        shown is not None and shown.group(1) not in browser.get(user_path).text,
    )
    if shown is None:
        return
    token = {"Authorization": f"Bearer {shown.group(1)}"}
    with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as other:
        me = other.get("/v1/me", headers=token)
        run.check(
            "the token works on the API, with the user's rights",
            me.status_code == 200 and me.json()["name"] == "ui-live-reader",
        )
        token_id = re.search(
            r"/tokens/(tok_[0-9a-f]+)/revoke",
            browser.get(f"{user_path}?tab=access").text,
        )
        if token_id is not None:
            browser.post(
                f"{user_path}/tokens/{token_id.group(1)}/revoke",
                data={"csrf_token": csrf},
            )
        run.check(
            "a revoked token is refused at once",
            other.get("/v1/me", headers=token).status_code == 401,
        )
        run.check(
            "the token does not sign in to the UI",
            "Wrong user name or password"
            in ui_sign_in(other, "ui-live-reader", shown.group(1)).text,
        )
        set_to = secrets.token_urlsafe(18)
        was_set = browser.post(
            f"{user_path}/password",
            data={
                "csrf_token": csrf,
                "new_password": set_to,
                "repeat_password": set_to,
            },
        )
        run.check(
            "set its password",
            "must be changed at the next sign-in" in was_set.text
            and set_to not in was_set.text,
        )
        asked = ui_sign_in(other, "ui-live-reader", set_to)
        run.check(
            "it must choose its own first",
            asked.url.path == "/ui/password",
        )
        own = secrets.token_urlsafe(18)
        changed = other.post(
            "/ui/password",
            data={
                "csrf_token": csrf_of(asked.text),
                "current_password": set_to,
                "new_password": own,
                "repeat_password": own,
            },
        )
        home = other.get("/ui").text
        run.check(
            "then it sees the first test account and may read and send",
            "Password changed." in changed.text
            and "mail.read" in home
            and "send" in home,
        )
        run.check(
            "its sending is narrowed, so no warning",
            "reads and sends anywhere" not in home,
        )
        browser.post(
            user_path,
            data={"csrf_token": csrf, "name": "ui-live-reader", "disabled": "1"},
        )
        run.check(
            "a disabled user is signed out at once",
            "/ui/login" in str(other.get("/ui").url),
        )
    deleted = browser.post(f"{user_path}/delete", data={"csrf_token": csrf})
    run.check("delete the user", "User deleted" in deleted.text)
    gone = browser.post("/ui/roles/ui-live-reader/delete", data={"csrf_token": csrf})
    run.check("delete the role", "Role ui-live-reader deleted." in gone.text)
