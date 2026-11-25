"""The settings of the live checks: from their file alone, on this machine."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from benethos_mailbox_agents.records import MessageRef
from benethos_mailbox_agents.sources.mailbox import connect

from .agents_fake import ACCOUNT, FakeService, wire_message
from .agents_helpers import ROOT, load_script

# live/ is no package and lies outside testpaths: the module is loaded by
# its path, as a script would find it beside itself.
COMMON = ROOT / "live" / "mailbox-agents" / "agents_common" / "__init__.py"


@pytest.fixture(scope="module")
def common() -> Iterator[ModuleType]:
    with load_script(COMMON, "live_common") as module:
        yield module


def test_loading_a_script_leaves_the_path_as_it_was() -> None:
    before = list(sys.path)

    with load_script(COMMON, "live_common_again") as module:
        assert str(ROOT / "containers" / "live" / "mailbox-agents") in sys.path
        assert module.mail.local("<x@y.example>") == "x"

    assert sys.path == before
    assert "live_common_again" not in sys.modules


def env_file(tmp_path: Path, url: str) -> Path:
    path = tmp_path / "agent.env"
    path.write_text(
        f"MAILBOX_AGENTS_SERVICE_URL={url}\nMAILBOX_AGENTS_ACCOUNTS=test-account\n",
        encoding="utf-8",
    )
    return path


def test_the_file_wins_over_the_environment(
    common: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_SERVICE_URL", "https://real.example")
    monkeypatch.setenv("MAILBOX_AGENTS_ACCOUNTS", "real-account")
    monkeypatch.setenv("MAILBOX_AGENTS_STAGE", "full")

    found = common.live_settings(env_file(tmp_path, "http://127.0.0.1:38081"), "x")

    assert found.service_url == "http://127.0.0.1:38081"
    assert found.accounts == ["test-account"]
    assert found.stage == "shadow"
    assert "live: account test-account at http://127.0.0.1:38081" in (
        capsys.readouterr().out
    )


def test_the_environment_is_left_as_it_was(
    common: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAILBOX_AGENTS_STAGE", "full")

    common.live_settings(env_file(tmp_path, "http://127.0.0.1:38081"), "x")

    assert os.environ["MAILBOX_AGENTS_STAGE"] == "full"


@pytest.mark.parametrize("url", ["http://localhost:38081", "http://[::1]:38081"])
def test_a_service_on_this_machine_is_taken(
    common: ModuleType, tmp_path: Path, url: str
) -> None:
    assert common.live_settings(env_file(tmp_path, url), "x").service_url == url


@pytest.mark.parametrize(
    "url",
    [
        "https://real.example",
        "https://real.example:38081",
        "http://127.0.0.1:8080",
        "http://127.0.0.1",
        "http://localhost:99999",
    ],
)
def test_a_service_elsewhere_stops_the_check(
    common: ModuleType, tmp_path: Path, url: str
) -> None:
    with pytest.raises(SystemExit) as raised:
        common.live_settings(env_file(tmp_path, url), "x")

    assert raised.value.code == 2


def test_the_live_port_is_the_one_of_the_compose_file(common: ModuleType) -> None:
    compose = (
        ROOT / "containers" / "live" / "mailbox-agents" / "compose.yaml"
    ).read_text("utf-8")
    setup = (ROOT / "containers" / "live" / "mailbox-agents" / "setup.sh").read_text(
        "utf-8"
    )

    assert f'"127.0.0.1:{common.LIVE_PORT}:8080"' in compose
    assert f"SERVICE_URL=http://127.0.0.1:{common.LIVE_PORT} " in setup


async def test_put_back_takes_off_each_keyword_and_moves_back_once(
    common: ModuleType,
) -> None:
    service = FakeService()
    service.add(wire_message("m1", folder_ids=["inbox"]), change=None)
    service.add(wire_message("m2", folder_ids=["inbox"]), change=None)
    service.messages[(ACCOUNT, "m2")]["keywords"] = ["mine"]
    async with connect(
        "https://mailbox.example.test", "t", transport=service.transport()
    ) as mailbox:
        refs = [MessageRef(account_id=ACCOUNT, message_id=m) for m in ("m1", "m2")]
        before = await common.snapshot(mailbox, refs)
        service.messages[(ACCOUNT, "m1")]["folder_ids"] = ["inv-hosting"]
        service.messages[(ACCOUNT, "m1")]["keywords"] = ["agent-categorized"]
        service.messages[(ACCOUNT, "m2")]["keywords"] = [
            "mine",
            "agent-categorized",
            "agent-invoice",
        ]

        moved = await common.put_back(
            mailbox, before, "agent-categorized", "agent-invoice"
        )

    assert moved == 1
    assert service.messages[(ACCOUNT, "m1")]["folder_ids"] == ["inbox"]
    assert service.messages[(ACCOUNT, "m1")]["keywords"] == []
    assert service.messages[(ACCOUNT, "m2")]["keywords"] == ["mine"]


class _CutOffError(Exception):
    """A put back that failed half way, as an upstream away would end it."""


@contextmanager
def _live_script(name: str) -> Iterator[ModuleType]:
    """The script ``live/mailbox-agents/<name>.py``, with its folder on the
    path while it is loaded, as it imports agents_common from beside it.
    Afterwards the path and the modules are as they were."""
    folder = ROOT / "live" / "mailbox-agents"
    modules = set(sys.modules)
    sys.path.insert(0, str(folder))
    try:
        with load_script(folder / f"{name}.py", f"live_{name}") as module:
            yield module
    finally:
        sys.path.remove(str(folder))
        for key in set(sys.modules) - modules:
            file = getattr(sys.modules[key], "__file__", None)
            if file and Path(file).is_relative_to(folder):
                del sys.modules[key]


@pytest.mark.parametrize(
    ("script", "step"),
    [("categorization", "put_back"), ("invoices", "put_back_between")],
)
async def test_a_put_back_cut_off_is_done_again_on_the_way_out(
    monkeypatch: pytest.MonkeyPatch, script: str, step: str
) -> None:
    async def cut_off(*args: object) -> object:
        raise _CutOffError

    async def done(*args: object) -> object:
        return 0 if step == "put_back" else "back"

    async def same(mailbox: object, before: object) -> object:
        return before

    with _live_script(script) as module:
        live = SimpleNamespace(
            mailbox=None,
            before={},
            keyword="agent-categorized",
            keywords=("agent-categorized",),
            put_back_done=False,
        )
        monkeypatch.setattr(module, step, cut_off)
        with pytest.raises(_CutOffError):
            await module.put_back_check(live)
        assert live.put_back_done is False

        monkeypatch.setattr(module, step, done)
        monkeypatch.setattr(module, "snapshot", same, raising=False)
        await module.put_back_check(live)
        assert live.put_back_done is True


# -- where gold.py writes ---------------------------------------------------------


@pytest.fixture(scope="module")
def gold() -> Iterator[ModuleType]:
    with _live_script("gold") as module:
        yield module


def test_the_gold_files_go_beside_the_settings_file(
    gold: ModuleType, tmp_path: Path
) -> None:
    env = tmp_path / "setup" / "secrets" / "agent.env"

    assert gold.target(env, None) == env.resolve().parent


def test_the_gold_files_go_to_the_secrets_of_the_live_setup_by_default(
    gold: ModuleType,
) -> None:
    secrets = ROOT / "containers" / "live" / "mailbox-agents" / "secrets"

    assert gold.target(gold.ENV, None) == secrets.resolve()


def test_out_names_another_folder_for_the_gold_files(
    gold: ModuleType, tmp_path: Path
) -> None:
    assert gold.target(tmp_path / "agent.env", tmp_path / "gold") == tmp_path / "gold"


def test_each_agent_gets_a_gold_file_of_its_lines(
    gold: ModuleType, tmp_path: Path
) -> None:
    folder = tmp_path / "made" / "here"

    written = gold.save({"categorization": ["{}", "[]"], "invoices": ["{}"]}, folder)

    assert [p.name for p in written] == [
        "gold-categorization.jsonl",
        "gold-invoices.jsonl",
    ]
    assert (folder / "gold-categorization.jsonl").read_text(
        encoding="utf-8"
    ) == "{}\n[]\n"
