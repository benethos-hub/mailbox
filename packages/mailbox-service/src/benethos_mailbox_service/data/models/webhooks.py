"""Webhooks: a URL that hears of events, signed with a secret (CONCEPT 6.5)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .changes import ChangeKind

CHANGE_KINDS: tuple[ChangeKind, ...] = (
    "message.created",
    "message.updated",
    "message.deleted",
    "message.sent",
    "account.needs_reauth",
)


class WebhookCreate(BaseModel):
    url: str = Field(
        max_length=2000,
        description=(
            "Where the service posts events, http or https. A host in the "
            "local network is allowed."
        ),
    )
    events: list[ChangeKind] = Field(
        default_factory=lambda: list(CHANGE_KINDS),
        min_length=1,
        description="The events to post. Without: every event.",
    )
    accounts: list[str] | None = Field(
        default=None,
        description=(
            "Account ids. Without: every account the creator may read, "
            "accounts added later included."
        ),
    )


class WebhookUpdate(BaseModel):
    """Change a webhook. A field left out stays as it is. Its deliveries and
    where its posts stand stay, its secret too."""

    url: str | None = Field(
        default=None,
        max_length=2000,
        description="Where the service posts events, http or https.",
    )
    events: list[ChangeKind] | None = Field(
        default=None, min_length=1, description="The events to post."
    )
    accounts: list[str] | None = Field(
        default=None,
        description=(
            "Account ids. `null`: every account the owner may read, accounts "
            "added later included. Left out: as it is."
        ),
    )


class Webhook(BaseModel):
    id: str
    url: str
    events: list[ChangeKind]
    accounts: list[str] | None
    user_id: str = Field(description="The user who created it and whose rights apply.")
    created_at: datetime
    last_delivery_at: datetime | None = Field(
        default=None, description="The last post the receiver took."
    )
    last_error: str | None = Field(
        default=None, description="Why the last post failed, if it did."
    )


class WebhookPost(BaseModel):
    """One post to a webhook's receiver."""

    delivery_id: str = Field(description="The `delivery_id` in the post's body.")
    at: datetime
    events: int = Field(description="How many events the post carried.")
    status: int | None = Field(
        description="What the receiver answered. Null when it could not be reached."
    )
    error: str | None = Field(
        description="Why the post failed. Null when the receiver took it."
    )


class WebhookDetail(Webhook):
    deliveries: list[WebhookPost] = Field(
        description="The last posts to the receiver, newest first, up to 20."
    )


class WebhookSecret(BaseModel):
    """A webhook's new signing secret. The one before stops at once."""

    webhook_id: str
    secret: str = Field(
        description=(
            "Signs every post from now on (HMAC-SHA256). Shown once, here. "
            "Keep it with the receiver."
        )
    )


class CreatedWebhook(Webhook):
    secret: str = Field(
        description=(
            "Signs every post (HMAC-SHA256). Shown once, here. Keep it with "
            "the receiver."
        )
    )
