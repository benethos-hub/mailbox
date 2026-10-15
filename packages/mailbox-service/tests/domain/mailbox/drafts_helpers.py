"""Addresses of the drafts in the API."""

from __future__ import annotations


def drafts_url(account_id: str, draft_id: str = "") -> str:
    return f"/v1/accounts/{account_id}/drafts" + (f"/{draft_id}" if draft_id else "")
