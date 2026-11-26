"""The server of the suite: it answers, and a schema of a test is gone
after it."""

from __future__ import annotations

from ..postgres_helpers import connect, schema, schemas


def test_the_server_is_postgresql_19_or_newer() -> None:
    with connect() as conn:
        row = conn.execute("SHOW server_version_num").fetchone()
    assert row is not None
    assert int(row[0]) >= 190000


def test_a_schema_of_a_test_is_gone_after_it() -> None:
    with schema() as made:
        assert made in schemas()
    assert made not in schemas()
