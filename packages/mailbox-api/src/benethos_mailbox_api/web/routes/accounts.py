from __future__ import annotations

from fastapi import APIRouter, status

from ...data.models import Account
from ..deps import Accounts
from ..schemas import AccountCreate

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(accounts: Accounts) -> list[Account]:
    return accounts.list()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(data: AccountCreate, accounts: Accounts) -> Account:
    return accounts.create(data.provider, data.email, data.display_name, data.settings)


@router.get("/{account_id}")
async def get_account(account_id: str, accounts: Accounts) -> Account:
    return accounts.get(account_id)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: str, accounts: Accounts) -> None:
    await accounts.delete(account_id)
