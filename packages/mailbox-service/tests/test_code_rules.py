"""The code itself, checked: where it logs, what a handler of any failure
does, how large a module and a class may grow, and that a helper of
``common/`` exists once. The layering is ``test_architecture``'s.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .test_architecture import HELPERS, PACKAGE, ROOT, _modules, _own_part

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
