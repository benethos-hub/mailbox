"""The client covers the whole REST API: every operation of
docs/openapi.json is a method of both clients, named like its
``operationId``. No operation is left out, and none is listed as an
exception. A route added to the service without its method fails here.
Both clients send the same endpoint, every endpoint is a method, and
every record is exported by the package."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import benethos_mailbox_client
from benethos_mailbox_client import MailboxClient, SyncMailboxClient, endpoints, models

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


def _endpoints() -> list[str]:
    """The functions of ``endpoints`` that describe a call. A helper such
    as ``message_body`` answers no ``Call``."""
    return sorted(
        name
        for name in endpoints.__all__
        if str(
            inspect.signature(getattr(endpoints, name)).return_annotation
        ).startswith("Call[")
    )


ENDPOINTS = _endpoints()
# Written out in both clients: it reads the answer as a stream, up to a
# limit, and the generic request takes a path.
WRITTEN_OUT = {"get_attachment", "request"}


def test_every_operation_has_its_endpoint() -> None:
    assert set(OPERATIONS) <= set(ENDPOINTS)


@pytest.mark.parametrize("name", ENDPOINTS)
def test_both_clients_send_the_same_endpoint(name: str) -> None:
    made = getattr(endpoints, name)
    asynchronous = getattr(MailboxClient, name)
    blocking = getattr(SyncMailboxClient, name)
    if name in WRITTEN_OUT:
        for method in (asynchronous, blocking):
            assert f"endpoints.{name}(" in inspect.getsource(method)
        return
    assert asynchronous.__wrapped__ is made, f"MailboxClient.{name}"
    assert blocking.__wrapped__ is made, f"SyncMailboxClient.{name}"


def test_every_record_is_exported_by_the_package() -> None:
    assert set(models.__all__) <= set(benethos_mailbox_client.__all__)
