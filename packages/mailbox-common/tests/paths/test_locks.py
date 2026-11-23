"""A lock file: one holder at a time."""

from __future__ import annotations

from pathlib import Path

import pytest

from benethos_mailbox_common.paths.locks import LockedError, exclusive_lock


def test_a_second_holder_is_refused_at_once(tmp_path: Path) -> None:
    path = tmp_path / "below" / "state.lock"
    with exclusive_lock(path):
        assert path.is_file()
        with pytest.raises(LockedError, match="locked by another process"):
            with exclusive_lock(path):
                pass
    with exclusive_lock(path):
        pass


def test_a_folder_that_cannot_be_made_is_an_os_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("", encoding="utf-8")
    with pytest.raises(OSError):
        with exclusive_lock(blocker / "state.lock"):
            pass
