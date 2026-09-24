"""The caller, users, their tokens, and roles."""

from __future__ import annotations

from fastapi import APIRouter, status

from ...data.models import Role, User
from ...domain import permissions
from ..deps import Caller, Users
from ..schemas import (
    Me,
    PermissionCatalogue,
    RoleCreate,
    RoleReplace,
    TokenCreate,
    TokenCreated,
    TokenInfo,
    UserCreate,
    UserUpdate,
)

router = APIRouter(tags=["users"])


@router.get("/me")
async def get_me(caller: Caller, users: Users) -> Me:
    rights = users.me(caller)
    return Me(
        user_id=rights.user_id,
        name=rights.name,
        accounts=rights.accounts,
        operations=rights.operations,
    )


@router.get("/permissions")
async def list_permissions(caller: Caller) -> PermissionCatalogue:
    return PermissionCatalogue(
        groups={group: list(ops) for group, ops in permissions.GROUPS.items()}
    )


@router.get("/users")
async def list_users(caller: Caller, users: Users) -> list[User]:
    return users.list_users(caller)


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(data: UserCreate, caller: Caller, users: Users) -> User:
    return users.create_user(caller, data.name, data.roles, data.grants)


@router.get("/users/{user_id}")
async def get_user(user_id: str, caller: Caller, users: Users) -> User:
    return users.get_user(caller, user_id)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str, data: UserUpdate, caller: Caller, users: Users
) -> User:
    return users.update_user(
        caller,
        user_id,
        name=data.name,
        roles=data.roles,
        grants=data.grants,
        disabled=data.disabled,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, caller: Caller, users: Users) -> None:
    users.delete_user(caller, user_id)


@router.get("/users/{user_id}/tokens")
async def list_tokens(user_id: str, caller: Caller, users: Users) -> list[TokenInfo]:
    return [TokenInfo.of(t) for t in users.list_tokens(caller, user_id)]


@router.post("/users/{user_id}/tokens", status_code=status.HTTP_201_CREATED)
async def create_token(
    user_id: str, data: TokenCreate, caller: Caller, users: Users
) -> TokenCreated:
    token, plain = users.create_token(caller, user_id, data.name, data.expires_at)
    return TokenCreated(**TokenInfo.of(token).model_dump(), token=plain)


@router.delete("/users/{user_id}/tokens/{token_id}")
async def revoke_token(
    user_id: str, token_id: str, caller: Caller, users: Users
) -> TokenInfo:
    return TokenInfo.of(users.revoke_token(caller, user_id, token_id))


@router.get("/roles")
async def list_roles(caller: Caller, users: Users) -> list[Role]:
    return users.list_roles(caller)


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(data: RoleCreate, caller: Caller, users: Users) -> Role:
    return users.create_role(caller, data.id, data.grants)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, caller: Caller, users: Users) -> Role:
    return users.get_role(caller, role_id)


@router.put("/roles/{role_id}")
async def replace_role(
    role_id: str, data: RoleReplace, caller: Caller, users: Users
) -> Role:
    return users.replace_role(caller, role_id, data.grants)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, caller: Caller, users: Users) -> None:
    users.delete_role(caller, role_id)
