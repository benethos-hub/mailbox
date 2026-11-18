"""Not a test: the public interface of a published package as JSON, for
the record in docs/ that test_interfaces.py holds to the code, as
docs/openapi.json is held to the service. ``client`` and ``common`` for
``benethos_mailbox_client`` and ``benethos_mailbox_common``:

    uv run python tests/interface.py PACKAGE > docs/<client|common>-interface.json

Each public module, none of whose names starts with an underscore, names
what it defines itself: classes with their bases, fields, members and
methods, functions with their signatures, values as they are or as the
source writes them. A package names what it exports in ``__all__``. A
name a module imports is recorded where it is defined, once.
"""

from __future__ import annotations

import ast
import dataclasses
import enum
import importlib
import inspect
import json
import pkgutil
import sys
from types import ModuleType
from typing import Any

# Values recorded as they are. Others as their source writes them, which
# reads alike on every version of Python.
_PLAIN = (str, int, float, bool, type(None))


def interface(package: str) -> dict[str, Any]:
    """Each public module of ``package`` and what it holds, by name."""
    root = importlib.import_module(package)
    modules = {package: root}
    for found in pkgutil.walk_packages(root.__path__, f"{package}."):
        if not any(part.startswith("_") for part in found.name.split(".")):
            modules[found.name] = importlib.import_module(found.name)
    return {name: _module(module) for name, module in sorted(modules.items())}


def written(package: str) -> str:
    """The record of ``package`` as the file in docs/ holds it."""
    return json.dumps(interface(package), indent=2) + "\n"


def _module(module: ModuleType) -> dict[str, Any]:
    described: dict[str, Any] = {}
    exported = getattr(module, "__all__", None)
    if exported is not None:
        described["__all__"] = sorted(exported)
    source = inspect.getsource(module)
    for name, written_as in _defined(source).items():
        value = getattr(module, name)
        if inspect.isclass(value):
            described[name] = _class(value)
        elif inspect.isroutine(value):
            described[name] = _function(value)
        elif isinstance(value, _PLAIN):
            described[name] = {"value": value}
        else:
            described[name] = {"source": ast.get_source_segment(source, written_as)}
    return described


def _defined(source: str) -> dict[str, ast.AST]:
    """The public names a module's source defines at its top, each with
    the node that gives its value."""
    names: dict[str, ast.AST] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            names[node.target.id] = node.value
    return {n: names[n] for n in sorted(names) if not n.startswith("_")}


def _function(value: Any) -> dict[str, Any]:
    wrapped = getattr(value, "__wrapped__", None)
    if wrapped is not None and ".endpoints." in wrapped.__module__:
        # A method that sends an endpoint: its signature is the endpoint's.
        described: dict[str, Any] = {
            "sends": f"{wrapped.__module__}.{wrapped.__qualname__}"
        }
    else:
        described = {"signature": _signature(value)}
    if inspect.iscoroutinefunction(value):
        described["async"] = True
    return described


def _signature(value: Any) -> str:
    try:
        return str(inspect.signature(value))
    except (TypeError, ValueError):
        return "(...)"


def _class(cls: type) -> dict[str, Any]:
    described: dict[str, Any] = {
        "bases": [f"{b.__module__}.{b.__qualname__}" for b in cls.__bases__]
    }
    if issubclass(cls, enum.Enum):
        described["members"] = {m.name: repr(m.value) for m in cls}
        return described
    record = dataclasses.is_dataclass(cls)
    if record:
        params = cls.__dataclass_params__  # type: ignore[attr-defined]
        described["frozen"] = params.frozen
        described["fields"] = {f.name: _field(f) for f in dataclasses.fields(cls)}
    else:
        hints = vars(cls).get("__annotations__", {})
        if hints:
            described["annotations"] = {k: str(v) for k, v in sorted(hints.items())}
    methods = _methods(cls, record)
    if methods:
        described["methods"] = methods
    return described


def _methods(cls: type, record: bool) -> dict[str, Any]:
    """The public methods a class defines itself, and its ``__init__``
    unless the dataclass made it from the fields."""
    found: dict[str, Any] = {}
    for name, value in sorted(vars(cls).items()):
        if name.startswith("_") and (name != "__init__" or record):
            continue
        if isinstance(value, staticmethod | classmethod):
            found[name] = _function(value.__func__)
        elif isinstance(value, property):
            found[name] = {"property": True}
        elif inspect.isroutine(value):
            found[name] = _function(value)
    return found


def _field(field: dataclasses.Field[Any]) -> dict[str, Any]:
    described: dict[str, Any] = {"type": str(field.type)}
    if field.default is not dataclasses.MISSING:
        described["default"] = repr(field.default)
    elif field.default_factory is not dataclasses.MISSING:
        described["default"] = f"{field.default_factory.__name__}()"
    if not field.init:
        described["init"] = False
    if field.kw_only is True:
        described["keyword"] = True
    return described


if __name__ == "__main__":
    # Lines end in LF on every system, as the file in docs/ does.
    sys.stdout.reconfigure(newline="\n")  # type: ignore[union-attr]
    sys.stdout.write(written(sys.argv[1]))
