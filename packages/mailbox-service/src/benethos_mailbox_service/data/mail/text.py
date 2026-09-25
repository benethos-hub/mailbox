"""The plain text of an HTML body, for the text part of a mail that was
written as HTML only. Standard library only.

What a reader would not see is left out: scripts, styles and elements
hidden by attribute or inline style. Blocks go on lines of their own, list
items get a dash, and a link keeps its address after its text.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# Content of these elements is never shown by a mail client.
_INVISIBLE = {"script", "style", "head", "title", "template", "noscript"}
_BLOCKS = {
    "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "blockquote", "pre", "hr", "section", "article", "ul", "ol",
}  # fmt: skip
_VOID = {"br", "hr", "img", "meta", "link", "input", "wbr", "col", "area", "base"}
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?![.\d])",
    re.IGNORECASE,
)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden: list[bool] = []  # per open element
        self._links: list[tuple[str | None, int]] = []  # href, start in parts

    @property
    def hidden(self) -> bool:
        return any(self._hidden)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        hidden = (
            tag in _INVISIBLE
            or "hidden" in values
            or values.get("aria-hidden") == "true"
            or bool(_HIDDEN_STYLE.search(values.get("style") or ""))
        )
        if not self.hidden:
            if tag in _BLOCKS:
                self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")
        if tag == "a":
            self._links.append((values.get("href"), len(self.parts)))
        if tag not in _VOID:
            self._hidden.append(hidden)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not self._hidden:
            return
        self._hidden.pop()
        if self.hidden:
            return
        if tag == "a" and self._links:
            href, start = self._links.pop()
            label = "".join(self.parts[start:]).strip()
            if href and href.startswith(("http://", "https://")) and href != label:
                self.parts.append(f" ({href})")
        if tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def from_html(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
