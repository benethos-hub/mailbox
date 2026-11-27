# Concept: state

Part of the [concept](../CONCEPT.md).

One SQLite file per agent, or per instance of one, with numbered migrations that are never changed
once released.

| Table | Holds |
|---|---|
| `cursor` | the feed state token |
| `passes` | when the loop last showed progress, after a message, a pass or a slice of a wait, for the health check |
| `messages` | message id, account id, state, attempts, next attempt |
| `steps` | message, step, prompt version, model alias and the model reported, result, tokens, duration. A baseline's prompt version is the agent version, with `/` and the prompt version after it when the agent has one, such as `5/v4` |
| `actions` | message, action, its argument (the keyword, the path of the folder, or the form and the addresses of a forward drafted), what was there before, when, stage, whether it was carried out. A stage `keyword`, the former word of `suggest`, is written as `suggest` by migration 3 (2026-11-27) |
| `open_items` | for an agent that follows a message, `awaiting_reply`, with a deadline (`invoices` kept them without one until it was removed on 2026-11-25): message, thread, due, whether the keyword is on the message, the stage its keyword was recorded in without being set, closed and why, for `awaiting_reply` `replied`, `followed_up`, `keyword_removed`, `message_gone` or `discarded`. The keyword counts as on the message until the runtime saw it taken off, also after the item closed |
| `calls` | the full request and answer of a model call, only while `PROMPT_RETENTION_DAYS` keeps them |

The schema version is the file's `user_version`. A reader opens the file
read-only and refuses one newer than it knows.

**Migrations (decided 2026-11-18).** Each step of the schema is a class
`VNNNN<Subject>` of `Migration` in its own module
`store/migrations/versions/vNNNN_<subject>.py`, listed at its number in
`MIGRATIONS`, which refuses a gap or a step out of place. A step holds
single SQL statements and, where it needs Python, the method `before`,
which answers notes. A writer runs the steps a file lacks when it opens
it, each in a transaction of its own with its `user_version`, and a file
newer than the program is refused. There is no way back. The store logs
nothing: it keeps what it did as `Migrated`, and the command that opened
the file logs it. A step that shipped in a release is never changed, down
to a comment: `RELEASED` in `packages/mailbox-agents/tests/store/test_store.py` holds the sha256 of each
released step's module.

What is stored: ids, decisions, evidence quotes, counts and times, and the
paths of folders and the keywords an action names or found. What is not: the text of a mail, its subject, its sender or an attachment. A message
is fetched again by its id when it is needed.

One exception, off by default: `MAILBOX_AGENTS_PROMPT_RETENTION_DAYS` above
zero keeps the full request and answer of each model call for that many
days, for finding an error. They are deleted after it, and the deleted
rows are overwritten in the file and in its write-ahead log.

There is no session store. No step carries a conversation from one call to
the next. Context a decision needs, such as the thread, is fetched fresh.
