"""Rules for the code across the five packages, held where they all are
read (docs/mailbox-service/ARCHITECTURE.md 13): the tests of every package, its helpers
and fixtures, the live checks, the entries of the packages, the size of
the tests here and of live/, and how deep a test reads. How the others
use the common package is in test_common_use.py. Each package's own
tests hold the rules for its own source and run alone."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path

from .repository_helpers import ROOT

# Hard limits (docs/mailbox-service/ARCHITECTURE.md 15), as each package holds them for
# its own source and tests.
MAX_LINES = 500
MAX_METHODS = 30
# Where they are held here: the tests of the repository and the live
# checks.
SIZED = (ROOT / "tests", ROOT / "live")


def test_modules_and_classes_stay_small() -> None:
    violations = []
    for path in sorted(p for folder in SIZED for p in folder.rglob("*.py")):
        text = path.read_text("utf-8")
        name = path.relative_to(ROOT).as_posix()
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


def test_no_test_module_imports_another() -> None:
    """What tests of several modules share is a fixture in the conftest.py
    of their nearest common folder, or a helper in a module of its own
    there (docs/mailbox-service/ARCHITECTURE.md 13): a test module is no library. In the
    tests of all five packages."""
    violations = []
    for path in sorted((ROOT / "packages").glob("*/tests/**/*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.level):
                continue
            # from .test_x import y, and from . import test_x
            named = [node.module or ""] + [a.name for a in node.names]
            if any(n.split(".")[-1].startswith("test_") for n in named):
                name = path.relative_to(ROOT).as_posix()
                violations.append(f"{name}:{node.lineno} from {node.module or '.'}")
    assert not violations, "imports a test module:\n  " + "\n  ".join(violations)


def _root_found(path: Path, source: str | None = None) -> list[int]:
    """The lines where ``path``, or ``source`` read as at its place, climbs
    from its own place to the root of the repository with ``parents[n]``."""
    depth = len(path.relative_to(ROOT).parts) - 1
    text = path.read_text("utf-8") if source is None else source
    return [
        node.lineno
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "parents"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == depth
    ]


def test_a_suite_finds_the_root_of_the_repository_once() -> None:
    """Each suite, the one here and the one of each package, names the
    root of the repository in one helper, a ``<subject>_helpers.py``, and
    its modules import it from there."""
    suites = [ROOT / "tests", *sorted((ROOT / "packages").glob("*/tests"))]
    violations = [
        f"{path.relative_to(ROOT).as_posix()}:{line}"
        for suite in suites
        for path in sorted(suite.rglob("*.py"))
        if not path.stem.endswith("_helpers")
        for line in _root_found(path)
    ]
    assert not violations, "the root found again:\n  " + "\n  ".join(violations)


def test_the_check_of_the_root_finds_a_climb() -> None:
    """At packages/<package>/tests/, the root is three folders up, and a
    climb of one folder is no climb to it."""
    probe = ROOT / "packages" / "mailbox-mcp" / "tests" / "probe.py"
    source = "ROOT = Path(__file__).resolve().parents[3]\nX = p.parents[1]\n"

    assert _root_found(probe, source) == [1]


# A module of a test folder that is no test (docs/mailbox-service/ARCHITECTURE.md 13).
HELPER = re.compile(r"conftest|clocks|.+_fake(_.+)?|.+_adapter|.+_helpers|__init__")


def test_a_helper_of_the_tests_is_named_after_its_kind() -> None:
    """A fake in ``<subject>_fake.py``, an adapter on it in
    ``<kind>_adapter.py``, anything else in ``<subject>_helpers.py``, in
    the tests of all five packages. ``tests/installed_check.py`` at the
    root is no helper but a script."""
    violations = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "packages").glob("*/tests/**/*.py"))
        if not path.stem.startswith("test_") and not HELPER.fullmatch(path.stem)
    ]
    assert not violations, "a helper named otherwise:\n  " + "\n  ".join(violations)


CLOCKS = {"Clock", "Seconds"}


def test_a_clock_a_test_moves_is_in_clocks() -> None:
    """The clocks a test moves itself are in ``clocks.py``
    (docs/mailbox-service/ARCHITECTURE.md 13), in the tests of all five
    packages."""
    violations = [
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {node.name}"
        for path in sorted((ROOT / "packages").glob("*/tests/**/*.py"))
        if path.stem != "clocks"
        for node in ast.walk(ast.parse(path.read_text("utf-8")))
        if isinstance(node, ast.ClassDef) and node.name in CLOCKS
    ]
    assert not violations, "a clock outside clocks.py:\n  " + "\n  ".join(violations)


# The fixture of each suite's conftest.py that keeps the settings of the
# machine from a test. None for a package that reads no setting of its
# own.
ISOLATION = {
    "mailbox-service": "no_configuration_from_this_machine",
    "mailbox-client": "no_settings_from_this_machine",
    "mailbox-mcp": "no_configuration_from_this_machine",
    "mailbox-common": None,
    "mailbox-agents": "no_configuration_from_this_machine",
}


def _autouse_fixtures(conftest: Path) -> set[str]:
    """The fixtures a conftest.py makes autouse."""
    if not conftest.exists():
        return set()
    found = set()
    for node in ast.walk(ast.parse(conftest.read_text("utf-8"))):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and any(
                k.arg == "autouse"
                and isinstance(k.value, ast.Constant)
                and k.value.value is True
                for k in decorator.keywords
            ):
                found.add(node.name)
    return found


def test_every_suite_keeps_the_settings_of_the_machine_out() -> None:
    """The conftest.py at the top of each package's suite makes the
    fixture of ``ISOLATION`` autouse, so no setting of the developer's
    machine reaches a test."""
    packages = sorted(p.name for p in (ROOT / "packages").iterdir() if p.is_dir())
    assert sorted(ISOLATION) == packages
    missing = [
        f"{package}: {fixture}"
        for package, fixture in ISOLATION.items()
        if fixture is not None
        and fixture
        not in _autouse_fixtures(ROOT / "packages" / package / "tests" / "conftest.py")
    ]
    assert not missing, "no autouse fixture:\n  " + "\n  ".join(missing)


def _helpers_imported(path: Path) -> Iterator[Path]:
    """The helpers of the tests a module imports by a relative import."""
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if not (isinstance(node, ast.ImportFrom) and node.level):
            continue
        base = path.parents[node.level - 1]
        if node.module:
            names = [node.module]
        else:
            names = [alias.name for alias in node.names]
        for name in names:
            found = base.joinpath(*name.split(".")).with_suffix(".py")
            if found.is_file() and HELPER.fullmatch(found.stem):
                yield found


# A helper every folder of a suite reads, kept at the top of it.
EVERYWHERE = {"clocks", "conftest", "__init__"}


def test_a_helper_sits_in_the_nearest_folder_of_its_importers() -> None:
    """A helper lives in the nearest common folder of the modules that
    import it (docs/mailbox-service/ARCHITECTURE.md 13), in the tests of all five
    packages. ``clocks.py`` is for every folder of a suite."""
    importers: dict[Path, set[Path]] = {}
    for path in sorted((ROOT / "packages").glob("*/tests/**/*.py")):
        for helper in _helpers_imported(path):
            importers.setdefault(helper, set()).add(path.parent)
    violations = []
    for helper, folders in sorted(importers.items()):
        if helper.stem in EVERYWHERE:
            continue
        name = helper.relative_to(ROOT).as_posix()
        nearest = Path(os.path.commonpath(sorted(folders)))
        if helper.parent != nearest:
            violations.append(f"{name} -> {nearest.relative_to(ROOT).as_posix()}")
    assert not violations, "a helper away from its importers:\n  " + "\n  ".join(
        violations
    )


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
    ("domain/mailbox/outgoing", "box"),
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
    """Every test module of the five packages, with its package's tests."""
    return [
        (tests, path)
        for tests in sorted((ROOT / "packages").glob("*/tests"))
        for path in sorted(tests.rglob("test_*.py"))
    ]


