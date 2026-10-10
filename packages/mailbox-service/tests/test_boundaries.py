"""At a package boundary, values travel as named records (docs/ARCHITECTURE.md
9). For each package of the workspace, what it offers is checked: an
answer is no tuple and no dict, a parameter carries no type of a package
above it, and a dataclass is frozen and slotted.

What a package offers: every module of a group of mailbox-common; what
mailbox-client exports, and the answer of each endpoint, which is a
method of both clients; what a package of the service or the MCP server
names in ``__all__``, and the public methods of the domain services the
web layer reaches through ``Services``.

``ALLOWED`` names what stays as it is, and why. An entry that no longer
matches fails, so the list cannot grow stale."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[2]
SRC = {
    "common": PACKAGES / "mailbox-common/src/benethos_mailbox_common",
    "client": PACKAGES / "mailbox-client/src/benethos_mailbox_client",
    "service": PACKAGES / "mailbox-service/src/benethos_mailbox_service",
    "mcp": PACKAGES / "mailbox-mcp/src/benethos_mailbox_mcp",
}
# The packages above each one: their types are not its parameters.
ABOVE = {
    "common": (
        "benethos_mailbox_service",
        "benethos_mailbox_mcp",
        "benethos_mailbox_client",
    ),
    "client": ("benethos_mailbox_service", "benethos_mailbox_mcp"),
    "service": ("benethos_mailbox_mcp",),
    "mcp": ("benethos_mailbox_service",),
}
# What an answer may not be. Call[T] of the client is judged by T.
UNNAMED = re.compile(r"^(tuple|dict|Mapping|MutableMapping)\b|^(list|Sequence)\[dict")

ALLOWED = {
    # The body of a request as the API takes it, for create_draft and
    # send_message: the JSON the route describes.
    "client endpoints/compose.py message_body": "a request body",
    # Lookups by a key, not a record with fields.
    "service assembly/providers.py build_oauth": "a client per provider",
    "service domain/sync/service.py SyncService.natives": "provider id per message id",
    "service domain/system/status.py StatusService.healths": "health per account id",
    # Free JSON: the settings of an account as the API and the store hold
    # them, and an answer of a JMAP server.
    "service data/providers/registry.py settings_defaults": "account settings",
    "service data/providers/registry.py settings_from_servers": "account settings",
    "service data/providers/imap/connect.py settings_from": "account settings",
    "service data/providers/jmap/connect.py settings_from": "account settings",
    "service data/providers/pop3/provider.py settings_from": "account settings",
    "service data/protocols/jmap/answers.py result": "a JMAP answer",
    # Filled during one pass of the sync, then applied at once.
    "service data/storage/index.py IndexChanges": "built up, then applied",
}


@dataclass(frozen=True, slots=True)
class Offered:
    """A function, a method or a class a package offers."""

    package: str
    module: str  # relative to the package's source
    name: str  # Class.method for a method
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef

    @property
    def key(self) -> str:
        return f"{self.package} {self.module} {self.name}"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text("utf-8"))


def _defined(package: str, path: Path, names: set[str] | None) -> Iterator[Offered]:
    """The public functions and classes of a module, or those of ``names``."""
    module = path.relative_to(SRC[package]).as_posix()
    for node in _tree(path).body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if node.name.startswith("_") or (names is not None and node.name not in names):
            continue
        yield Offered(package, module, node.name, node)


def _exported(package: str) -> Iterator[Offered]:
    """What each ``__init__.py`` names in ``__all__``, where it is defined."""
    for init in sorted(SRC[package].rglob("__init__.py")):
        tree = _tree(init)
        names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                getattr(target, "id", "") == "__all__" for target in node.targets
            ):
                names = set(ast.literal_eval(node.value))
        yield from _defined(package, init, names)
        for node in tree.body:
            if not (isinstance(node, ast.ImportFrom) and node.level == 1):
                continue
            taken = {a.name for a in node.names if (a.asname or a.name) in names}
            base = init.parent / (node.module or "").replace(".", "/")
            for path in (base.with_suffix(".py"), base / "__init__.py"):
                if taken and path.is_file():
                    yield from _defined(package, path, taken)


def _domain_services() -> Iterator[Offered]:
    """The public methods of the domain's classes that ``Services`` holds."""
    root = SRC["service"]
    tree = _tree(root / "assembly/services.py")
    holder = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Services"
    )
    held = {
        ast.unparse(item.annotation).split("|")[0].strip()
        for item in holder.body
        if isinstance(item, ast.AnnAssign)
    }
    for path in sorted((root / "domain").rglob("*.py")):
        for cls in _defined("service", path, held):
            assert isinstance(cls.node, ast.ClassDef)
            for item in cls.node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    if not item.name.startswith("_"):
                        name = f"{cls.name}.{item.name}"
                        yield Offered("service", cls.module, name, item)


