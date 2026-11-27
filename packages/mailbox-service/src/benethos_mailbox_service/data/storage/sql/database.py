"""The database the repositories of the service use: the storage of
mailbox-common, handed the shape of the service at this one place.

``SHAPE`` says what the service's database is: its tables
(``schema``), its revisions from schema 26 on, the old steps of its
file before them (``sqlite/``), the errors it has the storage raise, and
the counter of the change feed, set on after a fill. ``Database`` and
``ServerPlace`` are those of the storage with it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from benethos_mailbox_common.storage import database, place, server_place, shape

from ....errors import STORAGE_ERRORS
from ..sqlite import OLD_STEPS
from .revisions import BASELINE, SCHEMA_VERSION, VERSIONS
from .schema import METADATA
from .tables import align_changes

# Where an operator reads how to set a schema that holds tables aside.
SET_ASIDE = (
    "https://github.com/benethos-hub/mailbox/blob/main/containers/production/"
    "mailbox-service/README.md#set-a-schema-aside"
)

SHAPE = shape.Shape(
    program="benethos-mailbox-service",
    noun="service",
    metadata=METADATA,
    versions=VERSIONS,
    newest=SCHEMA_VERSION,
    baseline=BASELINE,
    errors=STORAGE_ERRORS,
    extra=(
        "storage postgres needs the extra postgres of the service:"
        " pip install 'benethos-mailbox-service[postgres]'"
    ),
    set_aside=SET_ASIDE,
    file_steps=OLD_STEPS,
    filled=align_changes,
)


class Database(database.Database):
    """The database of the service at ``path``, a file readable by its
    owner alone, in memory without one, or the one at ``place``. As the
    storage's, with the shape of the service."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        keep_copy: bool = True,
        schema: int | None = None,
        place: place.Place | None = None,
    ) -> None:
        super().__init__(SHAPE, path, keep_copy=keep_copy, schema=schema, place=place)


class ServerPlace(server_place.ServerPlace):
    """The schema of the service on the server ``server`` names."""

    def __init__(
        self,
        server: server_place.Server,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(server, SHAPE, clock)
