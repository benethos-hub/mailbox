"""Folders and messages of one account."""

from __future__ import annotations

from ..data.models import Folder, Message, MessageSummary, Page
from .accounts import AccountService


class MailboxService:
    def __init__(self, accounts: AccountService) -> None:
        self._accounts = accounts

    async def list_folders(self, account_id: str) -> list[Folder]:
        return await self._accounts.provider(account_id).list_folders()

    async def list_messages(
        self,
        account_id: str,
        *,
        folder_id: str | None,
        query: str | None,
        unread: bool | None,
        limit: int,
        cursor: str | None,
    ) -> Page[MessageSummary]:
        return await self._accounts.provider(account_id).list_messages(
            folder_id, limit=limit, cursor=cursor, query=query, unread=unread
        )

    async def get_message(self, account_id: str, message_id: str) -> Message:
        return await self._accounts.provider(account_id).get_message(message_id)
