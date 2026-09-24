"""Cross-cutting helpers, like ``config`` and ``errors``: read by every layer.

Only stateless helpers that more than one layer needs. They import the
standard library and nothing else: no layer, no third-party library. What
only one layer needs stays in that layer.
"""
