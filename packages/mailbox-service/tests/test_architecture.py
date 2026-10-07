"""The layering, checked instead of only written down.

web -> domain -> data, never the other way. A single reverse import is enough
to undo the split, and it happens by accident: a data module needs one domain
rule, imports it, and the data layer can no longer be used without the domain.
This test reads every import of the package and fails on the first one that
breaks a rule. Inside the domain and the data layer it checks the packages
the same way: each is imported through its ``__init__.py``, and none
imports another in a circle. The packages of both keep their lines.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = "benethos_mailbox_service"
ROOT = Path(__file__).resolve().parents[1] / "src" / PACKAGE

# Lower number = lower layer. A module may import its own layer and everything
# below it, never above.
LAYERS = {"data": 0, "domain": 1, "web": 2}

# Outside the layers. Read from every layer, so they import none of them.
# A module (config.py) or a package (common/).
CROSS_CUTTING = {"config", "errors", "common"}

# Shared helpers: the standard library and each other, nothing else.
HELPERS = "common"

# Assemble the app from the layers and may therefore reach anywhere.
ASSEMBLY = {"assembly", "cli", "__main__", "logs"}

# Web frameworks live in the web layer. assembly/ builds the app, so it may too.
WEB_LIBRARIES = {"fastapi", "starlette"}

# One library, one home (docs/ARCHITECTURE.md): the only module, or
# package, allowed to import each.
LIBRARY_HOMES = {
    "cryptography": f"{PACKAGE}.data.secrets.cipher",
    "keyring": f"{PACKAGE}.data.secrets.keys",
    "sqlite3": f"{PACKAGE}.data.storage.sqlite",
    "imapclient": f"{PACKAGE}.data.protocols.imap",
    "imap_tools": f"{PACKAGE}.data.mail.parse",
    "smtplib": f"{PACKAGE}.data.protocols.smtp",
    "poplib": f"{PACKAGE}.data.protocols.pop3",
    "httpx": f"{PACKAGE}.data.protocols.http",
    "dns": f"{PACKAGE}.data.discovery.dns",
    "defusedxml": f"{PACKAGE}.data.discovery.autoconfig",
    "publicsuffixlist": f"{PACKAGE}.data.discovery.suffix",
    "jinja2": f"{PACKAGE}.web.pages.templates",
    "platformdirs": f"{PACKAGE}.config",
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _from_imports(path: Path) -> list[tuple[str, ast.ImportFrom]]:
    """Every ``from ... import`` of this file, its module resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            found.append((name, node))
    return found


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every imported module of this file, relative imports resolved."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno) for alias in node.names]
    for name, node in _from_imports(path):
        found.append((name, node.lineno))
        # `from . import x` imports a submodule by name, resolve it too.
        if not node.module:
            found += [(f"{name}.{alias.name}", node.lineno) for alias in node.names]
    return found


def _own_part(module: str) -> str | None:
    """'benethos_mailbox_service.domain.accounts' -> 'domain'."""
    parts = module.split(".")
    if parts[0] != PACKAGE or len(parts) < 2:
        return None
    return parts[1]


def _modules() -> list[tuple[str, Path]]:
    return [(_module_name(p), p) for p in sorted(ROOT.rglob("*.py"))]


def test_no_module_imports_a_higher_layer() -> None:
    violations = []
    for name, path in _modules():
        own = LAYERS.get(_own_part(name) or "")
        if own is None:
            continue
        for imported, line in _imports(path):
            other = LAYERS.get(_own_part(imported) or "")
            if other is not None and other > own:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "import against the layering:\n  " + "\n  ".join(violations)


def _cross_cutting_files(part: str) -> list[Path]:
    module, package = ROOT / f"{part}.py", ROOT / part
    if package.is_dir():
        return sorted(package.rglob("*.py"))
    assert module.exists(), f"{part}.py is missing"
    return [module]


def test_cross_cutting_modules_import_no_layer() -> None:
    for part in CROSS_CUTTING:
        for path in _cross_cutting_files(part):
            inside = [
                imported
                for imported, _ in _imports(path)
                if _own_part(imported) in LAYERS or _own_part(imported) in ASSEMBLY
            ]
            assert not inside, f"{path.name} imports from the layers: {inside}"


