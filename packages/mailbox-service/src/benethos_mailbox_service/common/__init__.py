"""Cross-cutting helpers, like ``config`` and ``errors``: read by every layer.

Only what more than one layer needs, with no I/O and no state beyond what
a caller holds. ``redact`` is the one module with state of its own. They
import the standard library and nothing else: no layer, no third-party
library. What only one layer needs stays in that layer.
"""
