"""The sidebar: which entries a caller sees (docs/UI.md, section 3), and
the breadcrumb of the mail pages.

An entry shows only to a caller with the right its page needs. The page
checks the right again through the domain: hiding an entry is a
courtesy, not a guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from ...data.models import Account
from ...domain.rights import Access

# A breadcrumb: (label, link) pairs, the last one the page itself.
Trail = list[tuple[str, str | None]]


@dataclass(frozen=True)
class Entry:
    # The ``page`` a route renders with, to mark the entry active.
    key: str
    label: str
    # Its icon in the sprite, by the name in Bootstrap Icons.
    icon: str
    url: str


@dataclass(frozen=True)
class Group:
    title: str | None
    entries: list[Entry]


def navigation(caller: Access) -> list[Group]:
    """The groups of the sidebar, each with the entries the caller may
    open. A group without entries is left out."""
    mailboxes = []
    if caller.anywhere("list_accounts") or caller.allows("create_account"):
        mailboxes.append(Entry("accounts", "Accounts", "at", "/ui/accounts"))
    if caller.anywhere("list_sends"):
        mailboxes.append(Entry("sends", "Sends", "send", "/ui/sends"))
    if caller.allows("list_webhooks"):
        mailboxes.append(Entry("webhooks", "Webhooks", "broadcast", "/ui/webhooks"))
    service = []
    if caller.allows("list_users"):
        service.append(Entry("users", "Users", "people", "/ui/users"))
    if caller.allows("list_roles"):
        service.append(Entry("roles", "Roles", "person-badge", "/ui/roles"))
    if caller.sees_status():
        service.append(Entry("status", "Status", "activity", "/ui/status"))
    if caller.allows("list_activity"):
        service.append(Entry("audit", "Audit", "journal-text", "/ui/audit"))
    if caller.allows("read_service_log"):
        service.append(Entry("log", "Log", "terminal", "/ui/log"))
    if caller.allows("show_recovery_key"):
        service.append(Entry("recovery", "Recovery key", "key", "/ui/recovery-key"))
    groups = [
        Group(
            None,
            [
                Entry("home", "Overview", "house", "/ui"),
                Entry("mail", "Mail", "envelope", "/ui/mail"),
            ],
        ),
        Group("Mailboxes", mailboxes),
        Group("Service", service),
    ]
    return [group for group in groups if group.entries]


def own_page(caller: Access) -> str | None:
    """The signed-in user's page, where the caller may open it."""
    return f"/ui/users/{caller.user_id}" if caller.allows("get_user") else None


def mail_url(account_id: str, folder_id: str | None = None) -> str:
    """The mail page of an account, at one of its folders if given."""
    here = f"/ui/accounts/{account_id}/mail"
    return f"{here}?{urlencode({'folder': folder_id})}" if folder_id else here


def mail_trail(account: Account, folder: tuple[str, str] | None = None) -> Trail:
    """Mail › the account's mail › a folder, for the pages below them.
    ``folder``: its id and name."""
    trail: Trail = [("Mail", "/ui/mail"), (account.email, mail_url(account.id))]
    if folder is not None:
        folder_id, name = folder
        trail.append((name, mail_url(account.id, folder_id)))
    return trail
