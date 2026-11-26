"""What Alembic runs for a command: the revisions on the connection the
database hands over in ``attributes``, each in a transaction of its own.
No ``alembic.ini`` and no configuration of the log: the service sets
both."""

from __future__ import annotations

from alembic import context

context.configure(
    connection=context.config.attributes["connection"],
    transaction_per_migration=True,
)
with context.begin_transaction():
    context.run_migrations()
