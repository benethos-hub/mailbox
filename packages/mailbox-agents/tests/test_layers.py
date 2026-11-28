"""Which part of the package may import which, read from the source.

The package is layered, see docs/mailbox-agents/ARCHITECTURE.md: the foundation, the
records, the contract and the state file, the two modules that talk to
the upstreams, the runtime, the agents, and the command line on top.
Every import statement counts, one inside a function or under
``TYPE_CHECKING`` included, since a deferred import is still a dependency.

A new top-level module or subpackage fails :func:`test_every_layer_has_a_row`
until it is given a row in :data:`MAY_IMPORT`. Within a layer any module may
import another, and no import may close a circle, which
:func:`test_no_import_closes_a_circle` holds.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import benethos_mailbox_agents

from .agents_helpers import ROOT

PACKAGE = "benethos_mailbox_agents"
SOURCE = Path(benethos_mailbox_agents.__file__).parent

# Which layers a layer may import, besides itself and the package root,
# which every module may read ``__version__`` from. Each row allows what the
# layer uses and no more. A change that needs another layer adds it here on
# purpose.
# What the runtime, the cockpit and the command line all stand on.
_BASE = frozenset({"errors", "logbook", "settings", "records", "contract", "store"})
MAY_IMPORT: dict[str, frozenset[str]] = {
    "errors": frozenset(),
    "logbook": frozenset(),
    "settings": frozenset({"errors"}),
    "records": frozenset(),
    "contract": frozenset({"errors", "records", "settings"}),
    "store": frozenset({"errors", "records"}),
    # The mailbox service, behind one module.
    "sources": frozenset({"errors", "records"}),
    # The model gateway, behind one module, and the evidence check.
    "llm": frozenset({"errors", "records"}),
    # The spans, behind one module.
    "telemetry": frozenset({"errors", "records", "settings"}),
    # The runtime holds every piece below it and hands an agent its context.
    "runtime": _BASE | {"llm", "telemetry"},
    # An agent sees the contract and the records, never the client, the
    # gateway, the state file or the runtime that holds them. settings for
    # PREFIX alone, which an agent's messages name settings by.
    "agents": frozenset({"errors", "records", "settings", "contract"}),
    # Scores an agent the way the runtime runs it, on a state file of its own.
    "evaluation": frozenset({"errors", "records", "contract", "store", "runtime"}),
    # The entrance over A2A: it is handed what classifies a message.
    "peers": frozenset({"errors", "records", "settings"}),
    # The pages of what every agent did, read through the store and runtime.
    "cockpit": _BASE | {"sources", "runtime"},
    # The top: it wires the upstreams, the state file and the runtime.
    "cli": _BASE
    | {"sources", "llm", "runtime", "evaluation", "telemetry", "peers", "cockpit"},
    "__main__": frozenset({"cli"}),
}

_STORE = "store/{}.py".format
# The parts of the state file that speak SQLAlchemy, and its baseline.
_PARTS = ("actions", "calls", "items", "messages", "profile", "reader", "rows", "steps")
_BASELINE = "revisions/versions/r0005_baseline"

# A dependency some modules may import and no other: the modules that are
# its interface to the rest of the package.
CONFINED: dict[str, frozenset[str]] = {
    # The output, the recorder, and the areas of the catalogue that set a
    # level of their own.
    "logging": frozenset(
        {
            "logbook/output.py",
            "logbook/activity.py",
            "logbook/catalogue/worker.py",
            "logbook/catalogue/feed.py",
            "logbook/catalogue/messages.py",
        }
    ),
    # The state file before its revisions and to read: an old step is
    # handed the connection to run its statements on.
    "sqlite3": frozenset(map(_STORE, ("file", "reader", "migrations/migration"))),
    # The parts of the state file, its tables, its baseline.
    "sqlalchemy": frozenset(map(_STORE, (*_PARTS, "schema", "store", _BASELINE))),
    "alembic": frozenset({_STORE(_BASELINE)}),
    "benethos_mailbox_client": frozenset({"sources/mailbox.py"}),
    # What the programs of Mailbox share: the lines of the log, the masking
    # of secrets, text, settings and the storage of the state.
    "benethos_mailbox_common": frozenset(
        {
            "errors/base.py",
            *("logbook/output.py", "logbook/activity.py"),
            *("logbook/catalogue/feed.py", "logbook/catalogue/worker.py"),
            "runtime/steps.py",
            *("settings/folders.py", "settings/model.py"),
            "sources/mailbox.py",
            *("errors/state_file.py", "settings/database.py", "cli/session.py"),
            *map(_STORE, ("catalogue", "file", "items", "messages", "profile")),
            *map(_STORE, ("reader", "rows", "schema", "shape", "store")),
            *map(_STORE, ("revisions/__init__", "revisions/revision")),
            "telemetry/otlp.py",
            "contract/actor.py",
            *("agents/categorization/lists.py", "agents/categorization/summary.py"),
            *("cli/__init__.py", "cli/commands.py", "cli/report.py", "cli/storage.py"),
            *("cockpit/app.py", "cockpit/security.py", "cockpit/views.py"),
        }
    ),
    "httpx": frozenset({"sources/mailbox.py", "llm/gateway.py"}),
    "prometheus_client": frozenset({"runtime/metrics.py"}),
    "opentelemetry": frozenset({"telemetry/otlp.py"}),
    "requests": frozenset({"telemetry/otlp.py"}),
    # The entrance over A2A and the server that opens its port, the one
    # socket besides the metrics, which prometheus_client opens.
    **dict.fromkeys(("a2a", "starlette"), frozenset({"peers/a2a.py"})),
    "uvicorn": frozenset({"peers/a2a.py", "cockpit/server.py"}),
    # The pages of the cockpit, on the framework of the mailbox service.
    "fastapi": frozenset({"cockpit/app.py", "cockpit/templates.py"}),
    "jinja2": frozenset({"cockpit/templates.py"}),
    # Its one home is the group settings of mailbox-common.
    "pydantic_settings": frozenset(),
    # The TLS context of the own CA: read in the settings, used by the two
    # modules that talk to an upstream.
    "ssl": frozenset({"settings/model.py", "sources/mailbox.py", "llm/gateway.py"}),
    # Nothing starts a process or opens a socket of its own, and no mail is
    # read or sent but through the mailbox service: no IMAP, no SMTP.
    "subprocess": frozenset(),
    "socket": frozenset(),
    "smtplib": frozenset(),
    "imaplib": frozenset(),
}

# contract/registry.py is the one module that reaches into the package by
# name, through importlib, to find the agents: no import statement shows it,
# so no row of MAY_IMPORT can.


def _layer(module: str) -> str:
    """``benethos_mailbox_agents.store.store`` is in the layer ``store``."""
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else ""


def _from(path: Path, node: ast.ImportFrom) -> str:
    """The module ``node`` in ``path`` imports from, a relative one resolved."""
    if not node.level:
        return node.module or ""
    relative = path.relative_to(SOURCE).with_suffix("").parts
    base = [PACKAGE, *relative][:-1]
    anchor = base[: len(base) - (node.level - 1)]
    return ".".join([*anchor, *([node.module] if node.module else [])])


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every module of this package that ``path`` imports, with its line."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            module = _from(path, node)
            if module != PACKAGE and not module.startswith(f"{PACKAGE}."):
                continue
            if module == PACKAGE:
                found += [
                    (f"{module}.{alias.name}", node.lineno) for alias in node.names
                ]
            else:
                found.append((module, node.lineno))
        elif isinstance(node, ast.Import):
            found += [
                (alias.name, node.lineno)
                for alias in node.names
                if alias.name.startswith(f"{PACKAGE}.")
            ]
    return found


def _modules() -> list[Path]:
    return sorted(SOURCE.rglob("*.py"))


def _layer_of(path: Path) -> str:
    return path.relative_to(SOURCE).parts[0].removesuffix(".py")


@pytest.mark.parametrize(
    "path", _modules(), ids=[p.relative_to(SOURCE).as_posix() for p in _modules()]
)
def test_a_module_imports_only_the_layers_it_may(path: Path) -> None:
    layer = _layer_of(path)
    if layer == "__init__":
        return  # the package root, which holds the version and nothing else
    allowed = MAY_IMPORT[layer]
    wrong = [
        f"line {line}: {module}"
        for module, line in _imports(path)
        if (target := _layer(module)) not in ("", "__version__", layer)
        and target not in allowed
    ]
    assert wrong == [], f"{layer} may import {sorted(allowed)}"


@pytest.mark.parametrize(
    "path",
    [p for p in _modules() if _layer_of(p) == "agents"],
    ids=[
        p.relative_to(SOURCE).as_posix() for p in _modules() if _layer_of(p) == "agents"
    ],
)
def test_an_agent_imports_no_other_agent(path: Path) -> None:
    """Agents stand on their own: prompt, schema and rules are never shared."""
    parts = path.relative_to(SOURCE).parts
    own = f"{PACKAGE}.agents.{parts[1]}" if len(parts) > 2 else None
    for module, line in _imports(path):
        if module.startswith(f"{PACKAGE}.agents."):
            assert own is not None and (
                module == own or module.startswith(f"{own}.")
            ), f"line {line}: {module}"


def test_every_layer_has_a_row() -> None:
    """A module or subpackage added without deciding where it sits fails here."""
    layers = {_layer_of(path) for path in _modules()} - {"__init__"}
    assert layers == set(MAY_IMPORT)


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
    [p for p in _modules() if _layer_of(p) not in HTTP_HOMES],
    ids=[
        p.relative_to(SOURCE).as_posix()
        for p in _modules()
        if _layer_of(p) not in HTTP_HOMES
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


AGENT_MODULES = [p for p in _modules() if _layer_of(p) == "agents"]


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
            module = _from(path, node)
            if module == PACKAGE:
                found |= {a.name for a in node.names if a.name == "settings"}
            elif module.startswith(f"{PACKAGE}.") and _layer(module) == "settings":
                found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            found |= {
                "settings"
                for alias in node.names
                if alias.name.startswith(f"{PACKAGE}.")
                and _layer(alias.name) == "settings"
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
    monkeypatch.setitem(globals(), "SOURCE", tmp_path)

    assert _names_from_settings(probe) == {"PREFIX", "load_settings", "settings"}


@pytest.mark.parametrize(
    "path",
    [p for p in _modules() if p != SOURCE / "records" / "mail.py"],
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


def _third_party(path: Path) -> set[str]:
    """The top-level names of what ``path`` imports from outside the package."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and not node.level and node.module:
            found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
    return found


