"""Old records go when the service starts, not with the first new one."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from benethos_mailbox_service.assembly import build_services, create_app
from benethos_mailbox_service.common.clock import utc_now
from benethos_mailbox_service.config import Settings
from benethos_mailbox_service.domain.activity import Actor
from benethos_mailbox_service.domain.activity import users as said

from ..conftest import ADMIN


def test_the_audit_is_purged_when_the_service_starts() -> None:
    settings = Settings(storage="memory", sync_interval=0, audit_days=1)
    services = build_services(settings)
    old = utc_now() - timedelta(days=3)
    deleted = said.RoleDeleted(by=Actor("Anna", "usr_a"), role_id="r", at=old)
    services.audit.keep(deleted)
    assert services.audit.list_activity(ADMIN, limit=10).items

    with TestClient(create_app(settings, services)):
        assert services.audit.list_activity(ADMIN, limit=10).items == []
    assert len(services.purges) == 3
