"""The OpenAPI document is part of the contract, so it is checked in and guarded."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import create_app, openapi_json
from benethos_mailbox_service.cli import main
from benethos_mailbox_service.data.models import MessageFilter
from benethos_mailbox_service.web import search
from benethos_mailbox_service.web.api import PREFIX as API_PREFIX

from .conftest import METHODS

COMMITTED = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def _operations() -> list[tuple[str, dict[str, Any]]]:
    schema = create_app().openapi()
    return [
        (path, op)
        for path, ops in schema["paths"].items()
        for method, op in ops.items()
        if method in METHODS
    ]


def test_committed_document_is_current() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == openapi_json(), (
        "docs/openapi.json is stale, regenerate it with "
        "`uv run benethos-mailbox-service openapi > docs/openapi.json`"
    )


def test_version_is_3_1() -> None:
    assert create_app().openapi()["openapi"].startswith("3.1")


def test_operation_ids_are_unique_snake_case() -> None:
    ids = [op["operationId"] for _, op in _operations()]
    assert len(ids) == len(set(ids))
    assert all(i.isidentifier() and i == i.lower() for i in ids)


def test_protected_routes_declare_bearer_and_errors() -> None:
    for path, op in _operations():
        if path.startswith(API_PREFIX):
            assert op["security"] == [{"bearerAuth": []}], path
            assert {"400", "401", "403", "404", "409", "502", "503"} <= set(
                op["responses"]
            ), path


def test_the_search_form_uses_the_query_names_of_the_api() -> None:
    """The UI's search (web.search) and the API's query parameters name
    the same filter fields, so a search reads the same in both."""
    listing = create_app().openapi()["paths"][f"{API_PREFIX}/messages"]["get"]
    query = {p["name"] for p in listing["parameters"] if p["in"] == "query"}
    assert set(search.FIELDS) | set(search.FLAGS) <= query
    filtered = set(search.FIELDS.values()) | set(search.FLAGS)
    assert filtered == set(MessageFilter.model_fields)


# Each list of the UI with a filter bar, the API's list of the same records,
# and the filters only the UI has: the account of a page across accounts,
# where the API has a path per account, and API only, which is
# `ui_sign_in=false`.
FILTERED_LISTS = [
    ("/ui/sends", "/sends", {"account"}),
    ("/ui/audit", "/audit", set()),
    ("/ui/users", "/users", {"api_only"}),
    ("/ui/accounts", "/accounts", set()),
    ("/ui/webhooks", "/webhooks", set()),
]


@pytest.mark.parametrize(("page", "path", "ui_only"), FILTERED_LISTS)
def test_the_filter_bars_use_the_query_names_of_the_api(
    ui: TestClient, page: str, path: str, ui_only: set[str]
) -> None:
    """A filter reads the same in the UI's URL and at the API."""
    html = ui.get(page).text
    form = re.search(r'<form class="filter-bar".*?</form>', html, re.DOTALL)
    assert form is not None, page
    names = set(re.findall(r'name="([a-z_]+)"', form.group(0)))
    listing = create_app().openapi()["paths"][f"{API_PREFIX}{path}"]["get"]
    query = {p["name"] for p in listing["parameters"] if p["in"] == "query"}
    assert names - ui_only <= query, page
    assert ui_only.isdisjoint(query), page


def test_cli_prints_the_document(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["openapi"]) == 0
    assert capsys.readouterr().out == openapi_json()
