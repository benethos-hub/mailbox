"""Where invoices looks, and where an invoice goes: the three settings."""

from __future__ import annotations

import pytest

from benethos_mailbox_agents.agents.invoices.folders import Places
from benethos_mailbox_agents.errors import ConfigError
from benethos_mailbox_agents.records import FolderRef
from benethos_mailbox_agents.settings import Settings


def folder(path: str, role: str | None = None) -> FolderRef:
    return FolderRef(id=path, name=path.rpartition("/")[2], role=role, path=path)


INBOX = folder("INBOX", "inbox")


def by_path(*found: FolderRef) -> dict[str, FolderRef]:
    """The folders of an account by path, as the executor hands them over."""
    return {f.path: f for f in found}


def places(
    *folders: str, subfolder: str | None = None, inbox: str | None = None
) -> Places:
    return Places.read(list(folders), subfolder, inbox)


def test_unset_it_looks_in_the_inbox_alone() -> None:
    found = places()

    assert found.looks_in(INBOX)
    assert not found.looks_in(folder("Providers"))
    assert found.target(INBOX) is None
    assert found.needed() == ()


def test_a_named_folder_and_none_below_it() -> None:
    found = places("Providers/CloudHost")

    assert found.looks_in(folder("Providers/CloudHost"))
    assert not found.looks_in(folder("Providers/CloudHost/Rechnungen"))
    assert not found.looks_in(folder("Providers"))
    assert not found.looks_in(folder("providers/cloudhost"))


def test_parent_star_is_every_folder_directly_below() -> None:
    found = places("Providers/*")

    assert found.looks_in(folder("Providers/CloudHost"))
    assert found.looks_in(folder("Providers/Made-later"))
    assert not found.looks_in(folder("Providers"))
    assert not found.looks_in(folder("Providers/CloudHost/Rechnungen"))
    assert not found.looks_in(folder("Other/CloudHost"))
    assert found.needed() == ("Providers",)


def test_star_is_every_folder_at_the_top_without_a_role() -> None:
    found = places("*")

    assert found.looks_in(folder("Hosting"))
    assert found.looks_in(folder("My own"))
    assert not found.looks_in(folder("Hosting/Rechnungen"))
    for role in ("sent", "drafts", "trash", "junk", "archive", "all"):
        assert not found.looks_in(folder("Something", role))


def test_a_named_folder_with_a_role_is_looked_in_unless_it_is_the_trash() -> None:
    found = places("Archive", "Trash")

    assert found.looks_in(folder("Archive", "archive"))
    assert not found.looks_in(folder("Trash", "trash"))


def test_the_subfolder_below_the_folder_a_message_lies_in() -> None:
    found = places("Providers/*", subfolder="{folder}/Rechnungen/Eingang")

    assert found.target(folder("Providers/Hosting")) == (
        "Providers/Hosting/Rechnungen/Eingang"
    )
    assert found.target(INBOX) is None
    known = by_path(
        INBOX,
        folder("Providers"),
        folder("Providers/Hosting"),
        folder("Other"),
        folder("Other/Hosting"),
    )
    assert found.may_create("Providers/Hosting/Rechnungen", known)
    assert found.may_create("Providers/Hosting/Rechnungen/Eingang", known)
    assert not found.may_create("Providers/Hosting", known)
    assert not found.may_create("Other/Hosting/Rechnungen", known)
    assert not found.may_create("INBOX/Rechnungen", known)
    assert not found.may_create("Providers/Hosting/Other", known)


def test_star_makes_no_subfolder_below_a_folder_with_a_role() -> None:
    found = places("*", subfolder="{folder}/Rechnungen")
    known = by_path(
        INBOX,
        folder("Sent", "sent"),
        folder("Drafts", "drafts"),
        folder("Acme"),
    )

    assert found.may_create("Acme/Rechnungen", known)
    assert not found.may_create("Sent/Rechnungen", known)
    assert not found.may_create("Drafts/Rechnungen", known)
    assert not found.may_create("INBOX/Rechnungen", known)
    assert not found.may_create("Missing/Rechnungen", known)


def test_without_a_subfolder_nothing_is_made() -> None:
    found = places("*")

    assert found.target(folder("Hosting")) is None
    assert not found.may_create("Hosting/Rechnungen", by_path(folder("Hosting")))


def test_the_inbox_folder_is_needed_and_not_made() -> None:
    found = places("Providers/CloudHost", inbox="Rechnungen/Eingang")

    assert found.target(INBOX) == "Rechnungen/Eingang"
    assert found.needed() == ("Providers/CloudHost", "Rechnungen/Eingang")
    assert not found.may_create("Rechnungen/Eingang", by_path(folder("Rechnungen")))


def test_the_subfolder_of_a_folder_it_looks_in_is_not_looked_in() -> None:
    found = places("Invoices", "Invoices/*", subfolder="{folder}/Rechnungen/Eingang")

    assert found.looks_in(folder("Invoices"))
    assert found.looks_in(folder("Invoices/Hosting"))
    assert not found.looks_in(folder("Invoices/Rechnungen"))
    known = by_path(folder("Invoices"), folder("Invoices/Rechnungen"))
    assert not found.may_create("Invoices/Rechnungen/Rechnungen", known)
    assert found.may_create("Invoices/Rechnungen", known)


