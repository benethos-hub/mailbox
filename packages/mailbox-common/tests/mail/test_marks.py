"""The marks of RFC 8621 a person sees, and the words for them."""

from __future__ import annotations

from benethos_mailbox_common.mail import marks


def test_a_mark_is_found_without_case() -> None:
    assert marks.mark_of("$Answered") is marks.ANSWERED
    assert marks.mark_of("$important") is None


def test_the_marks_a_person_sees_in_their_order() -> None:
    held = ["work", "$Junk", "$notjunk", "$answered", "$hasattachment"]
    assert [m.word for m in marks.marks_of(held)] == ["answered", "junk"]


def test_a_persons_own_keywords() -> None:
    assert marks.personal(["$answered", "work", "$important", "Later"]) == [
        "work",
        "Later",
    ]
    assert marks.protocol("$important") and not marks.protocol("work")
