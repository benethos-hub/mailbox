"""The secrets no text of an error may carry, and ``redact``."""

from __future__ import annotations

__all__ = ["forget_secrets", "redact", "register_secret"]

_REDACTED = "[redacted]"

# A secret shorter than this is not registered: replacing every "a" in a
# text would make the text useless and protect nothing.
_SHORTEST = 6

_SECRETS: set[str] = set()


def register_secret(secret: str | None) -> None:
    """Remember ``secret``, so :func:`redact` takes it out of any text."""
    if secret and len(secret) >= _SHORTEST:
        _SECRETS.add(secret)


def forget_secrets() -> None:
    """Forget every registered secret. For tests."""
    _SECRETS.clear()


def redact(text: str) -> str:
    """Replace every registered secret in ``text`` with a placeholder.

    The longest first, so a secret that contains another is replaced whole.
    """
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    return text
