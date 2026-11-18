from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from ....data.models import Account, AccountStatus, Page, ProviderType
from ....domain.accounts import Rename
from ..deps import Accounts, Caller, Limit
from ..schemas import AccountCreate, AccountUpdate, ServerName, ServerNameList

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
    limit: Limit = 50,
    cursor: str | None = None,
) -> Page[Account]:
    """The accounts the caller may list, by address regardless of case.
    The filter parameters narrow the list together, before it is paged."""
    return accounts.page(
        caller,
        limit=limit,
        cursor=cursor,
        address=address,
        provider=provider,
        status=status,
    )


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
    accepts them. A server the settings did not name before needs every
    credential again: a stored one goes to no other server."""
    return await accounts.update(
        caller,
        account_id,
        rename=(
            Rename(data.display_name)
            if "display_name" in data.model_fields_set
            else None
        ),
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


@router.get("/{account_id}/server-names")
async def list_server_names(
    account_id: str, caller: Caller, accounts: Accounts
) -> ServerNameList:
    """The names receiving servers wrote into the newest ten mails of the
    inbox, for choosing `settings.authserv_id`. A mail can carry any name:
    take the one the server writes on every mail. The service never sets
    it. Empty for an account that names its server itself, as Gmail and
    Microsoft do. Needs `update_account`."""
    found = await accounts.server_names(caller, account_id)
    return ServerNameList(
        items=[ServerName(id=n.id, count=n.count, of=n.of) for n in found]
    )