def test_no_test_module_hides_a_fixture_of_a_conftest() -> None:
    """A module that defines a fixture of a conftest.py above it under the
    same name leaves a reader to guess which one holds (ARCHITECTURE 13)."""
    violations = []
    excused = set()
    for tests, path in _test_modules():
        name = path.relative_to(tests).as_posix()
        mine = _fixtures(path) - {OWN_SERVER}
        for folder in [path.parent, *path.parent.parents]:
            conftest = folder / "conftest.py"
            if conftest.exists():
                for fixture in sorted(mine & _fixtures(conftest)):
                    if (name, fixture) in SHADOWING:
                        excused.add((name, fixture))
                    else:
                        violations.append(f"{name}: {fixture}")
            if folder == tests:
                break
    assert not violations, "hides a fixture of a conftest:\n  " + "\n  ".join(
        violations
    )
    stale = sorted(SHADOWING - excused)
    assert not stale, f"remove from SHADOWING: {stale}"


def test_two_test_modules_of_a_folder_share_no_fixture_name() -> None:
    """A fixture two modules of a folder need goes to its conftest.py, or
    each names its own (ARCHITECTURE 13)."""
    seen: dict[tuple[Path, str], list[str]] = {}
    excused: dict[tuple[str, str], int] = {}
    for tests, path in _test_modules():
        folder = path.parent.relative_to(tests).as_posix()
        for fixture in _fixtures(path) - {OWN_SERVER}:
            if (folder, fixture) in REPEATED:
                excused[folder, fixture] = excused.get((folder, fixture), 0) + 1
            else:
                seen.setdefault((path.parent, fixture), []).append(path.name)
    violations = [
        f"{folder.relative_to(ROOT).as_posix()}: {fixture} in {', '.join(names)}"
        for (folder, fixture), names in sorted(seen.items())
        if len(names) > 1
    ]
    assert not violations, "a fixture name twice:\n  " + "\n  ".join(violations)
    stale = sorted(e for e in REPEATED if excused.get(e, 0) < 2)
    assert not stale, f"remove from REPEATED: {stale}"


