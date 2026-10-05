"""Schema 13: webhooks go with the user who made them. Those of users deleted
before were posted to by nobody's rights, and nobody could remove them.
"""

from __future__ import annotations

from .migration import Migration


class WebhooksOfDeletedUsers(Migration):
    version = 13
    statements = ("DELETE FROM webhooks WHERE user_id NOT IN (SELECT id FROM users)",)
