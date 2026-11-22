"""Agents that read and sort a mailbox.

Each agent decides one narrow question about a message and takes one
reversible action. Mail is reached through the REST API of a mailbox
service, a language model through an OpenAI-compatible gateway. See
docs/mailbox-agents/CONCEPT.md.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # The distribution (PyPI) name, which differs from the import package name.
    __version__ = version("benethos-mailbox-agents")
except PackageNotFoundError:  # pragma: no cover - package not installed
    __version__ = "0.0.0+unknown"