# Where a test reads two private attributes deep, each with its reason
# (review 2026-11-19).
DEEP = {
    "packages/mailbox-client/tests/test_environment.py _http._mounts": (
        "the proxies httpx took from the environment, which it shows nowhere"
    ),
    "packages/mailbox-service/tests/data/protocols/test_http_trust.py "
    "_transport._pool": "the context httpx builds, which it shows nowhere",
    "packages/mailbox-service/tests/data/protocols/test_http_trust.py "
    "_pool._ssl_context": "the context httpx builds, which it shows nowhere",
    "packages/mailbox-service/tests/domain/accounts/test_accounts.py "
    "_gone._after": "what is noted of a deleted account, which nothing shows",
    "packages/mailbox-service/tests/domain/mailbox/test_threads.py "
    "_threads._limit": "the messages a thread lists, set for one test",
    "packages/mailbox-service/tests/domain/sync/test_threads.py "
    "_threads._references": "the references kept, set for one test",
}


def _private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _deep_reads() -> set[str]:
    found = set()
    for _, path in _test_modules():
        name = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and _private(node.attr)
                and _private(node.value.attr)
            ):
                found.add(f"{name} {node.value.attr}.{node.attr}")
    return found


def test_no_test_reads_two_private_attributes_deep() -> None:
    """A test that reads ``x._a._b`` holds two modules to their insides
    and breaks with a move that changes nothing. It checks the behaviour,
    or sets what it needs through a parameter."""
    found = _deep_reads()
    violations = sorted(found - set(DEEP))
    assert not violations, "two private attributes deep:\n  " + "\n  ".join(violations)
    stale = sorted(set(DEEP) - found)
    assert not stale, "remove from DEEP:\n  " + "\n  ".join(stale)


def _live_scripts() -> list[Path]:
    """The live scripts: the files in the folder of each package under
    live/, beside the folder of what they share."""
    return sorted((ROOT / "live").glob("*/*.py"))


def _live_shared() -> list[Path]:
    """The folders of what the live scripts share: live/common/ for every
    package, and one in the folder of a package for its scripts alone."""
    return sorted(p.parent for p in (ROOT / "live").rglob("__init__.py"))


def test_no_live_script_imports_another() -> None:
    """What the live checks share is in live/common/ and in the shared
    folder of a package (ARCHITECTURE 13): a script is no library, and
    importing one loads all it needs."""
    scripts = {path.stem for path in _live_scripts()}
    violations = []
    for path in _live_scripts():
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


def test_the_shared_code_of_the_live_checks_names_each_module() -> None:
    """The docstring of each shared folder's __init__.py says what each
    module holds, so a new one is named there."""
    shared = _live_shared()
    assert [p.name for p in shared] == [
        "common",
        "agents_common",
        "mcp_common",
        "service_common",
    ]
    missing = []
    for folder in shared:
        told = ast.get_docstring(ast.parse((folder / "__init__.py").read_text("utf-8")))
        missing += [
            f"{folder.name}/{path.stem}"
            for path in sorted(folder.glob("*.py"))
            if path.stem != "__init__" and f"``{path.stem}``" not in (told or "")
        ]
    assert not missing, "name in its __init__.py: " + ", ".join(missing)


def test_no_package_entry_defines_a_class() -> None:
    """The entry of a package offers, it does not implement
    (ARCHITECTURE 5.2): no __init__.py of the five packages defines a
    class, nor one of the folders the live checks share."""
    entries = [
        *sorted((ROOT / "packages").glob("*/src/**/__init__.py")),
        *(folder / "__init__.py" for folder in _live_shared()),
    ]
    violations = [
        f"{path.relative_to(ROOT).as_posix()}: {node.name}"
        for path in entries
        for node in ast.parse(path.read_text("utf-8")).body
        if isinstance(node, ast.ClassDef)
    ]
    assert not violations, "a class in a package's entry:\n  " + "\n  ".join(violations)


def test_no_helper_but_conftest_defines_a_fixture() -> None:
    """A fixture of a helper reaches a test module by an import, beside
    the fixtures of the conftest.py files, which it may hide unseen: the
    rule above reads only what a test module defines itself. A fixture
    goes to the nearest conftest.py (ARCHITECTURE 13)."""
    violations = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "packages").glob("*/tests/**/*.py"))
        if not path.stem.startswith("test_")
        and path.stem != "conftest"
        and _fixtures(path)
    ]
    assert not violations, "a fixture in a helper:\n  " + "\n  ".join(violations)
