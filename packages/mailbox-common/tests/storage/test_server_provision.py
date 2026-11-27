"""The statements of a database of its own for an instance, without a
server: plain names alone, quoted where PostgreSQL reserves the word,
never a password."""

from __future__ import annotations

import pytest

from benethos_mailbox_common.storage.errors import OWN, StorageError
from benethos_mailbox_common.storage.server_provision import (
    Instance,
    instance_statements,
    reading_statements,
)

FOUND = Instance(role="agent_one", database="user", reader="read", login="cockpit")


def test_a_reserved_word_is_quoted() -> None:
    assert instance_statements(FOUND, OWN) == [
        "CREATE ROLE agent_one LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT",
        'CREATE DATABASE "user" OWNER agent_one',
        'REVOKE CONNECT, TEMPORARY ON DATABASE "user" FROM PUBLIC',
    ]
    assert reading_statements(FOUND) == [
        "CREATE ROLE read NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE",
        "CREATE ROLE cockpit LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE IN ROLE read",
    ]


@pytest.mark.parametrize("field", ["role", "database", "reader", "login"])
def test_a_name_that_is_not_plain_is_refused(field: str) -> None:
    values = {
        "role": FOUND.role,
        "database": FOUND.database,
        "reader": FOUND.reader,
        "login": FOUND.login,
        field: 'x"; DROP ROLE y',
    }
    with pytest.raises(StorageError, match="no plain name"):
        instance_statements(Instance(**values), OWN)
