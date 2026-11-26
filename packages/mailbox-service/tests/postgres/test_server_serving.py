"""One service per schema: a second on the same schema is refused while
the first runs, and two schemas of one database do not meet."""

from __future__ import annotations

import pytest

from benethos_mailbox_service.errors import StorageError

from ..postgres_helpers import database, schema


def test_a_second_service_on_the_schema_is_refused() -> None:
    with schema() as name:
        first, second = database(name), database(name)
        try:
            with first.serving() as held:
                assert held is True
                with pytest.raises(StorageError, match="another service runs"):
                    with second.serving():
                        pass
            with second.serving() as held:
                assert held is True
        finally:
            first.close()
            second.close()


def test_the_lock_goes_with_the_connection() -> None:
    with schema() as name:
        first = database(name)
        with first.serving():
            first.close()
            second = database(name)
            try:
                with second.serving() as held:
                    assert held is True
            finally:
                second.close()


def test_two_schemas_of_one_database_do_not_meet() -> None:
    with schema() as one, schema() as other:
        first, second = database(one), database(other)
        try:
            with first.serving(), second.serving() as held:
                assert held is True
        finally:
            first.close()
            second.close()


def test_a_database_serving_still_reads_and_writes() -> None:
    with schema() as name:
        db = database(name)
        try:
            with db.serving():
                assert db.schema_version() == 26
                with db.transaction():
                    pass
        finally:
            db.close()
