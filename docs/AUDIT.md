# The audit of administration

Proposal of 2026-09-28, the second of two steps, for later. The first
step, [LOGGING.md](LOGGING.md), names every event the service logs. This
step stores those a person caused, so "who changed what, when" can be
answered after the log is gone. It is the design of
[PERMISSIONS.md 8.6](PERMISSIONS.md#86-an-audit-of-administration) in
full. Nothing of it is built until the user asks. What the user decides
is marked as decided, everything else is the proposal.

## 1. Log and audit

The log is for the operator: everything the service did, in order, for
this process, dropped by the host when it likes. The audit is for
accountability: every action a user took on a record, in the database,
kept for a set time, readable through the API and the UI. Sends have
such an audit already (CONCEPT 7.5, `/v1/sends`). This one covers the
rest of administration.

A rule of the two together: an audited event is logged too, with the
same fields, from the same place in the code. The log line is the
human form of the record.

## 2. What is audited

Every event of LOGGING.md section 5 in which a user is the actor and a
record changes hands, and every sign-in. By area:

| Area | Events (LOGGING.md) |
|---|---|
| Sign-in (5.2) | signed in, failed sign-in, revoked or expired token presented, wrong password to confirm a step |
| Users, passwords, tokens, roles (5.3) | user created, changed, deleted; password changed, set, one-time made; token issued, revoked; role created, replaced, deleted |
| Accounts and OAuth (5.4) | account connected, changed, verified, removed; connecting failed; sign-in with a provider started, finished, failed |
| Webhooks (5.7) | webhook created, removed |
| Rate limits (5.9) | address locked out, name waiting, token or address limited |
| The rest (5.8) | recovery key shown, service log read, one-time password made on the host |

Not audited: what the worker, the dispatcher and the providers do on
their own (sync, IDLE, posts, refreshes, pauses), reads that hand out
nothing secret, and sends, which have their own audit.

## 3. The record

| Field | Content |
|---|---|
| `id` | `evt_` + 64 hex |
| `at` | time, UTC |
| `user_id`, `user_name` | who, the name as it was then |
| `credential` | `token:<id>`, `password`, `host` for a CLI command, null for a failed sign-in |
| `operation` | the right of the catalogue where one applies (`create_user`, `revoke_token`), else a name of this table (`sign_in`, `sign_in_failed`, `locked_out`) |
| `record` | the id of the record touched: `usr_`, `acc_`, `tok_`, `whk_`, a role id |
| `source` | the client address, null without a request |
| `outcome` | `done`, `refused`, `failed` |
| `detail` | the log line's "why" or "what changed", masked, never a secret, never content |

The record keeps no reference to user or account, so it outlives both,
as the send audit does. `user_name` is written for that reason.

## 4. Storage, API, UI

- **Table `events`**, a migration of its own, indexes on `at` and on
  `(user_id, at)`. Written in the same transaction as the change where
  there is one, so a change without its record cannot happen.
- **Retention**: `MAILBOX_SERVICE_AUDIT_DAYS`, 90 by default, purged as
  the change log is purged, on write and at most once an hour.
- **`GET /v1/audit`**: newest first, paged with `next_cursor`, filters
  `user`, `operation`, `record`, `after`, `before`. Right `audit` on
  the service, so the group `audit` appears in both lists of
  PERMISSIONS.md 8.1. `x-permission` as on every route, the OpenAPI
  document regenerated.
- **UI**: a page **Audit** under Service for `users.read`, a list page
  of UI.md 4.1 with the filter bar, and a card **Recent activity** on
  the user's page with that user's newest events.
- **The log page** stays as it is: the audit does not replace it.

## 5. One place in the code

A helper in the domain, `events.record(access, operation, record,
outcome, detail)`, writes the log line of LOGGING.md and the audit
record. It replaces the plain `log.info` calls that LOGGING.md step 2
to 4 put into the domain services, call by call, in the same places.
Nothing else writes an audit record, and no route does.

The helper needs `Access.source` and the credential id, which LOGGING.md
puts onto `Access` in its step 2. The CLI commands that change the
database (`users`, `keys`, `restore`) call the helper with `host` as
the credential.

## 6. Order of work

1. LOGGING.md steps 2 to 5 first: the lines exist, the actor and the
   source reach the domain.
2. The `events` table, the repository protocol with an in-memory and a
   SQLite implementation, the helper, the existing lines moved onto it.
3. `GET /v1/audit` and the OpenAPI document.
4. The Audit page and the Recent activity card, walked in `live/ui.py`.
5. Retention and the purge.

Each step a commit on one branch, a CHANGELOG entry for the API.

## 7. Open questions

- 90 days by default, or unbounded like the send audit?
- Should a failed sign-in with an unknown name be stored at all? It
  names what an attacker typed.
- Does the Audit page belong under Service, or is the card on the user's
  page enough for a start?
