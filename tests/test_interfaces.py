"""The public interface of the two libraries other code imports, the
client and the common package, is written in docs/ and held to the code,
as docs/mailbox-service/openapi.json is held to the service. A change to a name, a
signature, a field or a default shows as a diff of the record, to be
read like code: a removed or changed one breaks those who import it."""

from __future__ import annotations

from pathlib import Path

import pytest

from .interface import written

ROOT = Path(__file__).resolve().parents[1]
RECORDS = {
    "benethos_mailbox_client": "docs/mailbox-client/client-interface.json",
    "benethos_mailbox_common": "docs/mailbox-common/common-interface.json",
}


@pytest.mark.parametrize("package", sorted(RECORDS))
def test_the_record_of_the_interface_is_current(package: str) -> None:
    record = RECORDS[package]
    held = (ROOT / record).read_text(encoding="utf-8")
    assert held == written(package), (
        f"{record} is stale, regenerate it with "
        f"`uv run python tests/interface.py {package} > {record}` "
        "and review the diff"
    )


def test_a_record_names_what_a_caller_imports() -> None:
    client = (ROOT / RECORDS["benethos_mailbox_client"]).read_text("utf-8")
    common = (ROOT / RECORDS["benethos_mailbox_common"]).read_text("utf-8")
    for named in ('"MailboxClient"', '"SyncMailboxClient"', '"message_body"'):
        assert named in client
    assert '"Mark"' in common
