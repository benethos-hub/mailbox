"""What a page asks of the caller's rights."""

from __future__ import annotations

from benethos_mailbox_service.data.models import Grant
from benethos_mailbox_service.domain.rights import Access
from benethos_mailbox_service.web.pages.deps import if_allowed


def test_a_part_of_a_page_only_where_allowed() -> None:
    caller = Access("usr_1", "u", [Grant(accounts=["acc_1"], allow=["list_folders"])])
    assert if_allowed(caller, "list_folders", lambda: ["f"], [], "acc_1") == ["f"]
    assert if_allowed(caller, "list_folders", lambda: ["f"], [], "acc_2") == []
    assert if_allowed(caller, "list_users", lambda: 1 / 0, None) is None
