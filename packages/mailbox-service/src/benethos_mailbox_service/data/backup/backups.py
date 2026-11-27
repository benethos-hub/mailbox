"""Encrypted backups of the whole database (CONCEPT 7.8): written,
read, checked and restored. The file of blocks is ``blocks``.

Version 2 holds the file of the database in blocks. A backup is written
from a copy of the database on disk and read back into a file.

Version 3 holds the logical export of the records (``export``) in the
same blocks, and its manifest the rows of each table. It does not depend
on the file of the database: it is read into a new database of its
schema. It is what ``backup`` writes on a database server, and on
SQLite when told to.

Version 1 holds the database as one ciphertext, authenticated with the
magic and the manifest. Versions 1, 2 and 3 are read. The master key
itself is never in a backup.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from benethos_mailbox_common.storage import export, files

from ...common.clock import iso, utc_now
from ...errors import MailboxServiceError, SchemaNotEmptyError, StorageInUseError
from ..storage import (
    SCHEMA_VERSION,
    Claim,
    Records,
    Server,
    Store,
    claimed,
    file_claimed,
    file_store,
    inspect_bytes,
    inspect_file,
    migrate_file,
    move_sidecars,
    remove_database_file,
)
from .blocks import (
    BLOCK,
    BackupError,
    Decrypting,
    Sealing,
    backup_key,
    decrypt,
    sha256_of,
)
from .manifest import Manifest, head, read_header

# A running service holds the lock of the database.
RUNNING = "the service is running on this database: stop it first"
# The first schema format 3 is written of: its export needs schema 26.
_FIRST_EXPORTED = 26


def create_backup(
    store: Store,
    master_key: bytes,
    target: Path,
    service_version: str,
    *,
    format: int = 2,
) -> Manifest:
    """A backup of ``store`` at ``target``, in format 2, the file of the
    database taken from a snapshot, or 3, its export, read from a view of
    one moment."""
    if target.exists():
        raise BackupError(f"{target} exists, refusing to overwrite it")
    if format == 3:
        with store.view() as records:
            manifest = _manifest(service_version, records.schema_version(), format)
            return _write_export(records, manifest, master_key, target)
    with store.snapshot_file() as snapshot:
        try:
            schema_version = inspect_file(snapshot)
        except ValueError as exc:
            raise BackupError(f"the database cannot be backed up: {exc}") from None
        manifest = _manifest(service_version, schema_version, format)
        manifest = replace(manifest, sha256=sha256_of(snapshot))
        write_backup(snapshot, manifest, master_key, target)
    return manifest


def _manifest(service_version: str, schema_version: int, format: int) -> Manifest:
    return Manifest(
        service_version=service_version,
        schema_version=schema_version,
        created_at=iso(utc_now()),
        sha256="",
        format=format,
    )


def _write_export(
    records: Records, manifest: Manifest, master_key: bytes, target: Path
) -> Manifest:
    """The export of ``records`` as a backup of format 3, with nothing of
    it in plain on a disk. A first pass sums and counts the export for the
    manifest, a second one over the same records encrypts it into
    ``target``. A second sum that differs removes the backup."""
    summed = _Summed()
    rows = export.export_records(records, summed)
    manifest = replace(manifest, sha256=summed.hexdigest(), rows=rows)

    def written(out: Sealing) -> None:
        export.export_records(records, out)

    if _sealed(manifest, master_key, target, written) != manifest.sha256:
        target.unlink(missing_ok=True)
        raise BackupError("the records changed while the backup was written")
    return manifest


class _Summed:
    """A sink that keeps only the SHA-256 of what is written to it."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()

    def write(self, data: bytes, /) -> int:
        self._digest.update(data)
        return len(data)

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def write_backup(
    source: Path, manifest: Manifest, master_key: bytes, target: Path
) -> None:
    """The file at ``source`` as a backup at ``target``, block by block:
    the database in format 2, its export in format 3, as the manifest
    says. A backup that cannot be finished is removed."""

    def written(out: Sealing) -> None:
        with source.open("rb") as plain:
            shutil.copyfileobj(plain, out)

    _sealed(manifest, master_key, target, written)


