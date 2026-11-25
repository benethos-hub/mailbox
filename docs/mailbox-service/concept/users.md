# Concept: users, permissions and authentication

Part of the [concept](../CONCEPT.md): section 7.5.

## 7.5 Users, permissions and authentication

**Decided 2026-09-24:** callers of the REST API are **users** of the
service. Rights belong to the user. A bearer token is only one way for a
user to prove who it is.

The model as one piece, how a right is resolved and shown, and the
changes made to it on 2026-10-05: [PERMISSIONS.md](../PERMISSIONS.md). This section
keeps the decisions and the details.

Terms, since "account" is taken:

| Term | Meaning | Route |
|---|---|---|
| **Account** | a connected mailbox (GMX, Gmail, ...) | `/v1/accounts` |
| **User** | someone or something that calls the API: a person, the MCP server, a script | `/v1/users` |
| **Credential** | how a user authenticates: an API token for the API and the MCP server, a password for the UI | `/v1/users/{id}/tokens`, `/v1/users/{id}/password` |
| **Grant** | a right of a user: which operations on which accounts | part of the user |
| **Role** | a named, reusable set of grants and service rights | `/v1/roles` |

```
 User "Claude Desktop"
   ├─ roles:  mail-reader
   ├─ grants: acc_gmx → mail.write, drafts
   └─ credentials
        ├─ token mbx_…a1  "laptop"   expires 2027-03-01
        └─ token mbx_…b7  "desktop"  expires 2027-03-01
```

### Why users rather than tokens with rights

- **Several tokens, one set of rights.** A token per device or per
  installation, rotated one at a time without an outage. Revoking one does
  not touch the others, and rights are changed in one place.
- **Other ways to authenticate later** without touching the permission
  model: OAuth 2.0 client credentials for machines, mTLS behind a proxy.
  Each is a new credential kind of the same user, as the second factor of
  the configuration UI is, with TOTP or a passkey after the password.
- **The audit log names someone.** "Claude Desktop, token laptop, called
  send_message on acc_info" rather than an anonymous token id.
- **Several people** become possible without a second model. The open
  question of multi-user operation (section 12) shrinks to account ownership.

### Example

| User | May |
|---|---|
| Owner | `admin` |
| Claude Desktop | `acc_gmx`: read and write mail, drafts. No other account. No sending |
| Dashboard | every account: read. Nothing else |
| Newsletter job | `acc_info`: `send_message` only |

As stored:

```json
{
  "id": "usr_7f3a",
  "name": "Claude Desktop",
  "roles": [],
  "service": [],
  "grants": [
    {"accounts": ["acc_gmx"], "allow": ["mail.read", "mail.write", "drafts"]}
  ],
  "disabled": false
}
```

```json
{
  "id": "usr_91c0",
  "name": "Dashboard",
  "roles": ["mail-reader"],
  "grants": []
}
```

with the role

```json
{"id": "mail-reader", "grants": [{"accounts": ["*"], "allow": ["accounts.read", "mail.read"]}]}
```

### The permission model

- **Permission unit = `operationId`.** Every route already has a stable,
  unique `operationId` (6.8), so it is the natural name of a right:
  `list_messages`, `send_message`, `delete_folder`. The finest level is one
  API call.
- **Groups** bundle operations so that ordinary grants stay readable. A
  grant may name groups, single operations or both:

  | Group | Operations |
  |---|---|
  | `accounts.read` | `list_accounts`, `get_account`, `get_status` |
  | `mail.read` | `list_all_messages`, `list_folders`, `list_messages`, `get_message`, `get_message_raw`, `get_attachment`, `list_threads`, `get_thread`, `list_changes`, `list_all_changes` |
  | `mail.write` | `update_message`, `delete_message` to trash (also by a move), `batch_messages`, `create_folder`, `update_folder` |
  | `mail.delete` | `delete_message_permanent` (`delete_message` with `permanent=true`), `delete_folder` |
  | `drafts` | `list_drafts`, `create_draft`, `update_draft`, `delete_draft` |
  | `send` | `send_message`, `send_draft`, `list_outbox`, `get_outbox_job`, `cancel_send` |
  | `mail.share` | `share_attachment`: a link to an attachment for another service (6.3), in no role template |
  | `audit` | `list_sends`, `list_all_sends` on accounts, `list_activity` in `service` |
  | `accounts.manage` | `update_account`, `delete_account`, `verify_account`, `list_server_names`, credentials of mail accounts |
  | `accounts.connect` | `discover_account`, `start_device_oauth`, `poll_device_oauth`, `create_account`. Of the service |
  | `webhooks.manage` | `list_webhooks`, `get_webhook`, `create_webhook`, `update_webhook`, `renew_webhook_secret`, `delete_webhook`. Of the service |
  | `metrics` | `get_metrics`, the figures of the service for a monitor (6.1), of every account. Of the service |
  | `users.read` | `list_users`, `get_user`, `list_tokens`, `get_second_factor`, `list_roles`, `get_role`. Of the service |
  | `users.manage` | those of `users.read`, and `create_user`, `update_user`, `delete_user`, `create_token`, `revoke_token`, `set_password`, `remove_second_factor`, `remove_totp_device`, `remove_passkey`, `create_role`, `replace_role`, `delete_role`. Of the service |
  | `admin` | everything, and `show_recovery_key` (the recovery key in the UI) and `read_service_log` (the log page), [UI.md](../UI.md) 6.5, which nothing else gives. Of the service |

  Permanent deletion and sending are their own groups on purpose: they are
  the two things that cannot be taken back.
