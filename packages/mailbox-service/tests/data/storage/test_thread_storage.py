"""The threads of the id mapping store, the same tests for both
implementations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from itertools import count

from benethos_mailbox_service.data.storage import (
    IndexChanges,
    MessageIndexRepository,
    ThreadChain,
)

from .index_helpers import ACC, entry


def threads() -> Callable[[], str]:
    numbers = count(1)
    return lambda: f"thr_{next(numbers)}"


def message(n: int, *headers: str) -> ThreadChain:
    return ThreadChain(f"msg_{n}", headers)


def thread_of(index: MessageIndexRepository, n: int) -> str | None:
    found = index.get(ACC, f"msg_{n}")
    assert found is not None
    return found.thread_id


def test_a_reply_joins_the_thread_of_what_it_answers(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(1), entry(2, "f_sent"), entry(3)])
    new = threads()
    assert index.thread(ACC, [message(1, "<1@x>")], new) == {}
    assert index.thread(ACC, [message(2, "<2@x>", "<1@x>")], new) == {}
    index.thread(ACC, [message(3, "<3@x>")], new)
    assert (thread_of(index, 1), thread_of(index, 2)) == ("thr_1", "thr_1")
    assert thread_of(index, 3) == "thr_2"
    assert [e.id for e in index.in_thread(ACC, "thr_1")] == ["msg_1", "msg_2"]
    assert index.threads_of(ACC, ["msg_1", "msg_3", "msg_9"]) == {
        "msg_1": "thr_1",
        "msg_3": "thr_2",
    }


def test_the_original_after_its_reply_and_two_answers_to_a_missing_one(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(n) for n in range(1, 5)])
    new = threads()
    index.thread(ACC, [message(2, "<2@x>", "<1@x>")], new)
    index.thread(ACC, [message(1, "<1@x>")], new)
    # Both answer <9@x>, which the mailbox does not hold.
    index.thread(ACC, [message(3, "<3@x>", "<9@x>"), message(4, "<4@x>", "<9@x>")], new)
    assert [thread_of(index, n) for n in range(1, 5)] == [
        "thr_1",
        "thr_1",
        "thr_2",
        "thr_2",
    ]


def test_a_message_that_ties_two_threads_merges_the_younger_into_the_older(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(n) for n in range(1, 6)])
    new = threads()
    index.thread(ACC, [message(1, "<1@x>"), message(4, "<4@x>", "<1@x>")], new)
    index.thread(ACC, [message(2, "<2@x>")], new)
    merged = index.thread(ACC, [message(3, "<3@x>", "<2@x>", "<1@x>")], new)
    assert merged == {"msg_2": "thr_1"}
    assert [thread_of(index, n) for n in (1, 2, 3, 4)] == ["thr_1"] * 4
    assert index.in_thread(ACC, "thr_2") == []
    # The links of the younger thread lead to the older one now.
    index.thread(ACC, [message(5, "<5@x>", "<2@x>")], new)
    assert thread_of(index, 5) == "thr_1"


def test_a_message_without_headers_is_a_thread_of_its_own(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(1), entry(2)])
    new = threads()
    index.thread(ACC, [message(1), message(2)], new)
    assert (thread_of(index, 1), thread_of(index, 2)) == ("thr_1", "thr_2")


def test_threading_again_changes_nothing(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1)])
    new = threads()
    index.thread(ACC, [message(1, "<1@x>")], new)
    assert index.thread(ACC, [message(1, "<1@x>")], new) == {}
    assert thread_of(index, 1) == "thr_1"


def test_a_message_the_index_does_not_know_is_passed_over(
    index: MessageIndexRepository,
) -> None:
    new = threads()
    assert index.thread(ACC, [message(1, "<1@x>")], new) == {}
    index.add(ACC, [entry(2)])
    index.thread(ACC, [message(2, "<2@x>", "<1@x>")], new)
    assert thread_of(index, 2) == "thr_1"


def test_the_entries_without_a_thread_oldest_first(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(n) for n in range(1, 5)])
    index.thread(ACC, [message(2, "<2@x>")], threads())
    assert [e.id for e in index.unthreaded(ACC, 2)] == ["msg_1", "msg_3"]
    assert [e.id for e in index.unthreaded(ACC, 9)] == ["msg_1", "msg_3", "msg_4"]
    assert index.unthreaded("acc_2", 9) == []


def test_a_move_keeps_the_thread(index: MessageIndexRepository) -> None:
    index.add(ACC, [entry(1), entry(2)])
    index.thread(ACC, [message(1, "<1@x>")], threads())
    moved = replace(entry(1, "f_archive", "<1@x>"), native_id="n7")
    index.relocate(ACC, moved)
    index.apply(
        ACC,
        IndexChanges(updated=[replace(moved, folder_id="f_sent", native_id="n8")]),
    )
    found = index.get(ACC, "msg_1")
    assert found is not None
    assert (found.folder_id, found.thread_id) == ("f_sent", "thr_1")


def test_a_thread_without_messages_loses_its_links(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(n) for n in range(1, 6)])
    new = threads()
    index.thread(ACC, [message(1, "<1@x>"), message(2, "<2@x>", "<1@x>")], new)
    index.thread(ACC, [message(3, "<3@x>")], new)
    # One message of two goes: the thread keeps its links.
    index.apply(ACC, IndexChanges(removed=["msg_1"]))
    index.thread(ACC, [message(4, "<4@x>", "<1@x>")], new)
    assert thread_of(index, 4) == "thr_1"
    # The last one goes: an answer to it begins anew.
    index.drop(ACC, "msg_3")
    index.thread(ACC, [message(5, "<5@x>", "<3@x>")], new)
    assert thread_of(index, 5) == "thr_3"


def test_a_place_taken_over_ends_the_thread_of_the_entry_that_held_it(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(1), entry(2)])
    new = threads()
    index.thread(ACC, [message(1, "<1@x>"), message(2, "<2@x>")], new)
    # msg_2 moves to the place of msg_1, which is gone meanwhile.
    index.relocate(ACC, replace(entry(2), native_id="n1"))
    assert index.get(ACC, "msg_1") is None
    index.add(ACC, [entry(3)])
    index.thread(ACC, [message(3, "<3@x>", "<1@x>")], new)
    assert thread_of(index, 3) == "thr_3"


def test_forgetting_an_account_forgets_its_threads(
    index: MessageIndexRepository,
) -> None:
    index.add(ACC, [entry(1)])
    index.thread(ACC, [message(1, "<1@x>")], threads())
    index.forget_account(ACC)
    index.add(ACC, [entry(2)])
    index.thread(ACC, [message(2, "<2@x>", "<1@x>")], lambda: "thr_new")
    assert thread_of(index, 2) == "thr_new"
