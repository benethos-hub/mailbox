"""The caller, users, their tokens, and roles."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from ....data.models import ApiToken, Role, User
from ....domain.rights import permissions
from ....domain.users import UserService
from ..deps import Caller, Users
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

router = APIRouter(tags=["users"])


@router.get("/me")
async def get_me(caller: Caller, users: Users) -> Me:
    return Me.model_validate(users.me(caller), from_attributes=True)


@router.get("/permissions")
async def list_permissions(caller: Caller) -> PermissionCatalogue:
    return PermissionCatalogue(
        groups={group: list(ops) for group, ops in permissions.GROUPS.items()},
        service=list(permissions.SERVICE_GROUPS),
    )


@router.get("/users")
async def list_users(
    caller: Caller,
    users: Users,
    name: Annotated[
        str | None, Query(description="Part of the name, regardless of case")
    ] = None,
    role: Annotated[str | None, Query(description="A role the user holds")] = None,
    disabled: bool | None = None,
    ui_sign_in: Annotated[
        bool | None,
        Query(description="`false`: the API users, who work with tokens only"),
    ] = None,
) -> list[UserInfo]:
    """Every user. The filter parameters narrow the list together."""
    found = users.list_users(
        caller, name=name, role=role, disabled=disabled, ui_sign_in=ui_sign_in
    )
    return [_user(users, user) for user in found]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, caller: Caller, users: Users) -> UserInfo:
    made = users.create_user(
        caller,
        data.name,
        data.roles,
        data.grants,
        service=data.service,
        ui_sign_in=data.ui_sign_in,
    )
    return _user(users, made)


@router.get("/users/{user_id}")
async def get_user(user_id: str, caller: Caller, users: Users) -> UserInfo:
    return _user(users, users.get_user(caller, user_id))


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, data: UserUpdate, caller: Caller, users: Users
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
    return _user(users, changed)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, caller: Caller, users: Users) -> None:
    users.delete_user(caller, user_id)


@router.post("/users/{user_id}/password")
async def set_password(
    user_id: str, data: PasswordSet, caller: Caller, users: Users
) -> PasswordSetResult:
    """Give a user with UI sign-in a password, which it must change at its
    next sign-in. Without one in the request the service makes a one-time
    password and answers it, this once. Whoever sets a password can sign
    in as that user: the caller must hold every right the user holds.
    Refused for the caller itself and for an API user (`409`)."""
    new = data.password.get_secret_value() if data.password is not None else None
    return PasswordSetResult(password=await users.set_password(caller, user_id, new))


@router.get("/users/{user_id}/tokens")
async def list_tokens(user_id: str, caller: Caller, users: Users) -> list[TokenInfo]:
    return [_info(users, t) for t in users.list_tokens(caller, user_id)]


@router.post("/users/{user_id}/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(
    user_id: str, data: TokenCreate, caller: Caller, users: Users
) -> TokenCreated:
    token, plain = users.create_token(caller, user_id, data.name, data.expires_at)
    info = _info(users, token)
    return TokenCreated(**info.model_dump(), token=plain)


@router.delete("/users/{user_id}/tokens/{token_id}")
async def revoke_token(
    user_id: str, token_id: str, caller: Caller, users: Users
) -> TokenInfo:
    token = users.revoke_token(caller, user_id, token_id)
    return _info(users, token)


@router.get("/roles")
async def list_roles(caller: Caller, users: Users) -> list[Role]:
    return users.list_roles(caller)


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: RoleCreate, caller: Caller, users: Users) -> Role:
    return users.create_role(caller, data.id, data.grants, data.service)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, caller: Caller, users: Users) -> Role:
    return users.get_role(caller, role_id)


@router.put("/roles/{role_id}")
async def replace_role(
    role_id: str, data: RoleReplace, caller: Caller, users: Users
) -> Role:
    return users.replace_role(caller, role_id, data.grants, data.service)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, caller: Caller, users: Users) -> None:
    users.delete_role(caller, role_id)


def _user(users: UserService, user: User) -> UserInfo:
    """A user as the API shows it: with how it signs in to the UI."""
    return UserInfo.of(user, users.sign_in_state(user))


def _info(users: UserService, token: ApiToken) -> TokenInfo:
    """A token as the API shows it: never its hash, with its state."""
    return TokenInfo.of(token, users.token_state(token))
