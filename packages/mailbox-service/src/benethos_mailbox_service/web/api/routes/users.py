"""The caller, users, their tokens, and roles."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from ....data.models import ApiToken, Page, Role, User
from ....domain.rights import permissions
from ....domain.users import PasswordService, TokenService
from ..deps import Caller, Limit, Passwords, Roles, Tokens, Users
from ..schemas import (
    Me,
    PasswordSet,
    PasswordSetResult,
    PermissionCatalogue,
    RoleCreate,
    RoleReplace,
    TokenCreate,
    TokenCreated,
    TokenInfo,
    UserCreate,
    UserInfo,
    UserUpdate,
)

# The caller itself and the catalogue of rights: every token may ask.
caller_router = APIRouter(tags=["users"])
# Users, their tokens and passwords, roles.
router = APIRouter(tags=["users"])


@caller_router.get("/me")
async def get_me(caller: Caller, users: Users) -> Me:
    return Me.model_validate(users.me(caller), from_attributes=True)


@caller_router.get("/permissions")
async def list_permissions(caller: Caller) -> PermissionCatalogue:
    return PermissionCatalogue(
        groups={group: list(ops) for group, ops in permissions.GROUPS.items()},
        service=list(permissions.SERVICE_GROUPS),
    )


@router.get("/users")
async def list_users(
    caller: Caller,
    users: Users,
    passwords: Passwords,
    name: Annotated[
        str | None, Query(description="Part of the name, regardless of case")
    ] = None,
    role: Annotated[str | None, Query(description="A role the user holds")] = None,
    disabled: bool | None = None,
    ui_sign_in: Annotated[
        bool | None,
        Query(description="`false`: the API users, who work with tokens only"),
    ] = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[UserInfo]:
    """Every user, by name regardless of case. The filter parameters
    narrow the list together, before it is paged."""
    found = users.page_users(
        caller,
        limit=limit,
        cursor=cursor,
        name=name,
        role=role,
        disabled=disabled,
        ui_sign_in=ui_sign_in,
    )
    return Page[UserInfo](
        items=[_user(passwords, user) for user in found.items],
        next_cursor=found.next_cursor,
    )


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate, caller: Caller, users: Users, passwords: Passwords
) -> UserInfo:
    made = users.create_user(
        caller,
        data.name,
        data.roles,
        data.grants,
        service=data.service,
        ui_sign_in=data.ui_sign_in,
    )
    return _user(passwords, made)


@router.get("/users/{user_id}")
async def get_user(
    user_id: str, caller: Caller, users: Users, passwords: Passwords
) -> UserInfo:
    return _user(passwords, users.get_user(caller, user_id))


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    caller: Caller,
    users: Users,
    passwords: Passwords,
) -> UserInfo:
    changed = users.update_user(
        caller,
        user_id,
        name=data.name,
        roles=data.roles,
        service=data.service,
        grants=data.grants,
        disabled=data.disabled,
        ui_sign_in=data.ui_sign_in,
    )
    return _user(passwords, changed)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, caller: Caller, users: Users) -> None:
    users.delete_user(caller, user_id)


@router.post("/users/{user_id}/password")
async def set_password(
    user_id: str, data: PasswordSet, caller: Caller, passwords: Passwords
) -> PasswordSetResult:
    """Give a user with UI sign-in a password, which it must change at its
    next sign-in. Without one in the request the service makes a one-time
    password and answers it, this once. Whoever sets a password can sign
    in as that user: the caller must hold every right the user holds.
    Refused for the caller itself and for an API user (`409`)."""
    new = data.password.get_secret_value() if data.password is not None else None
    password = await passwords.set_password(caller, user_id, new)
    return PasswordSetResult(password=password)


@router.get("/users/{user_id}/tokens")
async def list_tokens(user_id: str, caller: Caller, tokens: Tokens) -> list[TokenInfo]:
    return [_info(tokens, t) for t in tokens.list_tokens(caller, user_id)]


@router.post("/users/{user_id}/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(
    user_id: str, data: TokenCreate, caller: Caller, tokens: Tokens
) -> TokenCreated:
    token, plain = tokens.create_token(caller, user_id, data.name, data.expires_at)
    info = _info(tokens, token)
    return TokenCreated(**info.model_dump(), token=plain)


@router.delete("/users/{user_id}/tokens/{token_id}", status_code=204)
async def revoke_token(
    user_id: str, token_id: str, caller: Caller, tokens: Tokens
) -> None:
    """Ends the token at once. It stays in the user's list with its
    `revoked_at`, so a revoked token can still be told from one that
    never was."""
    tokens.revoke_token(caller, user_id, token_id)


@router.get("/roles")
async def list_roles(caller: Caller, roles: Roles) -> list[Role]:
    return roles.list_roles(caller)


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: RoleCreate, caller: Caller, roles: Roles) -> Role:
    return roles.create_role(caller, data.id, data.grants, data.service)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, caller: Caller, roles: Roles) -> Role:
    return roles.get_role(caller, role_id)


@router.put("/roles/{role_id}")
async def replace_role(
    role_id: str, data: RoleReplace, caller: Caller, roles: Roles
) -> Role:
    return roles.replace_role(caller, role_id, data.grants, data.service)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, caller: Caller, roles: Roles) -> None:
    roles.delete_role(caller, role_id)


def _user(passwords: PasswordService, user: User) -> UserInfo:
    """A user as the API shows it: with how it signs in to the UI."""
    return UserInfo.of(user, passwords.sign_in_state(user))


def _info(tokens: TokenService, token: ApiToken) -> TokenInfo:
    """A token as the API shows it: never its hash, with its state."""
    return TokenInfo.of(token, tokens.token_state(token))
