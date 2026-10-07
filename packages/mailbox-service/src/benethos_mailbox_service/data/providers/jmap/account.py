"""The JMAP account on the wire: the credential for each request, method
calls in one request, emails and mailboxes asked for, a source down- and
uploaded. Every part of the adapter goes through one."""

from __future__ import annotations

import base64
from collections.abc import Iterable
from typing import Any, TypeVar

from pydantic import BaseModel

from ....common.chunks import batched
from ....errors import NotFoundError, ProviderError, missing_message
from ...models import Folder, FolderRole
from ...protocols import jmap
from ..base import CredentialReader
from . import mappers
from .shapes import Email, Mailbox

# The name and type a message's source is down- and uploaded as.
SOURCE = ("message.eml", "message/rfc822")

S = TypeVar("S", bound=BaseModel)


class JmapAccount:
    def __init__(
        self,
        client: jmap.JmapClient,
        credentials: CredentialReader,
        auth: str,
        username: str,
    ) -> None:
        self.client = client
        self._credentials = credentials
        self._auth = auth
        self._username = username

    def authorization(self) -> str:
        """The Authorization header, with the credential decrypted for this
        one request."""
        if self._auth == "token":
            return f"Bearer {self._credentials('token').get_secret_value()}"
        password = self._credentials("password").get_secret_value()
        pair = f"{self._username}:{password}".encode()
        return f"Basic {base64.b64encode(pair).decode()}"

    async def id(self) -> str:
        return (await self.client.session()).account_id

    async def call(
        self, *calls: jmap.Invocation, using: Iterable[str] = (jmap.CORE, jmap.MAIL)
    ) -> list[jmap.Invocation]:
        return await self.client.call(list(calls), using)

    async def one(self, name: str, args: dict[str, Any], shape: type[S]) -> S:
        """One method call in a request of its own, its answer read as
        ``shape``."""
        account = await self.id()
        answers = await self.call((name, {"accountId": account, **args}, "0"))
        return jmap.read(answers, "0", shape)

    async def emails(self, ids: list[str], properties: list[str]) -> dict[str, Email]:
        """The emails among ``ids`` that are there, by id, in batches the
        server takes."""
        limit = (await self.client.session()).max_get
        found: dict[str, Email] = {}
        for batch in batched([i for i in ids if mappers.is_id(i)], limit):
            got = await self.one(
                "Email/get", {"ids": batch, "properties": properties}, jmap.Got[Email]
            )
            found.update((e.id, e) for e in got.items)
        return found

    async def email(self, message_id: str, properties: list[str]) -> Email:
        found = (await self.emails([message_id], properties)).get(message_id)
        if found is None:
            raise missing_message(message_id)
        return found

    async def mailboxes(self) -> list[Mailbox]:
        got = await self.one(
            "Mailbox/get",
            {"ids": None, "properties": mappers.MAILBOX_PROPERTIES},
            jmap.Got[Mailbox],
        )
        return got.items

    async def folders(self) -> list[Folder]:
        return [mappers.folder(m) for m in await self.mailboxes()]

    async def role_id(self, role: FolderRole) -> str | None:
        for folder in await self.folders():
            if folder.role is role:
                return folder.id
        return None

    async def source(self, email: Email, message_id: str) -> bytes:
        if email.blob_id is None:
            raise ProviderError("the JMAP server named no source of the message")
        try:
            return await self.client.download(email.blob_id, *SOURCE)
        except NotFoundError:
            raise missing_message(message_id) from None

    async def upload(self, raw: bytes) -> str:
        return await self.client.upload(raw, SOURCE[1])
