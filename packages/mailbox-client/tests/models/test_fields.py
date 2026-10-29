"""Every record named like a schema of docs/openapi.json, or named
after one in ``SCHEMA_OF``, holds each of its fields. A field the API
adds and the client forgets fails here."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from benethos_mailbox_client import models

CONTRACT = Path(__file__).resolve().parents[4] / "docs" / "openapi.json"
SCHEMAS = json.loads(CONTRACT.read_text("utf-8"))["components"]["schemas"]
# A field named like a keyword of Python.
RENAMED = {"from": "sender"}
# Fields a record names otherwise than its schema.
RENAMED_IN = {"Sending": {"max_sends_per_day": "max_per_day", "sends_left": "left"}}
# Records that share a name with a schema but hold something else.
OTHER = {
    "Attachment": "the bytes of an attachment, the API's are its metadata",
    "WebhookDetail": "the webhook beside its posts, the API's is flat",
}
# Records named otherwise than the schema they read.
SCHEMA_OF = {
    "Sent": "SendResult",
    "Changes": "ChangePage",
    "Sending": "MeSending",
    "User": "UserInfo",
    "Token": "TokenInfo",
    "Activity": "ActivityRecord",
    "Reference": "MessageReference",
    "Permissions": "PermissionCatalogue",
    "Status": "ServiceStatus",
    "Worker": "WorkerStatus",
    "AccountHealth": "AccountSync",
    "StoredCredential": "CredentialInfo",
    "DeviceSignIn": "DeviceOAuthStarted",
    "DeviceSignInState": "DeviceOAuthState",
    "AttachedFile": "Attachment",
}
RECORDS = sorted(
    name
    for name in models.__all__
    if SCHEMA_OF.get(name, name) in SCHEMAS
    and name not in OTHER
    and dataclasses.is_dataclass(getattr(models, name))
)


def test_records_are_held_to_the_schemas() -> None:
    assert len(RECORDS) > 20
    assert set(SCHEMA_OF) <= set(RECORDS)


@pytest.mark.parametrize("name", RECORDS)
def test_a_record_holds_every_field_of_its_schema(name: str) -> None:
    fields = {f.name for f in dataclasses.fields(getattr(models, name))}
    renamed = {**RENAMED, **RENAMED_IN.get(name, {})}
    schema = SCHEMAS[SCHEMA_OF.get(name, name)]
    wanted = {renamed.get(p, p) for p in schema.get("properties", {})}
    assert fields == wanted
