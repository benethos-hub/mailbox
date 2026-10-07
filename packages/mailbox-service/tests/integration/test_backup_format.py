"""The backup file: broken and altered files, the schema, version 2 in
blocks, version 1 read."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from benethos_mailbox_service.data import backup
from benethos_mailbox_service.data.backup import (
    MAGIC,
    MAGIC_1,
    BackupError,
    Manifest,
    read_backup,
    restore_backup,
    write_backup,
)
from benethos_mailbox_service.data.secrets import (
    cipher,
)
from benethos_mailbox_service.data.storage import (
    Database,
    inspect_file,
)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"hello", "not a backup"),
        (MAGIC + b"no newline", "truncated"),
        (MAGIC + b"{not json}\n", "unreadable manifest"),
    ],
)
def test_broken_files(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "broken.bak"
    path.write_bytes(content)
    with pytest.raises(BackupError, match=message):
        read_backup(path, cipher.new_key(), tmp_path / "out.db")


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "x.db"
    Database(path).close()
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_checksum_and_schema_mismatch(tmp_path: Path) -> None:
    db = _database(tmp_path)
    master = cipher.new_key()
    bad_sum = Manifest("1", inspect_file(db), "now", "0" * 64)
    write_backup(db, bad_sum, master, tmp_path / "sum.bak")
    with pytest.raises(BackupError, match="checksum"):
        read_backup(tmp_path / "sum.bak", master, tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()

    wrong_schema = Manifest("1", 42, "now", _digest(db))
    write_backup(db, wrong_schema, master, tmp_path / "schema.bak")
    with pytest.raises(BackupError, match="does not match its manifest"):
        read_backup(tmp_path / "schema.bak", master, tmp_path / "out.db")

    not_a_db = tmp_path / "garbage"
    not_a_db.write_bytes(b"garbage" * 100)
    write_backup(
        not_a_db,
        Manifest("1", 1, "now", _digest(not_a_db)),
        master,
        tmp_path / "garbage.bak",
    )
    with pytest.raises(BackupError):
        read_backup(tmp_path / "garbage.bak", master, tmp_path / "out.db")


def test_a_newer_schema_is_not_restored(tmp_path: Path) -> None:
    path = _database(tmp_path)
    raw = sqlite3.connect(path)
    with raw:
        raw.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    raw.close()
    master = cipher.new_key()
    write_backup(
        path, Manifest("1", 999, "now", _digest(path)), master, tmp_path / "future.bak"
    )
    with pytest.raises(BackupError, match="update the service"):
        restore_backup(tmp_path / "future.bak", master, tmp_path / "target.db")
    assert not (tmp_path / "target.db.restoring").exists()


def test_inspect_rejects_non_databases(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_bytes(b"not a database at all" * 50)
    with pytest.raises(ValueError):
        inspect_file(path)


# --- version 2 in blocks, version 1 read --------------------------------------


@pytest.fixture
def small_blocks(monkeypatch: pytest.MonkeyPatch) -> int:
    """Blocks of 1 KiB, so a small database fills many."""
    monkeypatch.setattr(backup, "BLOCK", 1024)
    return 1024


def _blocks_of(tmp_path: Path) -> tuple[Path, bytes, bytes, list[bytes]]:
    """A database backed up in small blocks: the backup, the master key,
    its header and each block as written."""
    db = _database(tmp_path)
    master = cipher.new_key()
    target = tmp_path / "blocks.bak"
    write_backup(
        db, Manifest("1", inspect_file(db), "now", _digest(db)), master, target
    )
    raw = target.read_bytes()
    end = raw.index(b"\n", len(MAGIC)) + 1
    header, rest = raw[:end], raw[end:]
    records = []
    while rest:
        size = int.from_bytes(rest[13:17], "big")
        records.append(rest[: 17 + size])
        rest = rest[17 + size :]
    return target, master, header, records


def test_a_backup_is_written_and_read_in_blocks(
    tmp_path: Path, small_blocks: int
) -> None:
    target, master, _, records = _blocks_of(tmp_path)
    db = tmp_path / "x.db"
    assert len(records) == -(-db.stat().st_size // small_blocks)
    assert [r[12] for r in records] == [0] * (len(records) - 1) + [1]
    read_backup(target, master, tmp_path / "out.db")
    assert (tmp_path / "out.db").read_bytes() == db.read_bytes()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r[:-1], "truncated"),
        (lambda r: [r[1], r[0], *r[2:]], "does not decrypt"),
        (lambda r: [*r, r[-1]], "more than its backup"),
        (lambda r: [*r[:-2], r[-2][:12] + b"\x01" + r[-2][13:]], "does not decrypt"),
        (lambda r: [r[0][:-1] + bytes([r[0][-1] ^ 1]), *r[1:]], "does not decrypt"),
    ],
    ids=["last dropped", "swapped", "appended", "marked last early", "bit flipped"],
)
def test_a_block_altered_is_found(
    tmp_path: Path, small_blocks: int, change: object, message: str
) -> None:
    target, master, header, records = _blocks_of(tmp_path)
    target.write_bytes(header + b"".join(change(records)))  # type: ignore[operator]
    with pytest.raises(BackupError, match=message):
        read_backup(target, master, tmp_path / "out.db")
    assert not (tmp_path / "out.db").exists()


def test_a_backup_of_version_1_is_still_read(tmp_path: Path) -> None:
    db = _database(tmp_path)
    master = cipher.new_key()
    manifest = Manifest("0.2.0", inspect_file(db), "now", _digest(db))
    header = MAGIC_1 + json.dumps(asdict(manifest)).encode() + b"\n"
    key = cipher.derive(master, b"mailbox-service backup v1")
    nonce, sealed = cipher.encrypt(key, db.read_bytes(), header)
    (tmp_path / "old.bak").write_bytes(header + nonce + sealed)
    assert read_backup(tmp_path / "old.bak", master, tmp_path / "out.db") == manifest
    assert (tmp_path / "out.db").read_bytes() == db.read_bytes()
