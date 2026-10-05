"""The audit of administration (docs/AUDIT.md): which activities it keeps,
what a record says, who reads it, and how long it keeps it."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from benethos_mailbox_service.data.models import ActivityFilter, ActivityRecord, Grant
from benethos_mailbox_service.data.storage import InMemoryAuditRepository
from benethos_mailbox_service.domain.activity import (
    SERVICE,
    ActivityLog,
    Actor,
    Audit,
    changes,
)
from benethos_mailbox_service.domain.activity import users as said
from benethos_mailbox_service.domain.rights.access import Access
from benethos_mailbox_service.errors import (
    BadRequestError,
    ForbiddenError,
    UnauthorizedError,
)
from benethos_mailbox_service.main import Services

from ...conftest import ADMIN
from .test_activity import _catalogue

AUDIT_MD = Path(__file__).parents[5] / "docs" / "AUDIT.md"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
READER = Grant(accounts=["*"], allow=["mail.read"])


def kept(services: Services, **wanted: object) -> list[ActivityRecord]:
    matching = ActivityFilter.model_validate(wanted) if wanted else None
    return services.audit.list_activity(ADMIN, limit=100, matching=matching).items


def test_the_activities_kept_are_those_audit_md_names() -> None:
    text = AUDIT_MD.read_text(encoding="utf-8")
    section = text.partition("## 2. What is audited")[2].partition("\n## ")[0]
    named = set(re.findall(r"`(\w+\.\w+)`", section))
    assert named == {cls.kind() for cls in _catalogue() if cls.audited}


def test_what_a_person_did_is_kept_with_who_how_and_what(services: Services) -> None:
    anna = services.users.create_user(ADMIN, "Anna", [], [READER])
    token, plain = services.users.create_token(ADMIN, anna.id, "laptop")
    services.users.revoke_token(ADMIN, anna.id, token.id)
    records = kept(services)
    assert [r.activity for r in records] == [
        "users.token_revoked",
        "users.token_issued",
        "users.created",
    ]
    assert [r.record for r in records] == [token.id, token.id, anna.id]
    first = records[-1]
    assert first.id.startswith("evt_")
    assert (first.user_id, first.user_name, first.credential) == (
        ADMIN.user_id,
        "test admin",
        "password",
    )
    assert first.outcome == "done"
    # Who is in its own fields, not in the detail.
    assert first.detail == (
        f"created user Anna ({anna.id}): roles none, 1 grant, signs in to the API"
    )
    assert all(plain not in r.detail for r in records)


def test_a_token_and_the_host_are_named_as_the_credential(
    services: Services,
) -> None:
    access = Access(
        "usr_1",
        "Claude Desktop",
        [],
        "tok_1",
        service=["admin"],
        credential_name="laptop",
        source="10.0.0.7",
    )
    services.users.create_role(access, "readers", [READER])
    by_token = kept(services, activity="users.role_created")[0]
    assert (by_token.credential, by_token.source) == ("token:tok_1", "10.0.0.7")


async def test_a_command_on_the_host(services: Services) -> None:
    await services.users.create_admin("admin")
    record = kept(services, activity="users.created")[0]
    assert (record.user_id, record.user_name, record.credential) == (
        None,
        "the host",
        "host",
    )


async def test_a_failed_sign_in_keeps_no_name_that_was_typed(
    services: Services,
) -> None:
    anna = services.users.create_user(ADMIN, "Anna", [], [], ui_sign_in=True)
    with pytest.raises(UnauthorizedError):
        await services.auth.sign_in("hunter2-typed-here", "x", source="10.0.0.9")
    with pytest.raises(UnauthorizedError):
        await services.auth.sign_in("Anna", "wrong", source="10.0.0.9")
    unknown, known = kept(services, activity="auth.sign_in_failed")[::-1]
    assert unknown.outcome == known.outcome == "refused"
    assert (unknown.user_id, unknown.user_name, unknown.credential) == (
        None,
        "someone",
        None,
    )
    assert unknown.source == "10.0.0.9"
    assert "an unknown name" in unknown.detail
    assert "hunter2" not in unknown.detail
    assert unknown.record is None
    assert known.record == anna.id


def test_what_the_service_does_alone_is_not_kept(services: Services) -> None:
    services.activity.record(changes.ChangesPurged(by=SERVICE, count=3, before=NOW))
    assert kept(services) == []


def test_the_filters_and_the_pages(services: Services) -> None:
    anna = services.users.create_user(ADMIN, "Anna", [], [READER])
    services.users.create_role(ADMIN, "readers", [READER])
    bea_access = Access("usr_bea", "Bea", [], service=["admin"])
    services.users.update_user(bea_access, anna.id, name="Anna B")
    assert [r.activity for r in kept(services, activity="users.role_created")] == [
        "users.role_created"
    ]
    # An area holds its names, and a part of a name is none.
    assert len(kept(services, activity="users")) == 3
    assert kept(services, activity="user") == []
    assert [r.user_name for r in kept(services, user_id="usr_bea")] == ["Bea"]
    assert [r.activity for r in kept(services, record=anna.id)] == [
        "users.changed",
        "users.created",
    ]
    future = datetime.now(UTC) + timedelta(days=1)
    assert kept(services, after=future) == []
    assert len(kept(services, before=future)) == 3

    first = services.audit.list_activity(ADMIN, limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    rest = services.audit.list_activity(ADMIN, limit=2, cursor=first.next_cursor)
    assert [r.activity for r in rest.items] == ["users.created"]
    assert rest.next_cursor is None
    with pytest.raises(BadRequestError):
        services.audit.list_activity(ADMIN, limit=2, cursor="nonsense")


def test_audit_in_service_reads_it_and_audit_in_a_grant_does_not(
    services: Services,
) -> None:
    reader = Access("usr_r", "R", [], service=["audit"])
    assert services.audit.list_activity(reader, limit=10).items == []
    sends_only = Access("usr_s", "S", [Grant(accounts=["*"], allow=["audit"])])
    with pytest.raises(ForbiddenError):
        services.audit.list_activity(sends_only, limit=10)
    users_read = Access("usr_u", "U", [], service=["users.read"])
    with pytest.raises(ForbiddenError):
        services.audit.list_activity(users_read, limit=10)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def created(clock: Clock) -> said.RoleDeleted:
    return said.RoleDeleted(by=Actor("Anna", "usr_a"), role_id="r", at=clock())


def test_old_records_are_purged_once_an_hour_at_most(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    store = InMemoryAuditRepository()
    log = ActivityLog(clock, Audit(store, clock, days=1))
    log.record(created(clock))
    clock.now += timedelta(days=2)
    with caplog.at_level(logging.INFO):
        log.record(created(clock))
    assert len(store.list(limit=10, before=None)) == 1
    assert "purged 1 record older than" in caplog.text
    assert "from the audit" in caplog.text
    # Within the hour nothing is purged again, however old.
    clock.now += timedelta(minutes=30)
    log.record(said.RoleDeleted(by=Actor("Anna", "usr_a"), role_id="r", at=NOW))
    assert len(store.list(limit=10, before=None)) == 2


def test_zero_days_keeps_every_record() -> None:
    clock = Clock()
    store = InMemoryAuditRepository()
    audit = Audit(store, clock, days=0)
    log = ActivityLog(clock, audit)
    log.record(created(clock))
    clock.now += timedelta(days=4000)
    log.record(created(clock))
    assert audit.days == 0
    assert len(store.list(limit=10, before=None)) == 2


class Broken(InMemoryAuditRepository):
    def add(self, record: ActivityRecord) -> None:
        raise OSError("the disk is full")


def test_a_record_that_cannot_be_kept_is_logged_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = Clock()
    log = ActivityLog(clock, Audit(Broken(), clock))
    with caplog.at_level(logging.INFO):
        log.record(created(clock))
    failed = [r for r in caplog.records if r.name.endswith("system.not_audited")]
    assert [r.levelno for r in failed] == [logging.ERROR]
    assert failed[0].getMessage() == (
        "the service could not keep users.role_deleted in the audit: OSError"
    )
    # The activity's own line is there as well.
    assert "deleted role r" in caplog.text


def test_a_secret_noted_is_masked_in_the_record() -> None:
    from benethos_mailbox_service.common import redact

    redact.note("s3cret-in-an-error")
    clock = Clock()
    store = InMemoryAuditRepository()
    ActivityLog(clock, Audit(store, clock)).record(
        said.RoleDeleted(by=Actor("A", "usr_a"), role_id="s3cret-in-an-error")
    )
    (record,) = store.list(limit=10, before=None)
    assert "s3cret" not in record.detail
