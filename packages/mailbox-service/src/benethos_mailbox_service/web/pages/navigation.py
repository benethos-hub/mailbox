"""The sidebar: which entries a caller sees (docs/UI.md, section 3).

An entry shows only to a caller with the right its page needs. The page
checks the right again through the domain: hiding an entry is a
courtesy, not a guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...domain.access import Access


@dataclass(frozen=True)
class Entry:
    # The ``page`` a route renders with, to mark the entry active.
    key: str
    label: str
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
    if caller.has_accounts() or caller.allows("create_account"):
        mailboxes.append(Entry("accounts", "Accounts", "▤", "/ui/accounts"))
    if caller.anywhere("list_sends"):
        mailboxes.append(Entry("sends", "Sends", "⇢", "/ui/sends"))
    service = []
    if caller.allows("list_users"):
        service.append(Entry("users", "Users", "☺", "/ui/users"))
    if caller.allows("list_roles"):
        service.append(Entry("roles", "Roles", "◈", "/ui/roles"))
    groups = [
        Group(
            None,
            [
                Entry("home", "Overview", "◫", "/ui"),
                Entry("mail", "Mail", "✉", "/ui/mail"),
            ],
        ),
        Group("Mailboxes", mailboxes),
        Group("Service", service),
    ]
    return [group for group in groups if group.entries]


def own_page(caller: Access) -> str | None:
    """The signed-in user's page, where the caller may open it."""
    return f"/ui/users/{caller.user_id}" if caller.allows("get_user") else None
