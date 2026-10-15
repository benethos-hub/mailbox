"""Schema 21: what each account can do, stored with it.

The capabilities and the marks of an account follow from what its server
answers when the account is connected or verified (docs/UNIFORM.md, rule
R4). They are kept as JSON in ``abilities``, so that the account answers
them while its server cannot be reached (decision 6.11).

The accounts already there have none yet. The service asks their servers
when it next takes them up.
"""

from __future__ import annotations

from ..migration import Migration


class V0021Abilities(Migration):
    version = 21
    statements = ("ALTER TABLE accounts ADD COLUMN abilities TEXT",)
