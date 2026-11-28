"""The state of an agent in a database of its own on PostgreSQL: the
methods of the store as on a file, one writer, the schema of the role
made where it is missing, a reader at the schema of this version."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_agents.errors import StateInUseError
from benethos_mailbox_agents.records import MessageRef, StepResult
from benethos_mailbox_agents.store import SCHEMA_VERSION, Store

from ..agents_helpers import profile
from ..postgres_helpers import connect, instance

NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
REF = MessageRef(account_id="acc", message_id="m1")


def test_the_store_on_a_server_keeps_what_a_file_keeps() -> None:
    with instance() as server:
        with Store.open_server(server) as store:
            assert store.migrated is not None
            assert store.version == SCHEMA_VERSION
            assert store.enqueue(REF, NOW)
            assert not store.enqueue(REF, NOW)
            assert [row.ref for row in store.due(NOW, 10)] == [REF]
            store.set_state(REF, "done", NOW, attempts=1)
            assert store.enqueue(REF, NOW, again=True)
            store.add_step(
                REF,
                StepResult(step="decision", result={"label": "invoice"}, at=NOW),
                "alias",
            )
            first = store.add_action(
                REF,
                action="add_keyword",
                argument="agent-x",
                before=[],
                stage="shadow",
                executed=False,
                now=NOW,
            )
            assert (
                store.add_action(
                    REF,
                    action="add_keyword",
                    argument="agent-y",
                    before=[],
                    stage="shadow",
                    executed=True,
                    now=NOW,
                )
                == first + 1
            )
            store.open_item(REF, "t1", NOW, NOW)
            store.record_keyword_stage(REF, "suggest")
            assert store.due_items(NOW + timedelta(days=1), "suggest") == []
            assert len(store.due_items(NOW + timedelta(days=1), "full")) == 1
            store.add_call(REF, {"m": 1}, {"a": 2}, NOW)
            assert store.purge_calls(NOW + timedelta(days=1)) == 1
            store.set_cursor("token-1", NOW)
            store.set_progress(NOW)
            store.set_profile(profile(NOW))

        found = Store.read_server(server)
        assert found is not None
        with found as reader:
            assert reader.cursor() == "token-1"
            assert reader.progress() == NOW
            assert reader.labels_since(NOW) == {"invoice": 1}
            assert reader.counts()["pending"] == 1
            assert reader.profile() == profile(NOW)
            assert [a.argument for a in reader.actions(REF)] == ["agent-x", "agent-y"]


def test_one_writer_per_database() -> None:
    with instance() as server, Store.open_server(server):
        with pytest.raises(StateInUseError, match="another agent runs"):
            Store.open_server(server)


def test_the_schema_of_the_role_is_made_by_the_instance() -> None:
    with instance() as server:
        Store.open_server(server).close()
        with connect(server.database) as conn:
            owner = conn.execute(
                "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s",
                (server.role,),
            ).fetchone()
        assert owner == (server.role,)


def test_a_reader_finds_no_state_before_the_first_start() -> None:
    with instance() as server:
        assert Store.read_server(server) is None
