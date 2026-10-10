"""The plain text of an HTML body, as a reader sees it. Standard library
only.

What a reader would not see is left out: scripts, styles, and elements
hidden by an attribute or by their inline style. Blocks go on lines of
their own, list items get a dash, and a link keeps its address after its
text.

The mail page of the service shows it, and the model of the MCP server
reads it, so the model reads what a person sees, no more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

# Content of these elements is never shown by a mail client.
_INVISIBLE = {"script", "style", "head", "title", "template", "noscript"}
_BLOCKS = {
    "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "blockquote", "pre", "hr", "section", "article", "ul", "ol",
}  # fmt: skip
_VOID = {"br", "hr", "img", "meta", "link", "input", "wbr", "col", "area", "base"}
_LENGTH = re.compile(r"^(-?\d*\.?\d+)\s*([a-z%]*)")
# Below these a text cannot be read: in px, and relative to the font.
_SMALLEST_PX = 2.0
_SMALLEST_RELATIVE = 0.2
# A text pushed this far left or up is off any screen.
_FAR_OFF_PX = -500.0
# Only these let ``left`` and ``top`` move an element.
_POSITIONED = {"absolute", "fixed", "relative"}
# Values of a colour that name no colour of their own. Two of them
# alike say nothing about what a reader sees.
_NOT_A_COLOUR = {
    "inherit",
    "initial",
    "unset",
    "revert",
    "revert-layer",
    "currentcolor",
}


def hides(style: str) -> bool:
    """Whether an inline style hides the element's text from a reader:
    not shown, too small or too faint to see, pushed off the page, cut to
    nothing, or in the colour of its own background. A colour that only
    matches the page around the element, or a style sheet, is not seen
    here."""
    rules: dict[str, str] = {}
    for declaration in style.split(";"):
        name, colon, value = declaration.partition(":")
        if colon:
            rules[name.strip().lower()] = " ".join(value.lower().split())
    size = _css_length(rules.get("font-size"))
    moved = ("left", "top") if rules.get("position") in _POSITIONED else ()
    indent = [_css_length(rules.get(key)) for key in ("text-indent", *moved)]
    cut = any(
        _css_length(rules.get(key)) == (0.0, "px") for key in ("height", "max-height")
    )
    return (
        rules.get("display") == "none"
        or rules.get("visibility") in ("hidden", "collapse")
        or (size is not None and _too_small(*size))
        or _css_number(rules.get("opacity"), default=1.0) < 0.1
        or any(i is not None and i[0] <= _FAR_OFF_PX for i in indent)
        or (cut and rules.get("overflow") == "hidden")
        or rules.get("color") == "transparent"
        or (
            _colour(rules.get("color"))
            and rules["color"] == rules.get("background-color", rules.get("background"))
        )
    )


def _colour(value: str | None) -> bool:
    """Whether a CSS value is a colour of its own: ``#...``, ``rgb(...)``,
    ``hsl(...)`` or a named colour. Not ``inherit`` and the like."""
    if value is None:
        return False
    if value.startswith(("#", "rgb(", "rgba(", "hsl(", "hsla(")):
        return True
    return value.isalpha() and value not in _NOT_A_COLOUR


def _css_length(value: str | None) -> tuple[float, str] | None:
    """A CSS length as number and unit, ``px`` for a bare number."""
    found = _LENGTH.match(value or "")
    if found is None:
        return None
    return float(found.group(1)), found.group(2) or "px"


def _too_small(number: float, unit: str) -> bool:
    if unit in ("px", "pt"):
        return number < _SMALLEST_PX
    if unit in ("em", "rem"):
        return number < _SMALLEST_RELATIVE
    if unit == "%":
        return number < _SMALLEST_RELATIVE * 100
    return number <= 0


def _css_number(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


@dataclass
class _Open:
    """An element not closed yet."""

    tag: str
    hidden: bool
    # A link: its address, and where its text starts in the parts.
    href: str | None = None
    start: int = 0


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._open: list[_Open] = []

    @property
    def hidden(self) -> bool:
        return any(element.hidden for element in self._open)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        hidden = (
            tag in _INVISIBLE
            or "hidden" in values
            or values.get("aria-hidden") == "true"
            or hides(values.get("style") or "")
        )
        if not self.hidden:
            if tag in _BLOCKS:
                self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")
        if tag not in _VOID:
            self._open.append(_Open(tag, hidden, values.get("href"), len(self.parts)))

    def handle_endtag(self, tag: str) -> None:
        """Closes the innermost open element of that name, and what it left
        open inside. An end tag without its start tag closes nothing, so it
        cannot end a hidden element early."""
        if tag in _VOID:
            return
        tags = [element.tag for element in self._open]
        if tag not in tags:
            return
        at = len(tags) - 1 - tags[::-1].index(tag)
        closed = self._open[at:]
        del self._open[at:]
        if self.hidden or any(element.hidden for element in closed):
            return
        for element in reversed(closed):
            if element.tag == "a":
                self._link(element)
        if tag in _BLOCKS:
            self.parts.append("\n")

    def _link(self, element: _Open) -> None:
        """The address after the text of a link, unless it is that text."""
        href = element.href
        label = "".join(self.parts[element.start :]).strip()
        if href and href.startswith(("http://", "https://")) and href != label:
            self.parts.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def from_html(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
