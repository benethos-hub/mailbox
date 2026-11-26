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
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from benethos_mailbox_common.paths import locks

from ...common.clock import iso, utc_now
from ...errors import MailboxServiceError, StorageInUseError
from ..export import ExportError, read_export, write_export
from ..files import create_private, free_path
from ..storage import (
    SCHEMA_VERSION,
    SET_ASIDE,
    Database,
    Records,
    Server,
    ServerPlace,
    Store,
    inspect_bytes,
    inspect_file,
    migrate_file,
    move_sidecars,
    remove_database_file,
    service_lock,
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
    rows = write_export(records, summed)
    manifest = replace(manifest, sha256=summed.hexdigest(), rows=rows)

    def written(out: Sealing) -> None:
        write_export(records, out)

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
    try:
        create_private(target, header)
    except OSError as exc:
        raise BackupError(f"{target} cannot be written: {exc.strerror}") from None
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
    try:
        file = source.open("rb")
    except OSError as exc:
        raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
    # The plain export an earlier version wrote beside ``into``, left by
    # a crash.
    into.with_name(into.name + ".export").unlink(missing_ok=True)
    with file:
        header, manifest = read_header(file, source)
        if manifest.format == 3:
            _exported_schema(manifest)
        try:
            create_private(into)
        except OSError as exc:
            raise BackupError(f"{into} cannot be written: {exc.strerror}") from None
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
        db = Database(into, schema=manifest.schema_version)
    except MailboxServiceError as exc:
        raise BackupError(f"the backup cannot be read back: {exc}") from None
    try:
        plain = Decrypting(file, header, key, source)
        rows = _read_plain(io.BufferedReader(plain, BLOCK), db)
        plain.finish(manifest.sha256)
    finally:
        db.close()
    if rows != manifest.rows:
        raise BackupError("the backup does not match its manifest")


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
    try:
        file = source.open("rb")
    except OSError as exc:
        raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
    with file:
        header, manifest = read_header(file, source)
        key = backup_key(master_key)
        if manifest.format == 3:
            _exported_schema(manifest)
            plain = Decrypting(file, header, key, source)
            db = Database(schema=manifest.schema_version)
            try:
                rows = _read_plain(io.BufferedReader(plain, BLOCK), db)
                plain.finish(manifest.sha256)
            finally:
                db.close()
            if rows != manifest.rows:
                raise BackupError("the backup does not match its manifest")
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


def _read_plain(source: BinaryIO, store: Store) -> dict[str, int]:
    """The export in ``source`` into ``store``, its failures as a backup's."""
    try:
        return read_export(source, store)
    except (ExportError, MailboxServiceError) as exc:
        raise BackupError(f"the backup cannot be read back: {exc}") from None


def restore_on_server(source: Path, master_key: bytes, server: Server) -> Manifest:
    """Read a backup of format 3 into the schema of ``server``, which
    holds no table yet, then bring it to this version's schema. The lock
    of a running service is taken for it: a service on the schema refuses
    the restore. When it fails, the tables it made go, and only those."""
    try:
        file = source.open("rb")
    except OSError as exc:
        raise BackupError(f"{source} cannot be read: {exc.strerror}") from None
    with file:
        header, manifest = read_header(file, source)
        if manifest.format != 3:
            raise BackupError(
                f"a backup of format {manifest.format} holds the file of a SQLite"
                " database: restore it with MAILBOX_SERVICE_STORAGE=sqlite, then"
                " move it with `storage move --to postgres`"
            )
        _exported_schema(manifest)
        place = ServerPlace(server)
        # Connected alone, without a revision: the schema is looked at
        # before anything is made in it.
        try:
            place.open(manifest.schema_version, SCHEMA_VERSION)
            with _held(place):
                if place.tables():
                    raise BackupError(
                        f"the schema {server.schema_name} holds tables: a restore"
                        " goes into an empty schema only. How to set the old one"
                        f" aside: {SET_ASIDE}"
                    )
                _filled(place, file, header, manifest, source, master_key)
        finally:
            place.close()
    return manifest


@contextmanager
def _held(place: ServerPlace) -> Iterator[None]:
    """The lock of a running service, for the restore."""
    try:
        serving = place.claimed()
        serving.__enter__()
    except StorageInUseError:
        raise BackupError(
            "the service is running on this database: stop it first"
        ) from None
    try:
        yield
    finally:
        serving.__exit__(None, None, None)


def _filled(
    place: ServerPlace,
    file: BinaryIO,
    header: bytes,
    manifest: Manifest,
    source: Path,
    master_key: bytes,
) -> None:
    """The export of the backup into the empty schema of ``place``, at
    the schema of the manifest, then brought forward. Its tables dropped
    again on any failure. Until the records are checked the database
    keeps the mark a move sets, so a restore that dies half way leaves a
    database the service does not open."""
    try:
        made = Database(place=place, schema=manifest.schema_version)
        made.mark_move(iso(utc_now()))
        plain = Decrypting(file, header, backup_key(master_key), source)
        rows = _read_plain(io.BufferedReader(plain, BLOCK), made)
        plain.finish(manifest.sha256)
        if rows != manifest.rows:
            raise BackupError("the backup does not match its manifest")
        made.mark_move(None)
        Database(place=place)
    except BaseException as exc:
        try:
            place.drop_tables()
        except MailboxServiceError:
            if isinstance(exc, Exception):
                raise BackupError(
                    f"{exc}. Tables of the restore may be left: how to set the"
                    f" schema aside: {SET_ASIDE}"
                ) from None
        raise


def restore_backup(source: Path, master_key: bytes, target: Path) -> Manifest:
    """Replace the database at ``target`` with the backup. The previous file
    is kept beside it. The service must not be running."""
    staged = target.with_name(target.name + ".restoring")
    try:
        with locks.exclusive_lock(service_lock(target)):
            remove_database_file(staged)  # from a restore that crashed
            manifest = read_backup(source, master_key, staged)
            if manifest.schema_version > SCHEMA_VERSION:
                remove_database_file(staged)
                raise BackupError(
                    f"the backup has schema {manifest.schema_version}, this "
                    f"version supports up to {SCHEMA_VERSION}: update the "
                    "service first"
                )
            _replace(target, staged)
    except locks.LockedError:
        raise BackupError(
            "the service is running on this database: stop it first"
        ) from None
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
        kept = free_path(target.with_name(f"{target.name}.before-restore-{stamp}"))
        try:
            # A second name for the old file: the database stays in place
            # until the new one replaces it in one step.
            os.link(target, kept)
        except FileExistsError:
            raise  # taken since free_path looked: never replace a kept copy
        except OSError:
            target.replace(kept)  # a file system without hard links
        move_sidecars(target, kept)
    staged.replace(target)
