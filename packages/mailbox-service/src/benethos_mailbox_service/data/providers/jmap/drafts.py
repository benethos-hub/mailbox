"""Drafts in the folder with the drafts role. A draft id names an email
in that folder, any other id is not found. JMAP keeps an email as it was
stored: a replaced draft is a new email with a new id."""

from __future__ import annotations

from ....errors import ProviderError, missing
from ...models import FolderRole, MessageSummary, Page
from ...protocols import jmap
from .. import rules
from . import mappers
from .account import JmapAccount
from .messages import get_raw, list_messages


async def list_drafts(
    account: JmapAccount, limit: int, cursor: str | None
) -> Page[MessageSummary]:
    return await list_messages(account, await _drafts_id(account), limit, cursor, None)


async def save_draft(
    account: JmapAccount, raw: bytes, replaces: str | None
) -> MessageSummary:
    drafts = await _drafts_id(account)
    if replaces is not None:
        await _draft(account, replaces, drafts)
    blob = await account.upload(raw)
    done = await account.one(
        "Email/import",
        {
            "emails": {
                "d": {
                    "blobId": blob,
                    "mailboxIds": {drafts: True},
                    "keywords": {mappers.DRAFT: True, mappers.SEEN: True},
                }
            }
        },
    )
    refused = (done.get("notCreated") or {}).get("d")
    if refused is not None:
        raise jmap.set_error(refused, "draft")
    made = str(((done.get("created") or {}).get("d") or {}).get("id"))
    stored = (await account.emails([made], mappers.SUMMARY_PROPERTIES)).get(made)
    if stored is None:
        raise ProviderError("the draft was stored but cannot be found again")
    if replaces is not None:
        await _destroy(account, replaces, missing_ok=True)
    return mappers.summary(stored)


async def get_draft(account: JmapAccount, draft_id: str) -> bytes:
    await _draft(account, draft_id, await _drafts_id(account))
    return await get_raw(account, draft_id)


async def delete_draft(account: JmapAccount, draft_id: str) -> None:
    await _draft(account, draft_id, await _drafts_id(account))
    await _destroy(account, draft_id)


async def _drafts_id(account: JmapAccount) -> str:
    found = await account.role_id(FolderRole.DRAFTS)
    if found is None:
        raise rules.no_folder(FolderRole.DRAFTS)
    return found


async def _draft(account: JmapAccount, draft_id: str, drafts: str) -> None:
    """Only drafts: any other id is not found, so the draft operations
    reach no other mail."""
    found = (await account.emails([draft_id], ["mailboxIds"])).get(draft_id)
    if found is None or drafts not in (found.get("mailboxIds") or {}):
        raise missing("draft", draft_id)


async def _destroy(
    account: JmapAccount, email_id: str, missing_ok: bool = False
) -> None:
    done = await account.one("Email/set", {"destroy": [email_id]})
    failed = (done.get("notDestroyed") or {}).get(email_id)
    if failed is None or (missing_ok and failed.get("type") == "notFound"):
        return
    raise jmap.set_error(failed, "draft")
