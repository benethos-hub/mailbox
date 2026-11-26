"""The packages of the domain and of the data layer (docs/REFACTORING.md
4, 8.4): each is imported through its ``__init__.py``, none imports
another in a circle, they keep their lines, and only the storage builds
a database. A package below a layer, such as ``storage/sql/``, is
imported through its ``__init__.py`` as well."""

from __future__ import annotations

import ast

import pytest

from .source_helpers import PACKAGE, ROOT, from_imports, imports, modules

# The layers in packages: each package is imported through its __init__.py.
PACKAGED = ("domain", "data")


def _package_part(module: str) -> tuple[str, str] | None:
    """'...domain.sync.worker' -> ('domain', 'sync'), '...data.files' ->
    ('data', 'files')."""
    parts = module.split(".")
    if parts[0] != PACKAGE or len(parts) < 3 or parts[1] not in PACKAGED:
        return None
    return parts[1], parts[2]


def _is_package(part: tuple[str, str]) -> bool:
    return (ROOT / part[0] / part[1] / "__init__.py").exists()


def _dotted(part: tuple[str, str]) -> str:
    return f"{PACKAGE}.{part[0]}.{part[1]}"


# Packages of steps of a schema, one module each, which the package
# above them collects in order: their modules are imported one by one.
STEPS = ("storage.sqlite.migrations.versions",)


def _inner_package(module: str) -> str | None:
    """The innermost package below a layer that holds ``module`` and is
    not ``module`` itself: '...data.storage.sql.database' ->
    '...data.storage.sql'."""
    parts = module.split(".")
    if parts[0] != PACKAGE or len(parts) < 4 or parts[1] not in PACKAGED:
        return None
    for end in range(len(parts) - 1, 2, -1):
        outer = ".".join(parts[:end])
        if (ROOT.parent.joinpath(*parts[:end]) / "__init__.py").exists():
            return outer
    return None


def test_a_nested_package_is_imported_through_its_init() -> None:
    """The same below a package of a layer, such as ``storage/sql/``: a
    module outside a package takes what it offers from its
    ``__init__.py``."""
    violations = []
    for name, path in modules():
        own = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        for imported, line in imports(path):
            outer = _inner_package(imported)
            if outer is None or outer.endswith(STEPS):
                continue
            if own == outer or own.startswith(outer + ".") or imported == outer:
                continue
            violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "a module inside a package:\n  " + "\n  ".join(violations)


def test_a_package_is_imported_through_its_init() -> None:
    """So a package can split or merge its modules without its callers
    noticing: the other packages, the layers above and the assembly."""
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in modules()
        for imported, line in imports(path)
        if (other := _package_part(imported)) is not None
        and other != _package_part(name)
        and _is_package(other)
        and imported != _dotted(other)
    ]
    assert not violations, "a module inside a package:\n  " + "\n  ".join(violations)


def _exported(part: tuple[str, str]) -> set[str]:
    init = ast.parse((ROOT / part[0] / part[1] / "__init__.py").read_text("utf-8"))
    for node in init.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            return set(ast.literal_eval(node.value))
    return set()


def test_a_package_exports_what_others_import() -> None:
    """What another part imports from a package is in its ``__all__``."""
    violations = [
        f"{name}:{node.lineno} imports {alias.name} from {imported}"
        for name, path in modules()
        for imported, node in from_imports(path)
        if (other := _package_part(imported)) is not None
        and imported == _dotted(other)
        and other != _package_part(name)
        and _is_package(other)
        for alias in node.names
        if alias.name not in _exported(other)
    ]
    assert not violations, "not exported:\n  " + "\n  ".join(violations)


def _package_graph(layer: str) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for name, path in modules():
        own = _package_part(name)
        if own is None or own[0] != layer:
            continue
        for imported, _ in imports(path):
            other = _package_part(imported)
            if other is not None and other[0] == layer and other != own:
                graph.setdefault(own[1], set()).add(other[1])
    return graph


@pytest.mark.parametrize("layer", PACKAGED)
def test_no_cycle_between_the_packages(layer: str) -> None:
    graph = _package_graph(layer)
    done: set[str] = set()

    def walk(part: str, path: list[str]) -> list[str] | None:
        if part in path:
            return [*path[path.index(part) :], part]
        if part in done:
            return None
        for other in sorted(graph.get(part, ())):
            if cycle := walk(other, [*path, part]):
                return cycle
        done.add(part)
        return None

    for part in sorted(graph):
        cycle = walk(part, [])
        assert cycle is None, "a cycle: " + " -> ".join(cycle)


# The packages of each layer in lines (docs/mailbox-service/ARCHITECTURE.md 2): each
# imports only the lines below its own.
LINES = {
    "domain": (
        {"system"},
        {"mailbox", "users", "webhooks"},
        {"sync"},
        {"accounts"},
        {"auth", "discovery", "changes", "rounds"},
        {"activity"},
        {"rights"},
        {"paging"},
    ),
    "data": (
        {"backup", "move"},
        {"export"},
        {"secrets"},
        {"storage", "providers", "discovery"},
        {"protocols"},
        {"mail", "files"},
        {"models", "logbook"},
    ),
}


@pytest.mark.parametrize("layer", PACKAGED)
def test_the_packages_import_only_lines_below(layer: str) -> None:
    line_of = {part: n for n, line in enumerate(LINES[layer]) for part in line}
    assert set(line_of) == {
        p.stem
        for p in (ROOT / layer).iterdir()
        if p.stem != "__init__" and (p.suffix == ".py" or (p / "__init__.py").exists())
    }, f"a package of {layer} outside the lines"
    violations = [
        f"{own} imports {other}"
        for own, others in sorted(_package_graph(layer).items())
        for other in sorted(others)
        if line_of[other] <= line_of[own]
    ]
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)


# What holds a change of ours to messages under writing of the sync, so
# that a pass it overtakes applies nothing (CONCEPT 4.1), and the one
# module of domain/mailbox that calls it.
OWN_WRITES = {"writing", "pausing", "relocate", "forget"}
WRITES_HOME = f"{PACKAGE}.domain.mailbox.calls"


def _of_the_sync(node: ast.Attribute) -> bool:
    """Whether the attribute is one of ``sync`` or ``self._sync``."""
    held = node.value
    if isinstance(held, ast.Attribute):
        return held.attr == "_sync"
    return isinstance(held, ast.Name) and held.id == "sync"


def test_our_changes_to_messages_are_made_in_calls() -> None:
    """SyncService.writing, pausing, relocate and forget are called in
    domain/mailbox/calls.py alone, which keeps every change of ours under
    writing in one module."""
    violations = [
        f"{name}:{node.lineno} {node.attr}"
        for name, path in modules()
        if name != WRITES_HOME
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and node.attr in OWN_WRITES
        and _of_the_sync(node)
    ]
    assert not violations, "a change of ours outside calls.py:\n  " + "\n  ".join(
        violations
    )


# What only the storage itself builds: a database and the places it lies in.
STORAGE_INSIDE = {"Database", "ServerPlace", "FilePlace"}


def test_only_the_storage_builds_a_database() -> None:
    """A backup, a restore and a move open their stores through
    ``data/storage/stores.py``. No module outside ``data/storage`` names
    the database or a place, so the storage alone picks where it lies."""
    storage = ROOT / "data" / "storage"
    violations = [
        f"{name}:{node.lineno} {found}"
        for name, path in modules()
        if not path.is_relative_to(storage)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (
            found := node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else node.name
            if isinstance(node, ast.alias)
            else None
        )
        in STORAGE_INSIDE
    ]
    assert not violations, "the storage built outside it:\n  " + "\n  ".join(violations)
