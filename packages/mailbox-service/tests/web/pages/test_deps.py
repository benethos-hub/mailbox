"""What a page asks of the caller's rights."""

from __future__ import annotations

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.web.pages.deps import if_allowed
from benethos_mailbox_service.web.pages.navigation import mail_url


def test_a_part_of_a_page_only_where_allowed() -> None:
    caller = Access("usr_1", "u", [Grant(accounts=["acc_1"], allow=["list_folders"])])
    assert if_allowed(caller, "list_folders", lambda: ["f"], [], "acc_1") == ["f"]
    assert if_allowed(caller, "list_folders", lambda: ["f"], [], "acc_2") == []
    assert if_allowed(caller, "list_users", lambda: 1 / 0, None) is None


def test_the_mail_page_of_an_account() -> None:
    assert mail_url("acc_1") == "/ui/accounts/acc_1/mail"
    at_folder = "/ui/accounts/acc_1/mail?folder=INBOX%2FSub"
    assert mail_url("acc_1", "INBOX/Sub") == at_folder