- **Account level.** `accounts` is a list of account ids or `"*"`. `"*"`
  includes accounts added later, an explicit list does not.
- **Rights of the service** act on no account. A user and a role name
  them in a list `service` beside the grants, never in a grant
  ([PERMISSIONS.md](../PERMISSIONS.md) 8.1). Whoever connects an account
  gets `accounts.manage` on it.
- **Effective rights** of a user are the union of its direct grants and the
  grants of its roles. Default deny.
- **Check per request.** Credential → user → the route's `operationId` and
  the `account_id` from the path against the effective rights. Operations
  that carry an action in the body (`batch_messages`) are checked per action:
  a batch needs `batch_messages` and the right of the single operation
  (`update_message`, `delete_message` or `delete_message_permanent`). A
  move into the trash or a folder below it, by a single update or a
  batch, needs `delete_message` as well, and where the grants narrow it
  to folders, on the folder of the message, as `DELETE` does. Moving a
  folder below the trash with `update_folder` needs `delete_message` on
  that folder in the same way. Out of the trash and into junk need
  `update_message` alone.
- **Cross-account operations filter instead of failing.** `list_accounts`
  and `GET /v1/changes` return only accounts the user has a grant for.
- **No existence leak.** An account the user has no grant for answers `404`,
  as if it did not exist. A granted account with a missing operation
  answers `403 forbidden`, naming the missing right.
- **Every route declares its right.** Each operation carries `x-permission`
  in the OpenAPI document, and a test fails when a `/v1` operation has none.
  A new route cannot slip out unguarded.
- **No escalation.** A user with `users.manage` can only hand out rights it
  holds itself, so a delegated administrator cannot create anyone stronger
  than itself.
- **Constraints.** A grant can narrow further without changing the model:
  `recipients` (send only to `*@firma.example`) and `max_sends_per_day` are
  the main guard against prompt injection (7.7). `expires_at` ends a grant at a time. `folders` (read
  only `INBOX` and `Invoices`) keeps reading, writing and deleting to
  those folders and their subfolders ([PERMISSIONS.md](../PERMISSIONS.md)
  8.5).

  **Decided 2026-09-24:** `recipients` takes addresses, `*@domain` and `*`
  (anyone), without regard to case. A subdomain is named on its own.
  Constraints count per grant: a send is allowed when one grant that allows
  it on the account accepts every recipient and its limit is not reached.
  `max_sends_per_day` counts mails, whatever their number of recipients,
  that the user sent from the account in the last 24 hours, rolling.

  Rules of the implementation (phase 3):
  - Null means no constraint. Recipients are checked once the mail is
    composed: To, Cc and Bcc, and for a reply the recipients taken from the
    original. `send_draft` checks the stored draft.
  - `*@domain` does not accept a local part with `%` or `!`. Some servers
    route `bob%evil.org@domain` on to another host. Such an address passes
    only when the grant names it exactly.
  - A refused recipient answers `403 recipient_not_allowed`, a reached
    limit `429 send_limit_reached` with `Retry-After`. A retry with its
    `Idempotency-Key` returns the stored result and is not counted again.
  - Only sends with the outcome `sent` count. Sends of one user from one
    account run one after the other, so two cannot both pass the limit.
  - No escalation: a user with `users.manage` hands out `send_message` or
    `send_draft` only as narrow as one of its own grants for them, or
    narrower.

### Credentials

- **API token**, for the API and the MCP server:
  - Format `mbx_` + 64 random base62 characters, a little over 380 bits.
    Shown **once** on creation, stored as a SHA-256 hash (a random token of
    that length needs no slow hash).
  - Per token: `name`, `created_at`, `expires_at` (optional, at most
    3650 days ahead, else `400`), `last_used_at`, `revoked_at`.
  - A token carries the rights of its user, no more. Narrowing a single
    token below its user is left open, since a second user with fewer
    rights does the same job.
