"""The assembly and the command line (docs/ARCHITECTURE.md 2): nothing
below reaches them, the assembly knows no command, and their modules
keep their lines."""

from __future__ import annotations

import pytest

from .source_helpers import ASSEMBLY, PACKAGE, ROOT, imports, modules, own_part

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
        for name, path in modules()
        if own_part(name) not in ASSEMBLY
        for imported, line in imports(path)
        if own_part(imported) in above
    ]
    assert not violations, "assembly reached from below:\n  " + "\n  ".join(violations)


def test_the_assembly_knows_no_command() -> None:
    violations = [
        f"{name}:{line} imports {imported}"
        for name, path in modules()
        if own_part(name) == "assembly"
        for imported, line in imports(path)
        if own_part(imported) == "cli"
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
    for name, path in modules():
        parts = name.split(".")
        if len(parts) != 3 or parts[1] != part:
            continue
        for imported, line in imports(path):
            other = imported.split(".")
            if len(other) < 3 or other[:2] != [PACKAGE, part]:
                continue
            if line_of[other[2]] <= line_of[parts[2]]:
                violations.append(f"{name}:{line} imports {imported}")
    assert not violations, "against the lines:\n  " + "\n  ".join(violations)
