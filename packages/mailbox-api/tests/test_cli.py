from __future__ import annotations

import pytest

from benethos_mailbox_api import __version__
from benethos_mailbox_api.__main__ import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_serve_starts_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(kw))
    assert main(["serve", "--port", "9999"]) == 0
    assert calls["port"] == 9999
    assert calls["host"] == "127.0.0.1"
