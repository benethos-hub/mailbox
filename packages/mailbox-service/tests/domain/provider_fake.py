"""An adapter that fails when a test tells it to."""

from __future__ import annotations

from benethos_mailbox_service.data.models import Folder
from benethos_mailbox_service.data.providers.memory import MemoryProvider


class FlakyProvider(MemoryProvider):
    """Fails the way the next test tells it to."""

    def __init__(self) -> None:
        super().__init__()
        self.fail: Exception | None = None

    async def list_folders(self) -> list[Folder]:
        if self.fail is not None:
            raise self.fail
        return await super().list_folders()
