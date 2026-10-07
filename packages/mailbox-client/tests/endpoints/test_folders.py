"""The folders of an account, the same for both clients."""

from __future__ import annotations

from collections.abc import Callable

from benethos_mailbox_client import Folder

from ..fake_api import FOLDER, FakeApi


async def test_list_folders(make_client: Callable) -> None:
    api = FakeApi([FOLDER])
    found = await make_client(api).list_folders("acc_1")
    assert api.call() == ("GET", "/v1/accounts/acc_1/folders", {}, None)
    assert found == [Folder("fld_1", "Inbox", "inbox", 2, 9)]


async def test_create_folder(make_client: Callable) -> None:
    api = FakeApi(FOLDER)
    found = await make_client(api).create_folder("acc_1", "Inbox", None)
    assert api.call() == ("POST", "/v1/accounts/acc_1/folders", {}, {"name": "Inbox"})
    assert found.id == "fld_1"
