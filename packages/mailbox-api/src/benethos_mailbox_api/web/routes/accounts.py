from __future__ import annotations

from fastapi import APIRouter, status

from ...data.models import Account
from ..deps import Accounts, Caller
from ..schemas import AccountCreate

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(caller: Caller, accounts: Accounts) -> list[Account]:
    return accounts.list(caller)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreate, caller: Caller, accounts: Accounts
) -> Account:
    return accounts.create(
        caller, data.provider, data.email, data.display_name, data.settings
    )


@router.get("/{account_id}")
async def get_account(account_id: str, caller: Caller, accounts: Accounts) -> Account:
    return accounts.get(caller, account_id)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: str, caller: Caller, accounts: Accounts) -> None:
    await accounts.delete(caller, account_id)
