"""What a session on a database server is told when it starts."""

from __future__ import annotations

from benethos_mailbox_common.storage.server_engine import server_options


def test_the_server_ends_a_silent_session_within_half_a_minute() -> None:
    options = server_options("agent_one").split()

    assert options[0] == "-csearch_path=agent_one"
    assert {
        "-ctcp_keepalives_idle=10",
        "-ctcp_keepalives_interval=5",
        "-ctcp_keepalives_count=3",
        "-ctcp_user_timeout=15000",
    } <= set(options)
    assert "-cdefault_transaction_read_only=on" not in options


def test_a_reader_is_told_that_every_transaction_only_reads() -> None:
    assert (
        "-cdefault_transaction_read_only=on"
        in server_options("agent_one", read_only=True).split()
    )
