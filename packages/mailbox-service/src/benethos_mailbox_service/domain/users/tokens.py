"""The API tokens of users, issued and revoked within the caller's
rights. A token's secret is shown once, when it is issued."""

from __future__ import annotations

from datetime import datetime

from ...data.models import ApiToken
from ...data.storage import TokenRepository
from ...errors import missing
from ..activity import ActivityLog, Actor
from ..activity import users as said
from ..auth import AuthService, TokenState
from ..rights import Access
from .rules import UserRules, named


class TokenService:
    def __init__(
        self,
        tokens: TokenRepository,
        auth: AuthService,
        rules: UserRules,
        activity: ActivityLog,
    ) -> None:
        self._tokens = tokens
        self._auth = auth
        self._rules = rules
        self._activity = activity

    def list_tokens(self, access: Access, user_id: str) -> list[ApiToken]:
        self._rules.managed(access, "list_tokens", user_id)
        return self._tokens.list_for_user(user_id)

    def token_state(self, token: ApiToken) -> TokenState:
        """Active, expired or revoked, by the service's clock."""
        return self._auth.state_of(token)

    def create_token(
        self,
        access: Access,
        user_id: str,
        name: str,
        expires_at: datetime | None = None,
    ) -> tuple[ApiToken, str]:
        owner = self._rules.managed(access, "create_token", user_id)
        name = named("a token", name)
        with self._activity.atomic():
            token, plain = self._auth.issue_token(user_id, name, expires_at)
            self._activity.record(
                said.TokenIssued(
                    by=Actor.of(access),
                    token_id=token.id,
                    token_name=token.name,
                    user=owner,
                    expires_at=token.expires_at,
                )
            )
        return token, plain

    def revoke_token(self, access: Access, user_id: str, token_id: str) -> ApiToken:
        owner = self._rules.managed(access, "revoke_token", user_id)
        before = self._tokens.get(token_id)
        if before.user_id != user_id:
            raise missing("token", token_id)
        with self._activity.atomic():
            token = self._auth.revoke_token(token_id)
            if before.revoked_at is None:
                self._activity.record(
                    said.TokenRevoked(
                        by=Actor.of(access),
                        token_id=token.id,
                        token_name=token.name,
                        user=owner,
                    )
                )
        return token
