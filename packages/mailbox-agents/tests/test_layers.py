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

from pathlib import Path

import pytest

from . import layers_helpers
from .layers_helpers import (
    PACKAGE,
    SOURCE,
    imports_of,
    layer,
    layer_of,
    modules,
    third_party,
)

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


@pytest.mark.parametrize(
    "path", modules(), ids=[p.relative_to(SOURCE).as_posix() for p in modules()]
)
def test_a_module_imports_only_the_layers_it_may(path: Path) -> None:
    own = layer_of(path)
    if own == "__init__":
        return  # the package root, which holds the version and nothing else
    allowed = MAY_IMPORT[own]
    wrong = [
        f"line {line}: {module}"
        for module, line in imports_of(path)
        if (target := layer(module)) not in ("", "__version__", own)
        and target not in allowed
    ]
    assert wrong == [], f"{own} may import {sorted(allowed)}"


@pytest.mark.parametrize(
    "path",
    [p for p in modules() if layer_of(p) == "agents"],
    ids=[
        p.relative_to(SOURCE).as_posix() for p in modules() if layer_of(p) == "agents"
    ],
)
def test_an_agent_imports_no_other_agent(path: Path) -> None:
    """Agents stand on their own: prompt, schema and rules are never shared."""
    parts = path.relative_to(SOURCE).parts
    own = f"{PACKAGE}.agents.{parts[1]}" if len(parts) > 2 else None
    for module, line in imports_of(path):
        if module.startswith(f"{PACKAGE}.agents."):
            assert own is not None and (
                module == own or module.startswith(f"{own}.")
            ), f"line {line}: {module}"


def test_every_layer_has_a_row() -> None:
    """A module or subpackage added without deciding where it sits fails here."""
    layers = {layer_of(path) for path in modules()} - {"__init__"}
    assert layers == set(MAY_IMPORT)


@pytest.mark.parametrize(("dependency", "homes"), CONFINED.items())
def test_a_confined_dependency_is_imported_in_its_homes_alone(
    dependency: str, homes: frozenset[str]
) -> None:
    importers = {
        path.relative_to(SOURCE).as_posix()
        for path in modules()
        if dependency in third_party(path)
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
    monkeypatch.setattr(layers_helpers, "SOURCE", tmp_path)

    found = [module for module, _ in imports_of(probe)]

    assert found == ["benethos_mailbox_agents.store"]
    assert layer(found[0]) not in MAY_IMPORT["records"]


def _module(path: Path) -> str:
    """The module of ``path``, a package by its ``__init__``."""
    parts = path.relative_to(SOURCE).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([PACKAGE, *parts])


def _graph() -> dict[str, set[str]]:
    """Which module of the package imports which, the modules as nodes."""
    nodes = {_module(path): path for path in modules()}
    graph: dict[str, set[str]] = {name: set() for name in nodes}
    for name, path in nodes.items():
        for target, _ in imports_of(path):
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
