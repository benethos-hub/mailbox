"""Write the Claude Desktop bundle's checksum into server.json.

The registry wants a fileSha256 for the mcpb package, and that hash exists
only once the release has built the bundle. The committed server.json holds
a placeholder of zeros. The release job downloads the bundle it attached and
runs this script before it publishes:

    python3 fill_bundle_checksum.py <server.json> <bundle.mcpb>

It refuses a bundle whose file name is not the one the entry points at, and
an entry that no longer holds the placeholder, so a hash is never written
twice or for the wrong file.

The registry takes an entry whole or not at all. Should it refuse the one
with the bundle, the job drops the bundle and publishes the rest, so the
version is listed at least with PyPI:

    python3 fill_bundle_checksum.py --drop <server.json>

Standard library only, so it runs without the project's environment.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PLACEHOLDER = "0" * 64


def _write(server_json: Path, entry: dict[str, object]) -> None:
    text = json.dumps(entry, indent=2, ensure_ascii=False) + "\n"
    server_json.write_text(text, "utf-8", newline="\n")


def fill(server_json: Path, bundle: Path) -> str:
    entry = json.loads(server_json.read_text("utf-8"))
    (package,) = [p for p in entry["packages"] if p["registryType"] == "mcpb"]
    named = package["identifier"]
    if named.rsplit("/", 1)[-1] != bundle.name:
        raise SystemExit(f"{bundle.name} is not the file the entry points at: {named}")
    if package["fileSha256"] != PLACEHOLDER:
        raise SystemExit("the entry's fileSha256 is not the placeholder")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    package["fileSha256"] = digest
    _write(server_json, entry)
    return digest


def drop(server_json: Path) -> None:
    entry = json.loads(server_json.read_text("utf-8"))
    kept = [p for p in entry["packages"] if p["registryType"] != "mcpb"]
    if len(kept) == len(entry["packages"]):
        raise SystemExit("the entry lists no bundle to drop")
    entry["packages"] = kept
    _write(server_json, entry)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--drop":
        drop(Path(sys.argv[2]))
    elif len(sys.argv) == 3:
        print(fill(Path(sys.argv[1]), Path(sys.argv[2])), file=sys.stderr)
    else:
        sys.exit(
            "usage: fill_bundle_checksum.py <server.json> <bundle.mcpb>\n"
            "       fill_bundle_checksum.py --drop <server.json>"
        )
