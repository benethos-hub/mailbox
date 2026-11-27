"""The errors of the storage, and the record of the ones a program has
raised."""

from __future__ import annotations

from benethos_mailbox_common.storage import errors


class _ProgramError(Exception):
    """The base of a program's own errors."""


class _FailedError(_ProgramError, errors.StorageError):
    pass


def test_without_a_record_the_group_raises_its_own() -> None:
    away = errors.OWN.unavailable(7, "lost")

    assert isinstance(away, errors.StorageError)
    assert (away.retry_after, away.cause) == (7, "lost")
    assert "not available" in str(away)
    assert str(errors.OWN.missing("account", "acc_1")) == "account acc_1 not found"
    assert isinstance(errors.OWN.in_use("held"), errors.StorageError)
    assert isinstance(errors.OWN.not_empty("tables"), errors.StorageError)


def test_a_program_hands_in_its_own_classes() -> None:
    record = errors.Errors(failed=_FailedError)

    raised = record.failed("the database failed")

    assert isinstance(raised, _ProgramError)
    assert isinstance(raised, errors.StorageError)
    assert record.conflict is errors.ConflictError
