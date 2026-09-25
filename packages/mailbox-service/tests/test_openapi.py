"""The OpenAPI document is part of the contract, so it is checked in and guarded."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from benethos_mailbox_service.__main__ import main
from benethos_mailbox_service.main import create_app, openapi_json
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
            assert {"401", "404", "502"} <= set(op["responses"]), path


def test_cli_prints_the_document(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["openapi"]) == 0
    assert capsys.readouterr().out == openapi_json()