def _sealed(
    manifest: Manifest,
    master_key: bytes,
    target: Path,
    written: Callable[[Sealing], None],
) -> str:
    """A backup at ``target`` of what ``written`` writes, encrypted block
    by block. Returns the SHA-256 of the plain bytes. A backup that cannot
    be finished is removed."""
    header = head(manifest)
    _private(target, header)
    try:
        with target.open("ab") as out:
            sealing = Sealing(out, header, backup_key(master_key))
            written(sealing)
            sealing.close()
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise BackupError(f"{target} cannot be written: {exc.strerror}") from None
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return sealing.hexdigest()


def read_backup(source: Path, master_key: bytes, into: Path) -> Manifest:
    """Decrypt and check a backup into a new database file at ``into``,
    readable by its owner alone. Raises ``BackupError`` on any doubt, and
    leaves no file at ``into`` then."""
    # The plain export an earlier version wrote beside ``into``, left by
    # a crash.
    into.with_name(into.name + ".export").unlink(missing_ok=True)
    with _opened(source) as (file, header, manifest):
        if manifest.format == 3:
            _exported_schema(manifest)
        _private(into)
        try:
            key = backup_key(master_key)
            if manifest.format == 3:
                _read_export(file, header, key, source, manifest, into)
            else:
                with into.open("ab") as out:
                    digest = decrypt(file, header, key, out, source)
                if digest != manifest.sha256:
                    raise BackupError("the backup does not match its checksum")
            _check_schema(into, manifest)
        except OSError as exc:
            remove_database_file(into)
            raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
        except BaseException:
            remove_database_file(into)
            raise
    return manifest


def _exported_schema(manifest: Manifest) -> None:
    """A schema an export of format 3 can have, and this version read."""
    schema = manifest.schema_version
    if schema < _FIRST_EXPORTED or not isinstance(manifest.rows, dict):
        raise BackupError("the backup does not match its manifest")
    _not_newer(schema)


def _not_newer(schema: int) -> None:
    """Refuse a backup of a schema newer than this version's."""
    if schema > SCHEMA_VERSION:
        raise BackupError(
            f"the backup has schema {schema}, this version supports up to "
            f"{SCHEMA_VERSION}: update the service first"
        )


def _read_export(
    file: BinaryIO,
    header: bytes,
    key: bytes,
    source: Path,
    manifest: Manifest,
    into: Path,
) -> None:
    """The export the backup holds into the new database file at
    ``into``, of the schema of the manifest, decrypted block by block and
    never written in plain. Its checksum and rows held to the manifest."""
    try:
        db = file_store(into, schema=manifest.schema_version)
    except MailboxServiceError as exc:
        raise BackupError(f"the backup cannot be read back: {exc}") from None
    try:
        _records_into(file, header, key, source, manifest, db)
    finally:
        db.close()


def _check_schema(path: Path, manifest: Manifest) -> None:
    try:
        schema = inspect_file(path)
    except ValueError as exc:
        raise BackupError(str(exc)) from None
    if schema != manifest.schema_version:
        raise BackupError("the backup does not match its manifest")


def verify_backup(source: Path, master_key: bytes, scratch: Path) -> Manifest:
    """``read_backup`` into ``scratch``, which is removed afterwards."""
    try:
        return read_backup(source, master_key, scratch)
    finally:
        scratch.unlink(missing_ok=True)


def verify_in_memory(source: Path, master_key: bytes) -> Manifest:
    """Check a backup with nothing of it decrypted on a disk, for a
    service whose database is no file beside which a check could write.
    Format 3 is read block by block into a database in memory of the
    schema of the manifest, format 1 and 2, the file of a database, into
    memory whole. Raises ``BackupError`` on any doubt."""
    with _opened(source) as (file, header, manifest):
        key = backup_key(master_key)
        if manifest.format == 3:
            _exported_schema(manifest)
            db = file_store(schema=manifest.schema_version)
            try:
                _records_into(file, header, key, source, manifest, db)
            finally:
                db.close()
            return manifest
        held = io.BytesIO()
        if decrypt(file, header, key, held, source) != manifest.sha256:
            raise BackupError("the backup does not match its checksum")
    try:
        schema = inspect_bytes(held.getvalue())
    except ValueError as exc:
        raise BackupError(str(exc)) from None
    if schema != manifest.schema_version:
        raise BackupError("the backup does not match its manifest")
    return manifest


