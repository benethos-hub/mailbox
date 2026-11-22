"""What a validation error says, without its input."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

__all__ = ["describe_invalid"]


def describe_invalid(exc: Exception, name: Callable[[str], str] = str) -> str:
    """What is wrong, as a :class:`ConfigError` may say it: for a validation
    error the place and the rule of each problem, the place passed through
    ``name``, never the input, which may be a secret or a piece of mail. For
    another error its class."""
    if not isinstance(exc, ValidationError):
        return type(exc).__name__
    return ", ".join(
        f"{name('.'.join(str(p) for p in e['loc']))}: {e['msg']}"
        for e in exc.errors(include_input=False, include_url=False)
    )