- **Password**, for the configuration UI only (**decided 2026-09-27**):
  - The user signs in with its `name`, which is unique regardless of case.
  - Stored as a scrypt hash with a salt of its own, from the standard
    library. A hash made with older parameters is made anew at the next
    sign-in.
  - At least 15 characters, at most 256, any characters. No rules on
    character classes (NIST SP 800-63B for a single factor).
  - A wrong name and a wrong password answer alike, in the same time: an
    unknown name is checked against a hash of its own.
  - Users change their own password with the current one and, with a
    second factor on, that factor as well (AUTHENTICATION.md). The
    change forced after the sign-in asks for no factor. A user with
    `users.manage` sets the password of a user whose rights it covers, as
    for tokens: whoever sets a password can sign in as that user. A
    password set by someone else must be changed at the next sign-in.
    `users set-password <name>` on the host sets one without the UI, for
    a forgotten password of the last administrator.
  - In the API, `POST /v1/users/{user_id}/password` (`set_password`)
    does the same, with a password or with none, when the service makes
    a one-time password and answers it once. A user without a password
    cannot sign in to the UI.
- **The UI sign-in switch** (**decided 2026-09-27**): `ui_sign_in` on
  the user says whether it may sign in to the UI at all. Without it the
  user is an API user: tokens only.
  - A new user is an API user unless `ui_sign_in` is set. The first
    admin from `users create-admin` has it.
  - Switched off: the stored password is deleted, running UI sessions
    end at the next request, and a sign-in answers as a wrong password
    does, so nobody learns that the name exists. The log names the
    reason. Setting a password or a one-time password is refused.
    Tokens keep working.
  - Switched on: the user still has no password. It gets a one-time
    password as a new user does, on its page in the UI or with
    `POST /v1/users/{user_id}/password`, and changes it at the first
    sign-in.
  - Who switches: a user with `update_user`, for users whose rights it
    covers, as for any change of a user. Not for itself: a user cannot
    lock itself out of the UI. Nor can it disable itself, as it cannot
    delete itself.
  - On the host, `users set-password <name>` switches it on as well and
    says so. It is the way back in when nobody can sign in.
  - In the API: `ui_sign_in` on the user, in `POST /v1/users` (false
    when left out) and `PATCH /v1/users/{user_id}`.
- **A second factor** for the UI sign-in, TOTP with recovery codes
  (**decided 2026-10-09**), passkeys as its second method (**decided
  2026-11-18**): a choice per user, set up in the UI, asked after the
  password. The factors of the UI sign-in and how each is set up and
  removed: [AUTHENTICATION.md](../AUTHENTICATION.md).
- **Later:** a passkey in place of the password (AUTHENTICATION.md 9),
  OAuth 2.0 client credentials for machines. Rights come from grants alone. The
  switch above says where a user may sign in, not what it may do.
- A disabled user fails authentication with every credential at once.
  Rights changes take effect on the next request. Revoking a token is
  immediate.
- Sign-ins to the UI, failed ones and changed passwords are written to
  the service log with user name, client address and time, never a
  password.

### Bootstrap

A fresh installation has no users. `benethos-mailbox-service users create-admin`
on the host creates the first `admin` user and prints a one-time password
once. The first sign-in to the UI asks for a password of its own. All
further users, passwords and tokens are made in the UI, tokens also
through the API.

**Decided 2026-09-27:** every caller is a user, and so every call names
one in the audit. Tests and live checks create a user and a token of
their own.

### Audit log

User, credential, operation, account, status, time. Never content, never a
secret. The audit of administration, beyond sends, is
[AUDIT.md](../AUDIT.md): sign-ins and changes to users, tokens, roles,
accounts and webhooks, read by `GET /v1/audit` with `audit` in
`service`.

**Decided 2026-09-24:** the audit of sends is built first, together with
the send limits, which count from it. Every attempt through `send_message`
or `send_draft` is one record: time, user, token,
account, operation, recipients, outcome (`sent`, `denied` by a grant,
`failed`), error code, refused recipients and the Message-ID. A send put
into the outbox adds a record `queued`, each attempt of its job a record
of its own, and a job that ends without an attempt saying so a record
`cancelled`, `unknown` or `failed`. Each of them names the job
(`outbox_job_id`). Only `sent` counts against a send limit. It keeps no
reference to account or user, so it outlives both. A record is kept for
`MAILBOX_SERVICE_AUDIT_DAYS` days, 90 by default, `0` keeps every
record. Old ones are purged at start and as a send comes in, once an
hour at most.
`GET /v1/accounts/{account_id}/sends` reads it, newest first, with the
right `list_sends` (group `audit`). `GET /v1/sends` (`list_all_sends`)
reads it across the accounts the caller may audit, deleted ones
included for a grant on every account. `user`, `outcome`, `recipient`
(part of an address), `after` and `before` narrow both lists together.

