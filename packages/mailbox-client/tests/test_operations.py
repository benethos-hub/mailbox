"""The client covers the whole REST API: every operation of
docs/openapi.json is a method of both clients, named like its
``operationId``. No operation is left out, and none is listed as an
exception. A route added to the service without its method fails here."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from benethos_mailbox_client import MailboxClient, SyncMailboxClient

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"
METHODS = {"get", "put", "post", "patch", "delete"}


def _operations() -> list[str]:
    paths = json.loads(CONTRACT.read_text("utf-8"))["paths"]
    return sorted(
        operation["operationId"]
        for item in paths.values()
        for method, operation in item.items()
        if method in METHODS
    )


OPERATIONS = _operations()


def test_the_contract_names_operations() -> None:
    assert len(OPERATIONS) > 50
    assert len(set(OPERATIONS)) == len(OPERATIONS)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_operation_is_a_method_of_both_clients(operation: str) -> None:
    asynchronous = getattr(MailboxClient, operation, None)
    blocking = getattr(SyncMailboxClient, operation, None)
    assert inspect.iscoroutinefunction(asynchronous), f"MailboxClient.{operation}"
    assert callable(blocking), f"SyncMailboxClient.{operation}"
    assert not inspect.iscoroutinefunction(blocking), f"SyncMailboxClient.{operation}"
