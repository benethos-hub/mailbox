"""The code itself, checked: where it logs, what a handler of any failure
does, how large a module and a class may grow, and that a helper of
``common/`` exists once. The layering is ``test_architecture``'s.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .source_helpers import HELPERS, PACKAGE, ROOT, modules, own_part

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
        for name, path in modules()
        if own_part(name) == "data"
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
        for name, path in modules()
        if own_part(name) == "domain"
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
    for name, path in modules():
        for handler in _broad_handlers(path):
            catches_all = handler.type is None or (
                isinstance(handler.type, ast.Name)
                and handler.type.id == "BaseException"
            )
            if _raises(handler) or (not catches_all and _records(handler)):
                continue
            silent.append(f"{name}:{handler.lineno}")
    assert silent == []


# Hard limits (docs/ARCHITECTURE.md 15): what grows beyond them is split
# by subject.
MAX_LINES = 500
MAX_METHODS = 30
# Where the limits hold: the package, its tests and the live checks.
REPOSITORY = Path(__file__).resolve().parents[3]
SIZED = (ROOT, Path(__file__).resolve().parent, REPOSITORY / "live")


def test_modules_and_classes_stay_small() -> None:
    violations = []
    for path in sorted(p for folder in SIZED for p in folder.rglob("*.py")):
        text = path.read_text("utf-8")
        name = path.relative_to(REPOSITORY).as_posix()
        lines = len(text.splitlines())
        if lines > MAX_LINES:
            violations.append(f"{name}: {lines} lines")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ClassDef):
                methods = sum(
                    isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                    for n in node.body
                )
                if methods > MAX_METHODS:
                    violations.append(f"{name}: {node.name} has {methods} methods")
    assert not violations, "beyond the limits:\n  " + "\n  ".join(violations)


# The copies the shared helpers replaced (docs/ARCHITECTURE.md 2), and
# the one module that holds each now. None may come back elsewhere, under
# its name or with a leading underscore. A helper of mailbox-common, such
# as plural, is held once by that package's own test.
REPLACED_COPIES = {
    "one_line": HELPERS,
    "loopback": HELPERS,
    "host_of": HELPERS,
    "day": HELPERS,
    "before": HELPERS,
    "user_names": "web/pages/filters.py",
    "filter": "web/pages/filters.py",
}


def _functions(path: Path) -> set[str]:
    """The functions a module defines at its top level, without a leading
    underscore."""
    tree = ast.parse(path.read_text("utf-8"))
    return {
        node.name.lstrip("_")
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_a_helper_of_common_exists_once() -> None:
    helpers = ROOT / HELPERS
    shared = set().union(*(_functions(p) for p in helpers.rglob("*.py")))
    violations = []
    for path in sorted(ROOT.rglob("*.py")):
        if path.is_relative_to(helpers):
            continue
        name = path.relative_to(ROOT).as_posix()
        replaced = {f for f, home in REPLACED_COPIES.items() if home != name}
        for function in sorted(_functions(path) & (shared | replaced)):
            violations.append(f"{name}: {function}")
    assert not violations, "a copy of a helper:\n  " + "\n  ".join(violations)


def test_templates_ask_operations_not_providers() -> None:
    """A template asks ``can``, what the page was handed: never a
    capability, and it compares no kind of account. Setting up an account
    draws its form from the kind's description (U6). Showing the kind is
    no question."""
    from benethos_mailbox_service.data.models import ProviderType

    kinds = "|".join(re.escape(p.value) for p in ProviderType)
    named = re.compile(r"capabilit|[\"'](?:" + kinds + r")[\"']", re.IGNORECASE)
    templates = ROOT / "web" / "pages" / "templates"
    assert len(list(templates.rglob("*.html"))) > 20
    violations = [
        f"{path.relative_to(templates).as_posix()}: {found.group(0)}"
        for path in sorted(templates.rglob("*.html"))
        for found in named.finditer(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "a template names a provider:\n  " + "\n  ".join(violations)


def test_no_test_module_imports_another() -> None:
    """What tests of several modules share is a fixture in the conftest.py
    of their nearest common folder, or a helper in a module of its own
    there (docs/ARCHITECTURE.md 13): a test module is no library. In the
    tests of all four packages."""
    violations = []
    for path in sorted((REPOSITORY / "packages").glob("*/tests/**/*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.level):
                continue
            # from .test_x import y, and from . import test_x
            named = [node.module or ""] + [a.name for a in node.names]
            if any(n.split(".")[-1].startswith("test_") for n in named):
                name = path.relative_to(REPOSITORY).as_posix()
                violations.append(f"{name}:{node.lineno} from {node.module or '.'}")
    assert not violations, "imports a test module:\n  " + "\n  ".join(violations)


# A fixture each module of a server of its own brings, by design: the
# one of tests/conftest.py is the IMAP server.
OWN_SERVER = "server"
# What the two rules below found when they came, left for a change of its
# own (2026-10-29): a module beside the fixture of a conftest, and two
# modules of a folder with a fixture of one name.
SHADOWING = {
    ("domain/changes/test_changes_delta.py", "clock"),
    ("domain/sync/test_jmap_sync.py", "client"),
    ("domain/sync/test_take_up.py", "services"),
}
REPEATED = {
    ("domain/accounts", "world"),
    ("domain/mailbox", "box"),
    ("web/pages", "endpoint"),
}


def _fixtures(path: Path) -> set[str]:
    """The names of the fixtures a module defines at its top."""
    found = set()
    for node in ast.parse(path.read_text("utf-8")).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute) and target.attr == "fixture":
                found.add(node.name)
    return found


def _test_modules() -> list[tuple[Path, Path]]:
    """Every test module of the four packages, with its package's tests."""
    return [
        (tests, path)
        for tests in sorted((REPOSITORY / "packages").glob("*/tests"))
        for path in sorted(tests.rglob("test_*.py"))
    ]