def test_the_inbox_folder_the_settings_take_in_is_an_end_station() -> None:
    found = places("*", subfolder="{folder}/Rechnungen", inbox="Invoices")
    end = folder("Invoices")

    assert found.looks_in(end)
    assert found.is_end(end)
    assert found.target(end) is None
    assert found.steps(end) == ()
    assert found.looks_in(folder("Acme"))
    assert found.target(folder("Acme")) == "Acme/Rechnungen"


def test_the_inbox_folder_is_not_made_where_it_is_a_subfolder_too() -> None:
    found = places(
        "Invoices", subfolder="{folder}/Rechnungen", inbox="Invoices/Rechnungen"
    )
    known = by_path(INBOX, folder("Invoices"))

    assert not found.may_create("Invoices/Rechnungen", known)


def test_an_inbox_folder_set_to_the_inbox_itself_moves_nothing() -> None:
    found = places("Invoices/*", subfolder="{folder}/Rechnungen", inbox="INBOX")

    assert found.target(INBOX) is None
    assert found.describe(by_path(INBOX)) == [
        "INBOX: looked in, the inbox folder is the inbox itself, "
        "an invoice is marked and stays"
    ]


def test_only_the_subfolder_below_a_folder_looked_in_is_left_out() -> None:
    found = places("Providers", "Providers/*", subfolder="{folder}/Rechnungen")

    assert found.looks_in(folder("Providers"))
    assert found.looks_in(folder("Providers/CloudHost"))
    assert not found.looks_in(folder("Providers/Rechnungen"))
    assert not found.looks_in(folder("Providers/CloudHost/Rechnungen"))


def test_nothing_is_made_below_the_end_station() -> None:
    found = places("*", subfolder="{folder}/Rechnungen/Eingang", inbox="Invoices")
    known = by_path(folder("Invoices"), folder("Invoices/Rechnungen"))

    assert not found.may_create("Invoices/Rechnungen", known)
    assert not found.may_create("Invoices/Rechnungen/Eingang", known)


def test_an_inbox_folder_the_settings_do_not_take_in_is_not_looked_in() -> None:
    found = places("Providers/*", subfolder="{folder}/Rechnungen", inbox="Invoices")

    assert not found.looks_in(folder("Invoices"))
    assert found.target(INBOX) == "Invoices"


def test_the_inbox_folder_named_in_the_folders_too_is_an_end_station() -> None:
    found = places("Invoices", subfolder="{folder}/Rechnungen", inbox="Invoices")

    assert found.looks_in(folder("Invoices"))
    assert found.target(folder("Invoices")) is None
    assert found.needed() == ("Invoices",)


def test_an_inbox_folder_that_is_a_subfolder_is_not_looked_in() -> None:
    """The test of the subfolder comes first: an inbox folder below a
    folder it looks in, where the subfolder pattern points, is a subfolder."""
    found = places(
        "Invoices",
        "Invoices/*",
        subfolder="{folder}/Rechnungen",
        inbox="Invoices/Rechnungen",
    )

    assert not found.looks_in(folder("Invoices/Rechnungen"))
    assert found.looks_in(folder("Invoices/Hosting"))


def test_the_folders_that_matter_are_described() -> None:
    found = places("Providers/*", subfolder="{folder}/Rechnungen", inbox="Invoices")
    known = by_path(
        INBOX,
        folder("Sent", "sent"),
        folder("Invoices"),
        folder("Providers"),
        folder("Providers/Acme"),
        folder("Providers/Acme/Rechnungen"),
        folder("Other"),
    )

    assert found.describe(known) == [
        "INBOX: looked in, an invoice moves to Invoices",
        "Invoices: inbox folder, not looked in",
        "Providers/Acme: looked in, an invoice moves to Providers/Acme/Rechnungen",
        "Providers/Acme/Rechnungen: subfolder, not looked in",
    ]


def test_without_a_subfolder_an_invoice_is_described_as_staying() -> None:
    found = places("*")

    assert found.describe(by_path(INBOX, folder("Acme"))) == [
        "Acme: looked in, an invoice is marked and stays",
        "INBOX: looked in, an invoice is marked and stays",
    ]


@pytest.mark.parametrize(
    ("folders", "subfolder", "inbox", "says"),
    [
        (["Providers//CloudHost"], None, None, "INVOICES_FOLDERS"),
        (["Providers/*/x"], None, None, "INVOICES_FOLDERS"),
        (["../x"], None, None, "INVOICES_FOLDERS"),
        ([], "Rechnungen", None, "does not start with {folder}/"),
        ([], "{folder}/", None, "INVOICES_SUBFOLDER"),
        ([], "{folder}/a/{folder}", None, "INVOICES_SUBFOLDER"),
        ([], None, "a/ b", "INVOICES_INBOX_FOLDER"),
    ],
)
def test_a_wrong_setting_says_what_is_wrong(
    folders: list[str], subfolder: str | None, inbox: str | None, says: str
) -> None:
    with pytest.raises(ConfigError) as raised:
        Places.read(folders, subfolder, inbox)

    assert says in raised.value.message


def test_the_folders_come_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_INVOICES_FOLDERS", "Providers/*, *,Archive")

    assert Settings().invoices_folders == ["Providers/*", "*", "Archive"]
