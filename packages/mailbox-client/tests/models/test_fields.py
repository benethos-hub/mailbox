"""Every record named like a schema of docs/openapi.json holds each of
its fields. A field the API adds and the client forgets fails here."""

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
# Records that share a name with a schema but hold something else.
OTHER = {
    "Attachment": "the bytes of an attachment, the API's are its metadata",
    "WebhookDetail": "the webhook beside its posts, the API's is flat",
}
RECORDS = sorted(
    name
    for name in models.__all__
    if name in SCHEMAS
    and name not in OTHER
    and dataclasses.is_dataclass(getattr(models, name))
)


def test_records_are_held_to_the_schemas() -> None:
    assert len(RECORDS) > 20


@pytest.mark.parametrize("name", RECORDS)
def test_a_record_holds_every_field_of_its_schema(name: str) -> None:
    fields = {f.name for f in dataclasses.fields(getattr(models, name))}
    wanted = {RENAMED.get(p, p) for p in SCHEMAS[name].get("properties", {})}
    assert fields == wanted
