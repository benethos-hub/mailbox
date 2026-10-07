"""JSON from a server read into a model at the edge, once: the code
behind it works with typed fields, not with ``dict.get`` and
``isinstance``.

A body of another shape is the server's failure: ``ProviderError``. Its
text is the caller's, never the input, which may hold a token.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    PositiveInt,
    ValidationError,
    ValidatorFunctionWrapHandler,
    WrapValidator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from ...errors import ProviderError


def _or_none(value: object, handler: ValidatorFunctionWrapHandler) -> object:
    try:
        return handler(value)
    except ValidationError:
        return None


def _seconds(value: object, handler: ValidatorFunctionWrapHandler) -> object:
    # JSON's true would pass as 1.
    if value is True or value is False:
        return None
    return _or_none(value, handler)


# A field read as its type, or None when it is of another shape: what is
# odd in it does not spoil the rest of the answer.
OrNone = WrapValidator(_or_none)
# A positive number of seconds as a server wrote it, a number or digits,
# else None.
Seconds = Annotated[PositiveInt | None, WrapValidator(_seconds)]


class Shape(BaseModel):
    """What a server sends: fields it adds are passed by, and a field it
    sends as null counts as left out."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _without_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class CamelShape(Shape):
    """A shape whose fields the server writes in camel case, as JMAP and
    Graph do."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


S = TypeVar("S", bound=BaseModel)


def parse(shape: type[S], data: bytes | str, failure: str) -> S:
    """JSON ``data`` read as ``shape``, else ``ProviderError(failure)``."""
    try:
        return shape.model_validate_json(data)
    except ValidationError:
        raise ProviderError(failure) from None


def read(shape: type[S], data: bytes | str) -> S | None:
    """JSON ``data`` read as ``shape``, None when it is not: for what only
    adds to an answer, such as the detail of an error."""
    try:
        return shape.model_validate_json(data)
    except ValidationError:
        return None


def parse_value(shape: type[S], value: object, failure: str) -> S:
    """``value``, JSON decoded already, read as ``shape``, else
    ``ProviderError(failure)``."""
    try:
        return shape.model_validate(value)
    except ValidationError:
        raise ProviderError(failure) from None


def read_value(shape: type[S], value: object) -> S | None:
    """``value``, JSON decoded already, read as ``shape``, None when it is
    not."""
    try:
        return shape.model_validate(value)
    except ValidationError:
        return None
