"""The layering, checked instead of only written down.

web -> domain -> data, never the other way. A single reverse import is enough
to undo the split, and it happens by accident: a data module needs one domain
rule, imports it, and the data layer can no longer be used without the domain.
This test reads every import of the package and fails on the first one that
breaks a rule.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE = "benethos_mailbox_api"
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
ASSEMBLY = {"main", "__main__"}

# Web frameworks live in the web layer. main.py builds the app, so it may too.
WEB_LIBRARIES = {"fastapi", "starlette"}

# One library, one home (CLAUDE.md): the only module, or package, allowed to
# import each.
LIBRARY_HOMES = {
    "cryptography": f"{PACKAGE}.data.secrets.cipher",
    "keyring": f"{PACKAGE}.data.secrets.keys",
    "sqlite3": f"{PACKAGE}.data.storage.sqlite",
    "imapclient": f"{PACKAGE}.data.providers.protocols.imap",
    "imap_tools": f"{PACKAGE}.data.mail.parse",
    "smtplib": f"{PACKAGE}.data.providers.protocols.smtp",
    "httpx": f"{PACKAGE}.data.http",
    "dns": f"{PACKAGE}.data.discovery.dns",
    "defusedxml": f"{PACKAGE}.data.discovery.autoconfig",
    "publicsuffixlist": f"{PACKAGE}.data.discovery.suffix",
    "jinja2": f"{PACKAGE}.web.pages.templates",
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every imported module of this file, relative imports resolved."""
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module or ""
            found.append((name, node.lineno))
            # `from . import x` imports a submodule by name, resolve it too.
            if not node.module:
                found += [(f"{name}.{alias.name}", node.lineno) for alias in node.names]
    return found


def _own_part(module: str) -> str | None:
    """'benethos_mailbox_api.domain.accounts' -> 'domain'."""
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
