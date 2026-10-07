"""The filter bar above a list (docs/UI.md, 4.5).

Every list that filters has the same bar: one search field first, more
filters folded below it, and the active ones as chips, each removable.
A filter is a ``GET`` query, so a filtered list has a URL to keep. This
module reads the query and works out the chips and their links. The
template ``filter_bar`` in ``components/ui.html`` only shows them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypeVar
from urllib.parse import urlencode

from fastapi import Request
from pydantic import BaseModel

from ...common.clock import parse_day
from ...domain.rights import Access
from ..services import get_users
from .deps import if_allowed
from .forms import model_of

Kind = Literal["text", "date", "select", "flag", "checks"]
# Never a filter: the page a pager is on.
NOT_FILTERS = frozenset({"cursor"})

M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: Kind = "text"
    # (value, label) for select and checks.
    options: Sequence[tuple[str, str]] = ()
    # What a select without a value means.
    blank: str = "any"


@dataclass(frozen=True)
class Chip:
    label: str
    # The same list without this filter.
    remove: str


@dataclass(frozen=True)
class FilterBar:
    action: str
    search: Field | None
    fields: Sequence[Field]
    # The values of the query, by name, every value of a name.
    values: dict[str, list[str]]
    # Carried as hidden fields, never a chip: e.g. the folder of a list.
    keep: Sequence[tuple[str, str]]
    chips: list[Chip] = field(default_factory=list)
    # The list without any filter, None when none is set.
    clear: str | None = None

    @property
    def folded(self) -> bool:
        """Whether More filters stays folded: no filter of it is set."""
        return not any(f.name in self.values for f in self.fields)

    def value(self, name: str) -> str:
        return (self.values.get(name) or [""])[0]

    def has(self, name: str, value: str) -> bool:
        return value in self.values.get(name, [])


def filter_bar(
    request: Request,
    fields: Iterable[Field],
    *,
    search: Field | None = None,
    keep: Sequence[tuple[str, str]] = (),
) -> FilterBar:
    """The bar for this request: what is set, and a chip per value."""
    fields = list(fields)
    known = {f.name: f for f in fields}
    if search is not None:
        known[search.name] = search
    kept = {name for name, _ in keep}
    query = [
        (k, v.strip())
        for k, v in request.query_params.multi_items()
        if k not in NOT_FILTERS and v.strip()
    ]
    values: dict[str, list[str]] = {}
    for name, value in query:
        if name in known and name not in kept:
            values.setdefault(name, []).append(value)
    path = request.url.path
    chips = []
    for name, value in query:
        filter_field = known.get(name)
        if filter_field is None or name in kept:
            continue
        rest = [pair for pair in query if pair != (name, value)]
        chips.append(Chip(_chip_label(filter_field, value), _link(path, rest)))
    clear = _link(path, list(keep)) if chips else None
    return FilterBar(
        action=path,
        search=search,
        fields=fields,
        values=values,
        keep=keep,
        chips=chips,
        clear=clear,
    )


def user_names(request: Request, caller: Access) -> dict[str, str]:
    """The users a filter "Who" offers, by id: the caller, and every user
    where the caller may see users."""
    listed: dict[str, str] = if_allowed(
        caller,
        "list_users",
        lambda: {u.id: u.name for u in get_users(request).list_users(caller)},
        {},
    )
    return {caller.user_id: caller.name, **listed}


def records_filter(model: type[M], bar: FilterBar, *fields: str) -> M | None:
    """What the bar above a list of records asks for: who (``user``), the
    ``fields`` by their names, and the days ``after`` and ``before``. None
    when it asks for nothing. Raises ``FormError``, a ``ValueError``, for
    a value that is no filter."""
    wanted = {
        "user_id": bar.value("user") or None,
        **{name: bar.value(name) or None for name in fields},
        "after": parse_day(bar.value("after")),
        "before": parse_day(bar.value("before")),
    }
    if not any(value is not None for value in wanted.values()):
        return None
    return model_of(model, wanted)


def _chip_label(filter_field: Field, value: str) -> str:
    if filter_field.kind == "flag":
        return filter_field.label
    shown = dict(filter_field.options).get(value, value)
    return f"{filter_field.label}: {shown}"


def _link(path: str, query: Sequence[tuple[str, str]]) -> str:
    return f"{path}?{urlencode(query)}" if query else path