def test_no_test_module_hides_a_fixture_of_a_conftest() -> None:
    """A module that defines a fixture of a conftest.py above it under the
    same name leaves a reader to guess which one holds (ARCHITECTURE 13)."""
    violations = []
    for tests, path in _test_modules():
        name = path.relative_to(tests).as_posix()
        mine = _fixtures(path) - {OWN_SERVER}
        for folder in [path.parent, *path.parent.parents]:
            conftest = folder / "conftest.py"
            if conftest.exists():
                for fixture in sorted(mine & _fixtures(conftest)):
                    if (name, fixture) not in SHADOWING:
                        violations.append(f"{name}: {fixture}")
            if folder == tests:
                break
    assert not violations, "hides a fixture of a conftest:\n  " + "\n  ".join(
        violations
    )


def test_two_test_modules_of_a_folder_share_no_fixture_name() -> None:
    """A fixture two modules of a folder need goes to its conftest.py, or
    each names its own (ARCHITECTURE 13)."""
    seen: dict[tuple[Path, str], list[str]] = {}
    for tests, path in _test_modules():
        folder = path.parent.relative_to(tests).as_posix()
        for fixture in _fixtures(path) - {OWN_SERVER}:
            if (folder, fixture) not in REPEATED:
                seen.setdefault((path.parent, fixture), []).append(path.name)
    violations = [
        f"{folder.relative_to(REPOSITORY).as_posix()}: {fixture} in {', '.join(names)}"
        for (folder, fixture), names in sorted(seen.items())
        if len(names) > 1
    ]
    assert not violations, "a fixture name twice:\n  " + "\n  ".join(violations)


def test_no_live_script_imports_another() -> None:
    """What the live checks share is in live/checks/ (ARCHITECTURE 13): a
    script is no library, and importing one loads all it needs."""
    live = REPOSITORY / "live"
    scripts = {path.stem for path in live.glob("*.py")}
    violations = []
    for path in sorted(live.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.ImportFrom) and not node.level:
                named = [node.module or ""]
            elif isinstance(node, ast.Import):
                named = [alias.name for alias in node.names]
            else:
                continue
            for module in named:
                if module.split(".")[0] in scripts:
                    violations.append(f"{path.name}:{node.lineno} {module}")
    assert len(scripts) > 5
    assert not violations, "a live script imports another:\n  " + "\n  ".join(
        violations
    )


def test_no_package_entry_defines_a_class() -> None:
    """The entry of a package offers, it does not implement
    (ARCHITECTURE 5.2): no __init__.py of the four packages defines a
    class."""
    violations = [
        f"{path.relative_to(REPOSITORY).as_posix()}: {node.name}"
        for path in sorted((REPOSITORY / "packages").glob("*/src/**/__init__.py"))
        for node in ast.parse(path.read_text("utf-8")).body
        if isinstance(node, ast.ClassDef)
    ]
    assert not violations, "a class in a package's entry:\n  " + "\n  ".join(violations)
