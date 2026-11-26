"""The head of a backup: its magic line, which names the format, and its
manifest line, a JSON object of the fields of ``Manifest``. Both are
read before anything of the backup is authenticated, and both are part
of what each block is authenticated with."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO

from .blocks import MAGIC, MAGIC_1, MAGIC_3, BackupError

_MAGICS = {MAGIC_1: 1, MAGIC: 2, MAGIC_3: 3}
# The longest manifest line read: four short fields, and in format 3
# the rows of each table.
_MANIFEST_BYTES = 4096


@dataclass(frozen=True, slots=True)
class Manifest:
    service_version: str
    schema_version: int
    created_at: str
    sha256: str
    # Format 3: the rows of each table.
    rows: dict[str, int] | None = None
    # Not in the file: the format its magic names.
    format: int = field(default=2, compare=False)


def read_header(file: BinaryIO, source: Path) -> tuple[bytes, Manifest]:
    """The magic and the manifest line, and the manifest."""
    magic = file.readline(len(MAGIC))
    if magic not in _MAGICS:
        raise BackupError(f"{source} is not a backup of this service")
    line = file.readline(_MANIFEST_BYTES)
    if not line.endswith(b"\n"):
        raise BackupError(f"{source} is truncated")
    try:
        fields = json.loads(line)
        if not isinstance(fields, dict):
            raise TypeError
        # The magic names the format, whatever the manifest says.
        fields.pop("format", None)
        manifest = Manifest(**fields, format=_MAGICS[magic])
        if not _well_typed(manifest):
            raise TypeError
    except (ValueError, TypeError):
        raise BackupError(f"{source} has an unreadable manifest") from None
    return magic + line, manifest


def _well_typed(manifest: Manifest) -> bool:
    """Whether each field of the manifest is of its type: it is read
    before anything of the backup is authenticated."""

    def number(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    texts = (manifest.service_version, manifest.created_at, manifest.sha256)
    rows = manifest.rows
    return (
        all(isinstance(text, str) for text in texts)
        and number(manifest.schema_version)
        and (
            rows is None
            or isinstance(rows, dict)
            and all(isinstance(k, str) and number(v) for k, v in rows.items())
        )
    )


def head(manifest: Manifest) -> bytes:
    """The magic and the manifest line of ``manifest``'s format. Format 2
    holds the four fields it always held."""
    fields = asdict(manifest)
    del fields["format"]
    if manifest.format != 3:
        del fields["rows"]
    magic = {2: MAGIC, 3: MAGIC_3}[manifest.format]
    return magic + json.dumps(fields).encode() + b"\n"