def _records_into(
    file: BinaryIO,
    header: bytes,
    key: bytes,
    source: Path,
    manifest: Manifest,
    store: Store,
) -> None:
    """The export a backup of format 3 holds, decrypted block by block
    into ``store``, its checksum and rows held to the manifest. Its
    failures as a backup's."""
    plain = Decrypting(file, header, key, source)
    try:
        rows = export.import_records(io.BufferedReader(plain, BLOCK), store, "service")
    except (export.ExportError, MailboxServiceError) as exc:
        raise BackupError(f"the backup cannot be read back: {exc}") from None
    plain.finish(manifest.sha256)
    if rows != manifest.rows:
        raise BackupError("the backup does not match its manifest")


@contextmanager
def _opened(source: Path) -> Iterator[tuple[BinaryIO, bytes, Manifest]]:
    """The backup at ``source`` opened, with its head and manifest read."""
    try:
        file = source.open("rb")
    except OSError as exc:
        raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
    with file:
        header, manifest = read_header(file, source)
        yield file, header, manifest


def _private(path: Path, data: bytes = b"") -> None:
    """A new file at ``path`` for its owner alone, holding ``data``."""
    try:
        files.create_private(path, data)
    except OSError as exc:
        raise BackupError(f"{path} cannot be written: {exc.strerror}") from None


def restore_on_server(source: Path, master_key: bytes, server: Server) -> Manifest:
    """Read a backup of format 3 into the schema of ``server``, which
    holds no table yet, then bring it to this version's schema. The lock
    of a running service is taken for it: a service on the schema refuses
    the restore. When it fails, the tables it made go, and only those."""
    with _opened(source) as (file, header, manifest):
        if manifest.format != 3:
            raise BackupError(
                f"a backup of format {manifest.format} holds the file of a SQLite"
                " database: restore it with MAILBOX_SERVICE_STORAGE=sqlite, then"
                " move it with `storage move --to postgres`"
            )
        _exported_schema(manifest)
        # Connected alone, without a revision: the schema is looked at
        # before anything is made in it.
        with ExitStack() as held:
            try:
                claim = held.enter_context(
                    claimed(server, schema=manifest.schema_version, empty="a restore")
                )
            except StorageInUseError:
                raise BackupError(RUNNING) from None
            except SchemaNotEmptyError as exc:
                raise BackupError(str(exc)) from None
            _filled(claim, file, header, manifest, source, backup_key(master_key))
    return manifest


def _filled(
    claim: Claim,
    file: BinaryIO,
    header: bytes,
    manifest: Manifest,
    source: Path,
    key: bytes,
) -> None:
    """The export of the backup into the empty schema of ``claim``, at
    the schema of the manifest, then brought forward. Its tables dropped
    again on any failure. Until the records are checked the database
    keeps the mark a move sets, so a restore that dies half way leaves a
    database the service does not open."""
    try:
        made = claim.store(schema=manifest.schema_version)
        made.mark_move(iso(utc_now()))
        _records_into(file, header, key, source, manifest, made)
        made.mark_move(None)
        claim.store()
    except BaseException as exc:
        try:
            claim.drop_tables()
        except MailboxServiceError as left:
            if isinstance(exc, Exception):
                raise BackupError(f"{exc}. {left}") from None
        raise


def restore_backup(source: Path, master_key: bytes, target: Path) -> Manifest:
    """Replace the database at ``target`` with the backup. The previous file
    is kept beside it. The service must not be running."""
    staged = target.with_name(target.name + ".restoring")
    try:
        with file_claimed(target):
            remove_database_file(staged)  # from a restore that crashed
            manifest = read_backup(source, master_key, staged)
            try:
                _not_newer(manifest.schema_version)
            except BackupError:
                remove_database_file(staged)
                raise
            _replace(target, staged)
    except StorageInUseError:
        raise BackupError(RUNNING) from None
    return manifest


def _replace(target: Path, staged: Path) -> None:
    """Put the database at ``staged`` in place of the one at ``target``.
    It is migrated beside it first, so a crash on the way leaves the old
    database or the new one, never none."""
    try:
        migrate_file(staged)
    except BaseException:
        remove_database_file(staged)
        raise
    if target.exists():
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        kept = files.free_path(
            target.with_name(f"{target.name}.before-restore-{stamp}")
        )
        try:
            # A second name for the old file: the database stays in place
            # until the new one replaces it in one step.
            os.link(target, kept)
        except FileExistsError:
            raise  # taken since files.free_path looked: never replace a kept copy
        except OSError:
            target.replace(kept)  # a file system without hard links
        move_sidecars(target, kept)
    staged.replace(target)