def test_shared_helpers_use_the_standard_library_only() -> None:
    """common/ holds what several layers share, so it depends on nothing."""
    violations = []
    for path in _cross_cutting_files(HELPERS):
        for imported, line in _imports(path):
            top = imported.split(".")[0]
            own = imported.startswith(f"{PACKAGE}.{HELPERS}")
            if not own and top not in sys.stdlib_module_names:
                violations.append(f"{path.name}:{line} imports {imported}")
    assert not violations, "common/ beyond the stdlib:\n  " + "\n  ".join(violations)


def test_the_domain_picks_no_storage() -> None:
    """Which store is used is decided where the app is assembled. A domain
    service that makes its own would keep data where nobody looks."""
    violations = []
    for name, path in _modules():
        if _own_part(name) != "domain":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.startswith(("InMemory", "Sqlite")):
                        violations.append(f"{name}:{node.lineno} {alias.name}")
    assert not violations, "storage chosen in the domain:\n  " + "\n  ".join(violations)


def test_the_database_stays_behind_the_storage_package() -> None:
    """Outside ``data/storage`` the store is reached through the package,
    so another database replaces ``sqlite/`` and nothing else."""
    inside = f"{PACKAGE}.data.storage"
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in _modules()
        if not name.startswith(inside)
        for imported, line in _imports(path)
        if imported.startswith(f"{inside}.sqlite")
    ]
    assert not violations, "SQLite reached directly:\n  " + "\n  ".join(violations)


def test_web_framework_stays_in_the_web_layer() -> None:
    violations = []
    for name, path in _modules():
        part = _own_part(name)
        if part == "web" or part in ASSEMBLY:
            continue
        for imported, line in _imports(path):
            if imported.split(".")[0] in WEB_LIBRARIES:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "web framework outside web/:\n  " + "\n  ".join(violations)


def test_providers_are_reached_through_the_registry() -> None:
    """Outside data/providers/, only the package itself is imported."""
    prefix = f"{PACKAGE}.data.providers"
    violations = []
    for name, path in _modules():
        if name.startswith(prefix):
            continue
        for imported, line in _imports(path):
            if imported.startswith(prefix + "."):
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "provider module imported directly:\n  " + "\n  ".join(
        violations
    )


def test_concurrency_is_written_with_anyio() -> None:
    """The one concurrency library (docs/ARCHITECTURE.md 8, rule 2): no
    module imports asyncio, so every part runs on either event loop."""
    offenders = [
        f"{name}:{line}"
        for name, path in _modules()
        for module, line in _imports(path)
        if module == "asyncio" or module.startswith("asyncio.")
    ]
    assert offenders == []


def test_every_layer_exists_and_is_documented() -> None:
    """A layer without a docstring is a folder, not a decision."""
    for layer in LAYERS:
        init = ROOT / layer / "__init__.py"
        assert init.exists(), f"{layer}/__init__.py is missing"
        docstring = ast.get_docstring(ast.parse(init.read_text(encoding="utf-8")))
        assert docstring, f"{layer}/__init__.py has no docstring"


def test_each_wrapped_library_has_one_home() -> None:
    violations = []
    for name, path in _modules():
        for imported, line in _imports(path):
            home = LIBRARY_HOMES.get(imported.split(".")[0])
            if home is not None and name != home and not name.startswith(home + "."):
                violations.append(f"{name}:{line} imports {imported}, home is {home}")
    assert not violations, "library outside its home:\n  " + "\n  ".join(violations)


# The calls that write a line at INFO or above (docs/LOGGING.md rule 6.2).
LOUD = {"info", "warning", "error", "exception", "critical"}
LOGGERS = {"log", "logger", "logging"}


def _loud_calls(path: Path) -> list[int]:
    """The lines where the file logs at INFO or above: ``log.info(...)``,
    ``logging.warning(...)``, ``logging.getLogger(...).error(...)``."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in LOUD:
            continue
        target = node.func.value
        if (isinstance(target, ast.Name) and target.id in LOGGERS) or (
            isinstance(target, ast.Call)
            and isinstance(target.func, ast.Attribute)
            and target.func.attr == "getLogger"
        ):
            found.append(node.lineno)
    return found


def test_the_data_layer_logs_nothing_above_debug() -> None:
    """It decides nothing and knows neither actor nor reason: what it
    notices goes up as a result or an error, and the domain logs it."""
    loud = [
        f"{name}:{line}"
        for name, path in _modules()
        if _own_part(name) == "data"
        for line in _loud_calls(path)
    ]
    assert loud == []


def _gets_a_logger(path: Path) -> list[int]:
    """The lines where the file calls ``getLogger``."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "getLogger")
            or (isinstance(node.func, ast.Name) and node.func.id == "getLogger")
        )
    ]


