"""The list of categorization: format, loading, validation, matching."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_agents.agents.categorization.groups import (
    MAX_ADDRESS,
    Groups,
    Kind,
    load_groups,
)
from benethos_mailbox_agents.agents.categorization.lists import list_digest
from benethos_mailbox_agents.errors import ConfigError

from .categorization_helpers import groups, refused


@pytest.fixture
def listed() -> Groups:
    return groups(
        {
            "name": "Bank",
            "folder": "Providers/Bank",
            "senders": ["service@bank-two.example", "*@bank-one.example"],
            "hold": True,
        },
        {
            "name": "CloudHost",
            "folder": "Providers/CloudHost",
            "senders": ["*@cloudhost.example", "mailbox*@telco.example"],
        },
        {
            "name": "Shop",
            "folder": "Shop",
            "senders": ["*@*.shop.example", "Orders@Shop.Example"],
        },
    )


@pytest.mark.parametrize(
    ("address", "group", "kind"),
    [
        ("service@bank-two.example", "Bank", Kind.ADDRESS),
        ("anyone@bank-one.example", "Bank", Kind.PATTERN),
        ("mailbox7@telco.example", "CloudHost", Kind.PATTERN),
        ("billing@cloudhost.example", "CloudHost", Kind.PATTERN),
        ("news@eu.shop.example", "Shop", Kind.SUBDOMAINS),
        ("news@a.b.shop.example", "Shop", Kind.SUBDOMAINS),
        ("ORDERS@shop.example", "Shop", Kind.ADDRESS),
    ],
)
def test_a_sender_finds_its_group(
    listed: Groups, address: str, group: str, kind: Kind
) -> None:
    found = listed.match(address)

    assert found is not None and found.group is not None
    assert (found.group.name, found.kind) == (group, kind)


@pytest.mark.parametrize(
    "address",
    [
        "billing@eu.cloudhost.example",  # a pattern covers one domain
        "news@shop.example",  # a pattern for subdomains not the domain
        "info@telco.example",
        "someone@elsewhere.example",
        "",
        None,
    ],
)
def test_a_sender_in_no_group(listed: Groups, address: str | None) -> None:
    assert listed.match(address) is None


def test_an_address_wins_over_a_pattern() -> None:
    found = groups(
        {"name": "A", "folder": "A", "senders": ["*@telco.example"]},
        {"name": "B", "folder": "B", "senders": ["billing@telco.example"]},
    ).match("billing@telco.example")

    assert found is not None and found.group is not None
    assert found.group.name == "B"


def test_a_pattern_wins_over_one_for_subdomains() -> None:
    found = groups(
        {"name": "A", "folder": "A", "senders": ["*@*.shop.example"]},
        {"name": "B", "folder": "B", "senders": ["*@eu.shop.example"]},
    ).match("news@eu.shop.example")

    assert found is not None and found.group is not None
    assert found.group.name == "B"


def test_two_groups_alike_leave_the_sender_to_none() -> None:
    found = groups(
        {"name": "A", "folder": "A", "senders": ["*@telco.example"]},
        {"name": "B", "folder": "B", "senders": ["bill*@telco.example"]},
    ).match("billing@telco.example")

    assert found is not None
    assert found.group is None
    assert [g.name for g in found.groups] == ["A", "B"]


def test_the_folders_a_group_may_have_made(listed: Groups) -> None:
    assert listed.may_create("Providers")
    assert listed.may_create("Providers/Bank")
    assert listed.may_create("Shop")
    assert not listed.may_create("Providers/Other")
    assert not listed.may_create("providers")
    assert not listed.may_create("Elsewhere")


def test_a_group_is_moved_unless_it_is_held(listed: Groups) -> None:
    assert [g.hold for g in listed.groups] == [True, False, False]


@pytest.mark.parametrize(
    ("entries", "says"),
    [
        ([{"name": "", "folder": "A", "senders": ["a@b.example"]}], "name"),
        ([{"name": " A", "folder": "A", "senders": ["a@b.example"]}], "space"),
        (
            [
                {"name": "A", "folder": "A", "senders": ["a@b.example"]},
                {"name": "a", "folder": "B", "senders": ["c@b.example"]},
            ],
            "share the name",
        ),
        (
            [
                {"name": "A", "folder": "Same", "senders": ["a@b.example"]},
                {"name": "B", "folder": "same", "senders": ["c@b.example"]},
            ],
            "share the folder",
        ),
        ([{"name": "A", "folder": "A//B", "senders": ["a@b.example"]}], "none empty"),
        ([{"name": "A", "folder": "A/..", "senders": ["a@b.example"]}], "none empty"),
        ([{"name": "A", "folder": "A/ B", "senders": ["a@b.example"]}], "none empty"),
        ([{"name": "A", "folder": "A", "senders": []}], "senders"),
        (
            [
                {"name": "A", "folder": "A", "senders": ["a@b.example"]},
                {"name": "B", "folder": "B", "senders": ["A@b.example"]},
            ],
            "named by",
        ),
        ([{"name": "A", "folder": "A", "senders": ["b.example"]}], "is a domain"),
        ([{"name": "A", "folder": "A", "senders": ["@b.example"]}], "is a domain"),
        (
            [
                {"name": "A", "folder": "Bank", "senders": ["a@b.example"]},
                {"name": "B", "folder": "bank/Sub", "senders": ["c@b.example"]},
            ],
            "group 'B': a folder differs from one of group 'A' in case only",
        ),
        (
            [
                {"name": "A", "folder": "Top/Bank", "senders": ["a@b.example"]},
                {"name": "B", "folder": "TOP/Shop", "senders": ["c@b.example"]},
            ],
            "group 'B': a folder differs from one of group 'A' in case only",
        ),
        (
            [{"name": "None", "folder": "A", "senders": ["a@b.example"]}],
            "the label of a message in no group",
        ),
        (
            [{"name": "none", "folder": "A", "senders": ["a@b.example"]}],
            "the label of a message in no group",
        ),
        (
            [{"name": "A", "folder": "A", "senders": ["*@.shop.example"]}],
            "group 'A', sender 1 is no address",
        ),
        (
            [{"name": "A", "folder": "A", "senders": ["*@shop..example"]}],
            "group 'A', sender 1 is no address",
        ),
        (
            [{"name": "A", "folder": "A", "senders": ["a@b.c."]}],
            "group 'A', sender 1 is no address",
        ),
        (
            [{"name": "A", "folder": "A", "senders": ["*@b.c."]}],
            "group 'A', sender 1 is no address",
        ),
        (
            [{"name": "A", "folder": "A", "senders": ["*@*.shop..example"]}],
            "group 'A', sender 1 is no address",
        ),
        ([{"name": "A", "folder": "A", "senders": ["*@*.example"]}], "too broad"),
        ([{"name": "A", "folder": "A", "senders": ["*@b*.example"]}], "no address"),
        ([{"name": "A", "folder": "A", "senders": ["nobody"]}], "no address"),
        (
            [{"name": "A", "folder": "A", "senders": ["a@b.example"], "hold": "yes"}],
            "hold",
        ),
        (
            [{"name": "A", "folder": "A", "senders": ["a@b.example"], "color": 1}],
            "color",
        ),
    ],
)
def test_a_wrong_list_says_what_is_wrong(
    tmp_path: Path, entries: list[dict[str, Any]], says: str
) -> None:
    refused(tmp_path, entries, says)


def test_groups_may_share_a_folder_above_theirs_spelt_alike() -> None:
    found = groups(
        {"name": "A", "folder": "Providers", "senders": ["a@b.example"]},
        {"name": "B", "folder": "Providers/Bank", "senders": ["c@b.example"]},
        {"name": "C", "folder": "Providers/Shop", "senders": ["*@*.shop.example"]},
    )

    assert [g.name for g in found.groups] == ["A", "B", "C"]


def test_a_wrong_sender_is_named_by_its_group_and_place(tmp_path: Path) -> None:
    path = tmp_path / "categorization.json"
    entries = [
        {"name": "A", "folder": "A", "senders": ["a@b.example"]},
        {"name": "B", "folder": "B", "senders": ["c@b.example", "b.example"]},
    ]
    path.write_text(json.dumps({"groups": entries}), encoding="utf-8")

    with pytest.raises(ConfigError) as raised:
        load_groups(path)

    assert "group 'B', sender 2 is a domain" in raised.value.message


def test_a_doubled_sender_is_named_by_its_place_not_its_address(
    tmp_path: Path,
) -> None:
    path = tmp_path / "categorization.json"
    entries = [
        {"name": "A", "folder": "A", "senders": ["erika@tax-office.example"]},
        {
            "name": "B",
            "folder": "B",
            "senders": ["c@b.example", "Erika@tax-office.example"],
        },
    ]
    path.write_text(json.dumps({"groups": entries}), encoding="utf-8")

    with pytest.raises(ConfigError) as raised:
        load_groups(path)

    assert "group 'B', sender 2 is named by group 'A'" in raised.value.message
    assert "@" not in raised.value.message


def test_a_list_is_read_from_its_file(tmp_path: Path) -> None:
    path = tmp_path / "categorization.json"
    entry = {"name": "Bank", "folder": "Bank", "senders": ["*@bank-one.example"]}
    path.write_text(json.dumps({"groups": [entry]}), encoding="utf-8")

    assert [g.name for g in load_groups(path).groups] == ["Bank"]


def test_a_list_that_is_no_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "categorization.json"
    path.write_text("{groups: [", encoding="utf-8")

    with pytest.raises(ConfigError, match="categorization.json"):
        load_groups(path)


def test_a_list_of_another_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "categorization.yaml"
    path.write_text("groups: []", encoding="utf-8")

    with pytest.raises(ConfigError, match="no .json file"):
        load_groups(path)


def test_a_list_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot be read"):
        load_groups(tmp_path / "missing.json")


def test_a_list_with_the_mark_of_utf8_is_read(tmp_path: Path) -> None:
    path = tmp_path / "categorization.json"
    entry = {"name": "Bank", "folder": "Bank", "senders": ["*@bank-one.example"]}
    path.write_text(json.dumps({"groups": [entry]}), encoding="utf-8-sig")

    assert [g.name for g in load_groups(path).groups] == ["Bank"]


def test_a_list_in_another_encoding_than_utf8_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "categorization.json"
    entry = {"name": "Bäckerei", "folder": "Bäckerei", "senders": ["*@b.example"]}
    path.write_text(json.dumps({"groups": [entry]}, ensure_ascii=False), "cp1252")

    with pytest.raises(ConfigError) as raised:
        load_groups(path)

    assert raised.value.message == (
        "the categorization list categorization.json cannot be read "
        "(UnicodeDecodeError)"
    )


def test_an_address_longer_than_any_mail_allows_matches_nothing() -> None:
    listed = groups(
        {"name": "A", "folder": "A", "senders": ["*a*a*a*b@shop.example"]},
    )
    address = "a" * 100_000 + "@shop.example"

    started = time.monotonic()
    assert listed.match(address) is None
    assert time.monotonic() - started < 0.5
    assert listed.match("a" * (MAX_ADDRESS - 20) + "b@shop.example") is not None


def test_a_pattern_of_many_stars_is_matched_in_linear_time() -> None:
    listed = groups(
        {"name": "A", "folder": "A", "senders": ["x*x*x*x*x*x*y@shop.example"]},
    )
    address = "x" * (MAX_ADDRESS - len("@shop.example")) + "@shop.example"

    started = time.monotonic()
    assert listed.match(address) is None
    assert time.monotonic() - started < 0.1


def _by_regex(local: str, found: str) -> bool:
    """The match of a pattern as a regular expression, as it was before
    patterns were matched in linear time."""
    pattern = "^" + ".*".join(re.escape(p) for p in local.split("*")) + "$"
    return re.match(pattern, found) is not None


@pytest.mark.parametrize(
    ("local", "found"),
    [
        ("info*", "info"),
        ("info*", "info-desk"),
        ("info*", "inf"),
        ("*desk", "desk"),
        ("*desk", "help-desk"),
        ("*desk", "desks"),
        ("a*b", "ab"),
        ("a*b", "a"),
        ("a*b", "b"),
        ("ab*ba", "aba"),
        ("ab*ba", "abba"),
        ("a*b*c", "abc"),
        ("a*b*c", "acbc"),
        ("a*b*c", "acb"),
        ("a*bc*bc*d", "abcbcd"),
        ("a*bc*bc*d", "abcd"),
        ("*", ""),
        ("*", "any"),
        ("**", "x"),
        ("a**b", "ab"),
        ("*.*", "first.last"),
        ("*.*", "firstlast"),
        ("x*x*x*y", "xxxy"),
        ("x*x*x*y", "xxy"),
    ],
)
def test_a_pattern_matches_as_its_regular_expression_did(
    local: str, found: str
) -> None:
    listed = groups({"name": "A", "folder": "A", "senders": [f"{local}@shop.example"]})

    matched = listed.match(f"{found}@shop.example") is not None

    assert matched is _by_regex(local, found)


def test_the_version_of_a_list_stays_the_same_value() -> None:
    """A new version would take every message of the list up again."""
    listed = Groups.model_validate(
        {
            "groups": [
                {
                    "name": "Hosting",
                    "folder": "Hosting",
                    "senders": ["*@hosting.example"],
                }
            ]
        }
    )
    assert list_digest(listed) == "list-9c732a913e57"
