"""The status of the service: the sync worker and the accounts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ....data.models import AccountStatus, ProviderType
from ....domain import system


class WorkerStatus(BaseModel):
    """What the sync worker does. Kept in its memory: empty again after a
    restart."""

    interval: float = Field(description="Seconds between two rounds over the accounts")
    push: bool = Field(
        description="Whether watchers wait for a server to report a change"
    )
    last_pass_at: datetime | None = Field(
        description="When the last round ended, null before the first"
    )
    watchers: int = Field(description="How many accounts watchers may wait on at once")
    watching: int = Field(
        description="How many accounts watchers wait on now, of every account"
    )


class AccountSync(BaseModel):
    """An account and how its sync goes."""

    id: str
    email: str
    provider: ProviderType
    status: AccountStatus
    synced: bool = Field(description="Whether a sync pass does anything for it")
    watching: bool = Field(
        description="Whether a watcher waits for its server to report a change"
    )
    last_sync_at: datetime | None = Field(
        description="The last pass that succeeded, null for none since the start"
    )
    last_error: str | None = Field(
        description="Why the last pass failed. A pass that succeeds clears it"
    )
    last_error_at: datetime | None
    attention: bool = Field(
        description=(
            "Whether a person should look: the account is not connected, "
            "or its last pass failed"
        )
    )

    @classmethod
    def of(cls, health: system.AccountHealth) -> AccountSync:
        account, sync = health.account, health.sync
        return cls(
            id=account.id,
            email=account.email,
            provider=account.provider,
            status=account.status,
            synced=health.synced,
            watching=health.watching,
            last_sync_at=sync.last_sync_at,
            last_error=sync.last_error,
            last_error_at=sync.last_error_at,
            attention=health.attention,
        )


class ServiceStatus(BaseModel):
    """The sync worker and the accounts. Nothing is asked of a provider
    for it."""

    worker: WorkerStatus | None = Field(
        description="Null when the worker is switched off"
    )
    accounts: list[AccountSync]

    @classmethod
    def of(cls, status: system.ServiceStatus) -> ServiceStatus:
        worker = status.worker
        return cls(
            worker=None
            if worker is None
            else WorkerStatus(
                interval=worker.interval,
                push=worker.push,
                last_pass_at=worker.last_pass_at,
                watchers=worker.watchers,
                watching=len(worker.watching),
            ),
            accounts=[AccountSync.of(health) for health in status.accounts],
        )