@pytest.mark.parametrize(("dependency", "homes"), CONFINED.items())
def test_a_confined_dependency_is_imported_in_its_homes_alone(
    dependency: str, homes: frozenset[str]
) -> None:
    importers = {
        path.relative_to(SOURCE).as_posix()
        for path in _modules()
        if dependency in _third_party(path)
    }
    assert importers == homes


def test_the_check_finds_a_relative_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check itself, on a package of its own: a record that imports the
    state file is found, and the table forbids it."""
    (tmp_path / "records").mkdir()
    probe = tmp_path / "records" / "probe.py"
    probe.write_text("from ..store import Store\n", encoding="utf-8")
    monkeypatch.setitem(globals(), "SOURCE", tmp_path)

    found = [module for module, _ in _imports(probe)]

    assert found == ["benethos_mailbox_agents.store"]
    assert _layer(found[0]) not in MAY_IMPORT["records"]


def _module(path: Path) -> str:
    """The module of ``path``, a package by its ``__init__``."""
    parts = path.relative_to(SOURCE).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([PACKAGE, *parts])


def _graph() -> dict[str, set[str]]:
    """Which module of the package imports which, the modules as nodes."""
    nodes = {_module(path): path for path in _modules()}
    graph: dict[str, set[str]] = {name: set() for name in nodes}
    for name, path in nodes.items():
        for target, _ in _imports(path):
            while target and target not in nodes:
                target = target.rpartition(".")[0]
            if target and target != name:
                graph[name].add(target)
    return graph


def _down_to(node: str, stack: list[str], on_stack: set[str]) -> list[str]:
    """Take the nodes off ``stack`` down to ``node``: one strongly
    connected part."""
    part = []
    while True:
        taken = stack.pop()
        on_stack.discard(taken)
        part.append(taken)
        if taken == node:
            return part


def _circles(graph: dict[str, set[str]]) -> list[list[str]]:
    """The strongly connected parts of ``graph`` of more than one node,
    by Tarjan's algorithm."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            part = _down_to(node, stack, on_stack)
            if len(part) > 1:
                found.append(sorted(part))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return found


def test_no_import_closes_a_circle() -> None:
    graph = _graph()

    assert len(graph) > 50
    assert _circles(graph) == []


def test_a_circle_is_found() -> None:
    assert _circles({"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}}) == [
        ["a", "b", "c"]
    ]
