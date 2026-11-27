"""TLS to the server of the tests, measured: the arguments the place
hands libpq for a host other than this one connect only with the test
CA and the server's name, and "off" connects without TLS. The test
reaches the server by a name its certificate holds, at 127.0.0.1."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import psycopg
import pytest

from benethos_mailbox_common.storage.server_engine import tls_arguments
from benethos_mailbox_service.data.storage import Database, Server, ServerPlace

from ..postgres_helpers import admin, schema
from ..schema_helpers import driver_of

# A name in the certificate of the test server, and one that is not.
NAMED = "db.mailbox.test"
UNNAMED = "other.mailbox.test"


def _connect(host: str, tls: Literal["verify", "off"], ca: Path | None) -> bool:
    """Whether the connection with what the place tells libpq is over
    TLS. A refused one raises."""
    who = admin()
    with psycopg.connect(
        host=host,
        hostaddr=who.host,
        port=who.port,
        user=who.user,
        password=who.password,
        dbname=who.database,
        connect_timeout=10,
        **tls_arguments(host, tls, ca),
    ) as conn:
        row = conn.execute(
            "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        ).fetchone()
    assert row is not None
    return bool(row[0])


def test_the_test_ca_and_the_name_connect_over_tls() -> None:
    assert _connect(NAMED, "verify", admin().ca_file) is True


def test_another_ca_is_refused() -> None:
    with pytest.raises(psycopg.OperationalError, match="certificate verify failed"):
        _connect(NAMED, "verify", admin().other_ca_file)


def test_the_authorities_of_the_system_refuse_the_test_ca() -> None:
    with pytest.raises(psycopg.OperationalError, match="certificate verify failed"):
        _connect(NAMED, "verify", None)


def test_a_name_the_certificate_does_not_hold_is_refused() -> None:
    with pytest.raises(psycopg.OperationalError):
        _connect(UNNAMED, "verify", admin().ca_file)


def test_off_connects_without_tls() -> None:
    assert _connect(NAMED, "off", None) is False


@pytest.mark.parametrize(("tls", "encrypted"), [("verify", True), ("off", False)])
def test_the_place_on_this_host(tls: Literal["verify", "off"], encrypted: bool) -> None:
    who = admin()
    with schema() as name:
        db = Database(
            place=ServerPlace(
                Server(
                    host=who.host,
                    port=who.port,
                    database=who.database,
                    role=who.user,
                    password=who.password,
                    schema=name,
                    tls=tls,
                )
            )
        )
        try:
            with db.connected() as conn:
                found = (
                    driver_of(conn)
                    .execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                    .fetchone()
                )
        finally:
            db.close()
    assert found is not None and bool(found[0]) is encrypted