### Endpoints

| Method | Path | Right |
|---|---|---|
| GET | `/v1/me` | any authenticated user. Who am I, and my effective rights resolved to operations per account, with how each account fares: `status`, `attention`, `last_sync_at` |
| GET | `/v1/permissions` | any authenticated user. The catalogue of operations and groups |
| GET / POST | `/v1/users` | GET `users.read`, POST `users.manage` |
| GET / PATCH / DELETE | `/v1/users/{user_id}` | GET `users.read`, the others `users.manage`. Name, roles, service, grants, disabled, `ui_sign_in`. Each answer also says how the user signs in to the UI: `has_password`, `must_change`, `last_sign_in_at`, `second_factor` |
| GET / POST | `/v1/users/{user_id}/tokens` | GET `users.read`, POST `users.manage`. POST returns the token once |
| DELETE | `/v1/users/{user_id}/tokens/{token_id}` | `users.manage`. Revoke |
| POST | `/v1/users/{user_id}/password` | `users.manage`. A password to change at the next sign-in, or a one-time password answered once |
| GET / DELETE | `/v1/users/{user_id}/second-factor` | GET `users.read`: the devices of the user's second factor ([AUTHENTICATION.md](../AUTHENTICATION.md)), never a secret. DELETE `users.manage`: every device, never the caller's own |
| DELETE | `/v1/users/{user_id}/second-factor/totp/{device_id}` | `users.manage`. One TOTP device, never the caller's own |
| DELETE | `/v1/users/{user_id}/second-factor/passkeys/{passkey_id}` | `users.manage`. One passkey, never the caller's own |
| GET / POST | `/v1/roles` | GET `users.read`, POST `users.manage` |
| GET / PUT / DELETE | `/v1/roles/{role_id}` | GET `users.read`, the others `users.manage` |
| GET | `/v1/audit` | `audit` in `service`. The audit of administration, newest first ([AUDIT.md](../AUDIT.md)) |

### And the MCP server

- It is a user of its own, typically with `mail.read`, `mail.write` and
  `drafts` on chosen accounts. It never gets `accounts.manage` or
  `users.manage`.
- It needs no `accounts.read`. Every token may call `/v1/me`. That answer
  lists each account the token has any right on, with its address and the
  operations allowed there. The tool `list_accounts` is built on it.
  `accounts.read` opens the full account records instead: the server
  settings, the state and which credentials are stored. The model does not
  need them.
- At start it calls `/v1/me` and registers **only the tools its user can
  use**. The user's rights decide what is offered to the model.
- **Decided 2026-10-16:** while it runs it asks `/v1/me` again every
  `MAILBOX_MCP_RIGHTS_SECONDS`, 60 by default, over stdio and HTTP, and
  at once when a tool is refused with `403 forbidden`, a right missing.
  With `0` it asks only at start. When the tools change it tells its clients with
  `notifications/tools/list_changed`, so a right granted or taken away
  shows without a restart. When the service refuses the token, every
  tool goes away but `server_status`. **Decided 2026-10-16:** a user
  that may do nothing keeps `list_accounts` alone beside
  `server_status`, and it lists no account, so the model can say why
  nothing else is there.
- **Decided 2026-10-29:** the tool `server_status` is always offered,
  whatever the token may do, also when the service refuses the token.
  It asks the service nothing for its answer. It names the server's own
  version, its transport, Python, the MCP library and its uptime, and
  with `details` the service as the server's own requests last found
  it.
- A refused token is asked for no more, since each refusal counts
  against the address like a wrong token (LIMITS.md). A tool refused
  with `401` counts as such a refusal. A new token needs a restart.
  A tool refused for a missing right asks at most every 5 seconds.
  Only the rights checks answer `403 forbidden`. A grant's limits have
  codes of their own, such as `recipient_not_allowed`, and a mail
  server's refusal answers `502`.
- **Decided 2026-10-12:** `/v1/me` says how each account fares, its
  `status`, whether it needs a person's `attention` and its last
  successful sync, so a model learns of a problem before a tool fails.
  The text of the last error stays with `GET /v1/status`.
