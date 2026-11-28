"""The rules of the package that hold beside its layers, read from the
source: what a live script, an agent and a module beside the upstreams
may do. The layers themselves are tests/test_layers.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from . import layers_helpers
from .agents_helpers import ROOT
from .layers_helpers import PACKAGE, SOURCE, layer, layer_of, module_from, modules

LIVE = ROOT / "live" / "mailbox-agents"
LIVE_SCRIPTS = sorted(LIVE.rglob("*.py"))


def _imports_nothing_of_the_command_line(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            assert name != f"{PACKAGE}.cli", f"{path.name} imports {name}"
            assert not name.startswith(f"{PACKAGE}.cli."), f"{path.name} imports {name}"


def test_the_live_scripts_are_found() -> None:
    """The scripts of live/mailbox-agents are there to be held, so the test
    below never passes over an empty list."""
    assert len(LIVE_SCRIPTS) >= 5


@pytest.mark.parametrize(
    "path", LIVE_SCRIPTS, ids=lambda p: p.relative_to(LIVE).as_posix()
)
def test_a_live_script_imports_nothing_of_the_command_line(path: Path) -> None:
    """A live script works with the runtime, as the command line does, not
    through it."""
    _imports_nothing_of_the_command_line(path)


def test_an_import_of_the_command_line_is_caught(tmp_path: Path) -> None:
    script = tmp_path / "script.py"
    script.write_text(f"from {PACKAGE}.cli import main\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        _imports_nothing_of_the_command_line(script)


# Where an HTTP status may be read: the modules of the upstreams, and the
# error that carries it.
HTTP_HOMES = frozenset({"sources", "llm", "errors"})


@pytest.mark.parametrize(
    "path",
    [p for p in modules() if layer_of(p) not in HTTP_HOMES],
    ids=[
        p.relative_to(SOURCE).as_posix()
        for p in modules()
        if layer_of(p) not in HTTP_HOMES
    ],
)
def test_no_http_status_beyond_the_upstreams(path: Path) -> None:
    """A status code or a comparison with one stays where the upstream is
    spoken to, so a change of client touches nothing else."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    caught = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.name
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "status"
            and isinstance(node.value, ast.Name)
        ):
            assert node.value.id not in caught, f"{path.name} reads an error's .status"
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                code = side.value if isinstance(side, ast.Constant) else None
                assert not (isinstance(code, int) and 100 <= code <= 599), (
                    f"{path.name} compares with {code}"
                )


AGENT_MODULES = [p for p in modules() if layer_of(p) == "agents"]


@pytest.mark.parametrize(
    "path", AGENT_MODULES, ids=[p.relative_to(SOURCE).as_posix() for p in AGENT_MODULES]
)
def test_no_agent_compares_the_stage(path: Path) -> None:
    """What a stage carries out is the executor's table alone: an agent
    asks for its actions whatever the stage."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Compare):
            for side in (node.left, *node.comparators):
                assert not (isinstance(side, ast.Attribute) and side.attr == "stage"), (
                    f"{path.name} compares the stage on line {node.lineno}"
                )


def _names_from_settings(path: Path) -> set[str]:
    """The names ``path`` takes from the layer settings: what it imports
    from there, and ``settings`` itself when it imports the layer whole."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            module = module_from(path, node)
            if module == PACKAGE:
                found |= {a.name for a in node.names if a.name == "settings"}
            elif module.startswith(f"{PACKAGE}.") and layer(module) == "settings":
                found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {
                "settings"
                for alias in node.names
                if alias.name.startswith(f"{PACKAGE}.")
                and layer(alias.name) == "settings"
            }
    return found


@pytest.mark.parametrize(
    "path", AGENT_MODULES, ids=[p.relative_to(SOURCE).as_posix() for p in AGENT_MODULES]
)
def test_an_agent_takes_prefix_alone_from_the_settings(path: Path) -> None:
    """An agent is handed its settings and names a setting in what it says
    by ``PREFIX``. It reads nothing else of the layer settings, such as the
    loading of the settings or a secret."""
    assert _names_from_settings(path) <= {"PREFIX"}


def test_the_check_finds_more_than_prefix_taken_from_the_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "agents" / "probe").mkdir(parents=True)
    probe = tmp_path / "agents" / "probe" / "agent.py"
    probe.write_text(
        "from ...settings import PREFIX, load_settings\n"
        "import benethos_mailbox_agents.settings\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(layers_helpers, "SOURCE", tmp_path)

    assert _names_from_settings(probe) == {"PREFIX", "load_settings", "settings"}


@pytest.mark.parametrize(
    "path",
    [p for p in modules() if p != SOURCE / "records" / "mail.py"],
    ids=lambda p: p.relative_to(SOURCE).as_posix(),
)
def test_the_discard_roles_are_spelt_once(path: Path) -> None:
    """The trash, junk and spam, and the drafts and sent mail, are named as
    a set of roles in records/mail.py alone, so the executor and an agent
    cannot come to differ on them. In a set, a tuple or a list."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Set | ast.Tuple | ast.List):
            values = {e.value for e in node.elts if isinstance(e, ast.Constant)}
            assert not values & {"trash", "drafts"}, (
                f"{path.name} names the roles on line {node.lineno}"
            )
