"""The state of an agent in a database of its own on PostgreSQL: the
methods of the store as on a file, one writer, the schema of the role
made where it is missing, a reader at the schema of this version."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from benethos_mailbox_agents.errors import ConfigError, StateInUseError
from benethos_mailbox_agents.records import MessageRef, Profile, StepResult
from benethos_mailbox_agents.store import SCHEMA_VERSION, Store

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
            store.set_profile(_profile())

        with Store.open_server(server, read_only=True) as reader:
            assert reader.cursor() == "token-1"
            assert reader.progress() == NOW
            assert reader.labels_since(NOW) == {"invoice": 1}
            assert reader.counts()["pending"] == 1
            assert reader.profile() == _profile()
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


def test_a_reader_needs_a_state_there() -> None:
    with instance() as server:
        with pytest.raises(ConfigError, match="schema version 0"):
            Store.open_server(server, read_only=True)


def _profile() -> Profile:
    return Profile(
        agent="counting",
        instance=None,
        agent_version="1",
        package_version="0.11.1",
        stage="shadow",
        accounts=(),
        keyword="agent-counted",
        poll_seconds=60.0,
        gateway_timeout_seconds=120.0,
        model_alias="",
        prompt_version="",
        started=NOW,
    )
