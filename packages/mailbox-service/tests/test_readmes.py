"""The links of every README and every document, and the contents at
the top of a README.

A link renders whether it leads anywhere or not, so a renamed heading or a
moved file goes unnoticed. Checked here, without the network:

- a link to a heading lands on one, in the same file or another one of
  the repository;
- a link into the repository, relative or as an address on GitHub,
  names a file or folder that is there;
- the READMEs PyPI shows have no relative link, since PyPI renders them
  without the repository around them. A link to a heading is fine there:
  PyPI keeps it on the page;
- a README with two sections or more lists them all, in order, in its
  contents after the title and the short description.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"
# Folders with READMEs that are not the project's own.
SKIPPED = {".git", ".venv", "node_modules", "vendor", "__pycache__", "data"}

# Only the ``](target)`` tail of a link: a badge is a link around an image,
# and its outer target is the one that counts.
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_SRC = re.compile(r"""<img\b[^>]*?\bsrc=["']([^"']+)["']""")
_FENCE = re.compile(r"^```.*?^```", re.M | re.S)
_HEADING = re.compile(r"^(#{1,6}) (.+)$", re.M)
_REPOSITORY = re.compile(
    r"^https://(?:github\.com/benethos-hub/mailbox/(?:blob|tree)/main/"
    r"|raw\.githubusercontent\.com/benethos-hub/mailbox/main/)([^#?]*)(?:#(.*))?$"
)
CONTENTS = "**Contents**"


def _readmes() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("README.md")
        if not SKIPPED & set(path.relative_to(ROOT).parts[:-1])
    )


def _documents() -> list[Path]:
    """The READMEs, the documents in docs/ and CLAUDE.md: the files whose
    links are checked."""
    return [*_readmes(), *sorted((ROOT / "docs").glob("*.md")), ROOT / "CLAUDE.md"]


def _on_pypi(readme: Path) -> bool:
    return readme.parent.parent == PACKAGES


def _text(markdown: str) -> str:
    return _FENCE.sub("", markdown)


def _targets(markdown: str) -> list[str]:
    text = _text(markdown)
    return _LINK.findall(text) + _SRC.findall(text)


def anchor(heading: str) -> str:
    """GitHub's anchor of a heading: the text without HTML and code marks,
    in lower case, punctuation dropped, spaces as hyphens."""
    text = re.sub(r"<[^>]+>", "", heading).replace("`", "").strip().lower()
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def _headings(markdown: str) -> list[tuple[int, str, str]]:
    """Level, text and anchor of each heading. A repeated anchor gets -1,
    -2 and so on, as on GitHub."""
    found: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for marks, heading in _HEADING.findall(_text(markdown)):
        base = unique = anchor(heading)
        suffix = 0
        while unique in seen:
            suffix += 1
            unique = f"{base}-{suffix}"
        seen.add(unique)
        found.append((len(marks), heading, unique))
    return found


def _anchors(path: Path) -> set[str]:
    return {a for _, _, a in _headings(path.read_text("utf-8"))}


def _broken(readme: Path, target: str) -> str | None:
    """Why ``target`` in ``readme`` leads nowhere, or None."""
    if target.startswith("#"):
        return None if target[1:] in _anchors(readme) else "no such heading"
    found = _REPOSITORY.match(target)
    if found:
        path, fragment = ROOT / found[1], found[2]
    elif target.startswith(("http://", "https://", "mailto:")):
        return None
    elif _on_pypi(readme):
        return "relative, which PyPI cannot follow"
    else:
        file, _, fragment = target.partition("#")
        path = (readme.parent / file).resolve()
    if not path.exists():
        return "no such file"
    if fragment and path.suffix == ".md" and fragment not in _anchors(path):
        return "no such heading there"
    return None


@pytest.mark.parametrize(
    "readme", _documents(), ids=lambda p: p.relative_to(ROOT).as_posix()
)
def test_every_link_leads_somewhere(readme: Path) -> None:
    broken = [
        f"{target}: {why}"
        for target in _targets(readme.read_text("utf-8"))
        if (why := _broken(readme, target))
    ]
    assert not broken, "\n  ".join(["links that lead nowhere:", *broken])


def contents(markdown: str) -> str:
    """The contents a README shows: its sections and their parts, after
    the title, linked to their headings."""
    lines = [CONTENTS, ""]
    for level, heading, target in _headings(markdown):
        if level in (2, 3):
            indent = "  " * (level - 2)
            title = re.sub(r"<[^>]+>", "", heading).strip()
            lines.append(f"{indent}- [{title}](#{target})")
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "readme", _readmes(), ids=lambda p: p.relative_to(ROOT).as_posix()
)
def test_a_readme_of_several_sections_lists_them_at_its_top(readme: Path) -> None:
    text = readme.read_text("utf-8")
    sections = [h for h in _headings(text) if h[0] == 2]
    if len(sections) < 2:
        assert CONTENTS not in text
        return
    wanted = contents(text)
    assert wanted in text, f"the contents should read:\n\n{wanted}"
    assert text.index(wanted) < text.index("\n## "), "the contents come first"


def test_the_readmes_are_found() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _readmes()}
    assert {"README.md", "packages/mailbox-mcp/README.md"} <= names
    assert not any("vendor" in name for name in names)


def test_the_documents_are_found() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _documents()}
    assert {"CLAUDE.md", "docs/CONCEPT.md", "README.md"} <= names


def test_the_anchor_follows_githubs_rules() -> None:
    assert anchor("What it is for") == "what-it-is-for"
    assert anchor("With `docker run`") == "with-docker-run"
    assert anchor("Users, rights and tokens") == "users-rights-and-tokens"
    assert anchor('<img src="x.svg"> Mailbox') == "mailbox"
    assert anchor("7.4 Folders") == "74-folders"


def test_the_check_sees_what_is_broken(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# T\n\n## Here\n\n[a](#here) [b](#gone) [c](missing.md)\n"
        "[![x](https://img.example/x.svg)](LICENSE)\n```\n[d](nothing)\n```\n",
        "utf-8",
    )
    targets = _targets(readme.read_text("utf-8"))
    assert targets == [
        "#here",
        "#gone",
        "missing.md",
        "https://img.example/x.svg",
        "LICENSE",
    ]
    assert [_broken(readme, t) for t in targets] == [
        None,
        "no such heading",
        "no such file",
        None,
        "no such file",
    ]
    assert _broken(readme, "https://github.com/benethos-hub/mailbox/blob/main/nope.md")
    assert not _broken(
        readme, "https://github.com/benethos-hub/mailbox/blob/main/LICENSE"
    )
