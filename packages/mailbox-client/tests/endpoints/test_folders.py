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


async def test_update_folder_renames_or_moves(make_client: Callable) -> None:
    api = FakeApi(FOLDER)
    await make_client(api).update_folder("acc_1", "fld_1", name="Old")
    assert api.call() == (
        "PATCH",
        "/v1/accounts/acc_1/folders/fld_1",
        {},
        {"name": "Old"},
    )
    top = FakeApi(FOLDER)
    await make_client(top).update_folder("acc_1", "fld_1", parent_id=None)
    assert top.call()[3] == {"parent_id": None}


async def test_delete_folder(make_client: Callable) -> None:
    api = FakeApi()
    assert await make_client(api).delete_folder("acc_1", "a/b") is None
    assert api.call()[0] == "DELETE"
    # An IMAP folder's id may hold a slash: it stays one part of the path.
    assert api.seen[0].url.raw_path == b"/v1/accounts/acc_1/folders/a%2Fb"