def test_the_domain_logs_through_activities() -> None:
    """A domain service hands an activity to ``ActivityLog.record``. No
    module of the domain but the activities has a logger (rule 6.1)."""
    activity = f"{PACKAGE}.domain.activity"
    found = [
        f"{name}:{line}"
        for name, path in _modules()
        if _own_part(name) == "domain"
        and name != activity
        and not name.startswith(activity + ".")
        for line in _gets_a_logger(path) + _loud_calls(path)
    ]
    assert found == []


# What a handler of any failure may do instead of raising: record it as an
# activity, or hand it to the logging module's own error handling.
RECORDERS = {"record", "_record", "_failed", "handleError"}
BROAD = {"Exception", "BaseException"}


def _broad_handlers(path: Path) -> list[ast.ExceptHandler]:
    """The handlers of ``except Exception`` and ``except BaseException``."""
    return [
        node
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ExceptHandler)
        and (
            node.type is None
            or (isinstance(node.type, ast.Name) and node.type.id in BROAD)
        )
    ]


def _raises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) for n in ast.walk(handler))


def _records(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if name in RECORDERS:
                return True
    return False


def test_a_broad_handler_raises_or_records() -> None:
    """A handler of any failure raises on, or records what it swallows.
    One of BaseException always raises, so a cancellation goes through."""
    silent = []
    for name, path in _modules():
        for handler in _broad_handlers(path):
            catches_all = handler.type is None or (
                isinstance(handler.type, ast.Name)
                and handler.type.id == "BaseException"
            )
            if _raises(handler) or (not catches_all and _records(handler)):
                continue
            silent.append(f"{name}:{handler.lineno}")
    assert silent == []


# --- the packages of the domain and of data (docs/REFACTORING.md 2, 8.4) -------------

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


def test_a_package_is_imported_through_its_init() -> None:
    """So a package can split or merge its modules without its callers
    noticing: the other packages, the layers above and the assembly."""
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in _modules()
        for imported, line in _imports(path)
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
        for name, path in _modules()
        for imported, node in _from_imports(path)
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
    for name, path in _modules():
        own = _package_part(name)
        if own is None or own[0] != layer:
            continue
        for imported, _ in _imports(path):
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


# The packages of each layer in lines (docs/ARCHITECTURE.md 2): each
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
        {"locks", "paging", "bounded"},
    ),
    "data": (
        {"backup"},
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


# --- the assembly and the command line (docs/ARCHITECTURE.md 3) -----------------

# The modules of assembly/ and cli/ in lines, the top first. A command of
# cli/ reaches the assembly, and through it the layers, never another
# command.
PART_LINES = {
    "assembly": (
        {"web"},
        {"lifecycle"},
        {"domain"},
        {"storage", "secrets", "providers"},
        {"services"},
    ),
    "cli": (
        {"serve", "openapi", "paths", "users", "keys", "backup", "restore"},
        {"common"},
    ),
}


def test_nothing_below_reaches_the_assembly_or_the_command_line() -> None:
    """The layers and what they share are built by the assembly. Were one
    of them to import it, the assembly could no longer pick its parts."""
    above = {"assembly", "cli", "__main__"}
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in _modules()
        if _own_part(name) not in ASSEMBLY
        for imported, line in _imports(path)
        if _own_part(imported) in above
    ]
    assert not violations, "assembly reached from below:\n  " + "\n  ".join(violations)


def test_the_assembly_knows_no_command() -> None:
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in _modules()
        if _own_part(name) == "assembly"
        for imported, line in _imports(path)
        if _own_part(imported) == "cli"
    ]
    assert not violations, "the assembly imports cli/:\n  " + "\n  ".join(violations)


@pytest.mark.parametrize("part", sorted(PART_LINES))
def test_the_modules_of_the_assembly_keep_their_lines(part: str) -> None:
    line_of = {module: n for n, line in enumerate(PART_LINES[part]) for module in line}
    folder = ROOT / part
    assert set(line_of) == {
        p.stem for p in folder.glob("*.py") if p.stem != "__init__"
    }, f"a module of {part}/ outside the lines"
    violations = []
    for name, path in _modules():
        parts = name.split(".")
        if len(parts) != 3 or parts[1] != part:
            continue
        for imported, line in _imports(path):
            other = imported.split(".")
            if len(other) < 3 or other[:2] != [PACKAGE, part]:
                continue
            if line_of[other[2]] <= line_of[parts[2]]:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)