def offered() -> list[Offered]:
    found: list[Offered] = []
    common = SRC["common"]
    for group in sorted(p for p in common.iterdir() if (p / "__init__.py").is_file()):
        for path in sorted(group.glob("*.py")):
            found += _defined("common", path, None)
    found += _exported("client")
    for path in sorted((SRC["client"] / "endpoints").glob("*.py")):
        found += [
            item
            for item in _defined("client", path, None)
            if isinstance(item.node, ast.FunctionDef)
            and ast.unparse(item.node.returns or ast.Constant(None)).startswith("Call[")
        ]
    for path in sorted((SRC["client"] / "models").glob("*.py")):
        found += _defined("client", path, None)
    found += _exported("service")
    found += _domain_services()
    found += _exported("mcp")
    unique = {item.key: item for item in found}
    return sorted(unique.values(), key=lambda item: item.key)


def _answer(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The answer, when it is a tuple or a dict."""
    if node.returns is None:
        return None
    text = ast.unparse(node.returns)
    if called := re.fullmatch(r"Call\[(.*)\]", text):
        text = called.group(1)
    parts = [part.strip() for part in text.split("|")]
    return text if any(UNNAMED.match(part) for part in parts) else None


def _not_frozen_and_slotted(node: ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        text = ast.unparse(decorator)
        if text.split("(")[0] in ("dataclass", "dataclasses.dataclass"):
            return not ("frozen=True" in text and "slots=True" in text)
    return False


def _breaches() -> dict[str, str]:
    found = {}
    for item in offered():
        node = item.node
        if isinstance(node, ast.ClassDef):
            if _not_frozen_and_slotted(node):
                found[item.key] = "a dataclass not frozen and slotted"
            continue
        if answer := _answer(node):
            found[item.key] = f"answers {answer}"
        for argument in node.args.args + node.args.kwonlyargs:
            text = ast.unparse(argument.annotation) if argument.annotation else ""
            if any(name in text for name in ABOVE[item.package]):
                found[item.key] = f"takes {argument.arg}: {text}"
    return found


def test_values_cross_a_boundary_as_named_records() -> None:
    breaches = _breaches()
    unnamed = [f"{key}: {why}" for key, why in breaches.items() if key not in ALLOWED]
    assert not unnamed, "a tuple, a dict or a loose dataclass:\n  " + "\n  ".join(
        unnamed
    )


def test_every_exception_is_still_needed() -> None:
    stale = sorted(set(ALLOWED) - set(_breaches()))
    assert not stale, "remove from ALLOWED:\n  " + "\n  ".join(stale)


def test_the_check_reaches_every_package() -> None:
    """Each package offers something the check looks at, so a moved
    folder cannot leave one unchecked."""
    assert {item.package for item in offered()} == set(SRC)
    names = {item.key for item in offered()}
    assert "client models/messages.py Message" in names
    assert "service domain/users/totp.py TotpService.begin" in names
    assert "common values/text.py joined" in names
