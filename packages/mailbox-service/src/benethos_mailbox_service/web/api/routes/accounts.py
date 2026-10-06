from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from ....data.models import Account, AccountStatus, ProviderType
from ..deps import Accounts, Caller
from ..schemas import AccountCreate, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(
    caller: Caller,
    accounts: Accounts,
    address: Annotated[
        str | None, Query(description="Part of the address, regardless of case")
    ] = None,
    provider: ProviderType | None = None,
    status: AccountStatus | None = None,
) -> list[Account]:
    """The accounts the caller may list. The filter parameters narrow the
    list together."""
    return accounts.list(caller, address=address, provider=provider, status=status)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreate, caller: Caller, accounts: Accounts
) -> Account:
    return await accounts.create(
        caller,
        data.provider,
        data.email,
        data.display_name,
        data.settings,
        data.credentials,
    )


@router.get("/{account_id}")
async def get_account(account_id: str, caller: Caller, accounts: Accounts) -> Account:
    return accounts.get(caller, account_id)


@router.patch("/{account_id}")
async def update_account(
    account_id: str, data: AccountUpdate, caller: Caller, accounts: Accounts
) -> Account:
    """Change the display name, settings or credentials. New settings or
    credentials are tried first: nothing is stored unless the provider
    accepts them."""
    return await accounts.update(
        caller,
        account_id,
        display_name=data.display_name,
        rename="display_name" in data.model_fields_set,
        settings=data.settings,
        credentials=data.credentials,
    )


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: str, caller: Caller, accounts: Accounts) -> None:
    await accounts.delete(caller, account_id)


@router.post("/{account_id}/verify")
async def verify_account(
    account_id: str, caller: Caller, accounts: Accounts
) -> Account:
    return await accounts.verify(caller, account_id)
