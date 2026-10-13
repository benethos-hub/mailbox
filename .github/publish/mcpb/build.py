"""Stage the Claude Desktop bundle (.mcpb) of the MCP server.

The bundle is a uv one: Claude Desktop brings uv and Python and installs
what the bundle's pyproject.toml and uv.lock name on the first start. The
MCP server needs the client and the common package of this workspace, so
the bundle does not carry the workspace. Its pyproject.toml pins the MCP
server's version on PyPI instead, and uv.lock is made once that version is
there:

    python .github/publish/mcpb/build.py <staging dir>
    uv lock --directory <staging dir>
    npx @anthropic-ai/mcpb pack <staging dir> <file>.mcpb

The release job of publish.yml runs these after the upload to PyPI. The
manifest is committed as it ships. tests/test_mcpb.py of the service holds
it to the package and runs this script into a temporary folder. Standard
library only, so it runs without the project's environment.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
MCP = REPOSITORY / "packages" / "mailbox-mcp"

# Name in the bundle: source in the repository.
FILES = {
    "manifest.json": HERE / "manifest.json",
    "server.py": HERE / "server.py",
    "icon.png": REPOSITORY / "assets" / "brand" / "icon.png",
    "README.md": MCP / "README.md",
    "LICENSE": REPOSITORY / "LICENSE",
}


def pyproject() -> str:
    """The bundle's project: the MCP server of this version from PyPI,
    and nothing of its own to build."""
    project = tomllib.loads((MCP / "pyproject.toml").read_text("utf-8"))["project"]
    return (
        "[project]\n"
        f'name = "{project["name"]}-bundle"\n'
        f'version = "{project["version"]}"\n'
        f'requires-python = "{project["requires-python"]}"\n'
        f'dependencies = ["{project["name"]}=={project["version"]}"]\n'
        "\n"
        "[tool.uv]\n"
        "package = false\n"
    )


def stage(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name, source in FILES.items():
        shutil.copy2(source, target / name)
    (target / "pyproject.toml").write_text(pyproject(), "utf-8", newline="\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: build.py <staging dir>")
    stage(Path(sys.argv[1]))
    print(f"staged the bundle in {sys.argv[1]}", file=sys.stderr)
