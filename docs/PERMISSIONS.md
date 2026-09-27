# Users, roles and rights

Proposal of 2026-09-27. One place for the whole model: who may do what,
how that is written down, checked and shown, and what should change.
[CONCEPT 7.5](CONCEPT.md#75-users-permissions-and-authentication) keeps
the record of decisions and the details of credentials. [UI.md](UI.md)
says how the pages look. This file says how the rights work, as they are
today (sections 1 to 7) and as they should be (section 8). What the user
decides is marked as decided, everything else is the proposal.

## 1. Principles

1. **Rights belong to users, not to tokens.** A user is a person, the
   MCP server, a script. A token, a password, later a second factor are
   ways for the user to prove who it is. Rights are changed in one
   place, credentials come and go.
2. **Default deny.** A user may do what a grant allows, nothing else.
   There are no deny rules: what is not allowed is refused.
3. **The unit of a right is one API operation**, its `operationId`.
   Groups bundle operations so grants stay readable. A grant may name
   groups, single operations or both.
4. **Rights are checked in the domain**, once, for the API, the UI and
   the MCP server alike. The web layer only says who is calling.
5. **No escalation.** Whoever hands out rights holds them. A delegated
   administrator can make no one stronger than itself, and can manage
   only users it covers.
6. **What cannot be taken back is its own group.** Sending and deleting
   for good are granted on purpose, never as part of writing.
7. **No existence leak.** An account a user has no right on answers as
   if it did not exist.
8. **Every route names its right.** `x-permission` in the OpenAPI
   document, checked by a test. A new route cannot slip out unguarded.
9. **Someone is always named.** Every call is made by a user, so the
   audit and the log name one.

## 2. Terms

| Term | Meaning | Where |
|---|---|---|
| **Account** | a connected mailbox | `/v1/accounts`, UI Accounts |
| **User** | someone or something that calls the service | `/v1/users`, UI Users |
| **Credential** | how a user proves who it is: a token for the API and the MCP server, a password for the UI | the user's page |
| **Right** | the name of one operation, e.g. `send_message` | the catalogue, `/v1/permissions` |
| **Group** | a named set of rights, e.g. `mail.read` | the catalogue |
| **Grant** | rights on accounts, with constraints: `{accounts, allow, recipients, max_sends_per_day}` | part of a user or a role |
| **Role** | a named, reusable set of grants | `/v1/roles`, UI Roles |
| **Constraint** | a narrowing of a grant that changes no right: which recipients, how many sends a day | part of the grant |
| **Effective rights** | the union of a user's grants and those of its roles | `/v1/me`, the user's page |

## 3. The catalogue

The groups as `domain/permissions.py` holds them today:

| Group | Rights | Bound to |
|---|---|---|
| `accounts.read` | `list_accounts`, `get_account` | an account |
| `mail.read` | `list_all_messages`, `list_folders`, `list_messages`, `get_message`, `get_message_raw`, `get_attachment`, `list_changes`, `list_all_changes` | an account |
| `mail.write` | `update_message`, `delete_message` (to the trash), `batch_messages`, `create_folder`, `update_folder` | an account |
| `mail.delete` | `delete_message_permanent`, `delete_folder` | an account |
| `drafts` | `list_drafts`, `create_draft`, `update_draft`, `delete_draft` | an account |
| `send` | `send_message`, `send_draft` | an account |
| `audit` | `list_sends` | an account |
| `accounts.manage` | `update_account`, `delete_account`, `verify_account`, and `discover_account`, `create_account`, `start_oauth` | an account, the last three every account |
| `webhooks.manage` | `list_webhooks`, `create_webhook`, `delete_webhook` | the service |
| `users.manage` | users, tokens, passwords, roles: fourteen rights | the service |
| `admin` | everything, and `show_recovery_key`, which no grant names | the service |

Three kinds of right hide in this table, and the model treats them
differently without saying so in the grant:

- **Account-bound rights** act on one account. A grant names the
  accounts, `*` for every account, also those added later.
- **Service rights** act on the service: `users.manage`,
  `webhooks.manage`, `admin`. A grant that names them ignores its
  accounts list.
- **Rights on accounts that do not exist yet**: `discover_account`,
  `create_account`, `start_oauth`. They need a grant with `*`. A grant
  naming `accounts.manage` on one account gives `update_account` and
  `verify_account` there, and nothing of connecting.

Two operations are open to every user: `get_me` and `list_permissions`.

## 4. How a right is resolved

- **Effective rights** are the union of the user's grants and the grants
  of its roles. A role is a name for grants, nothing more. A right
  unknown to the catalogue, for example one renamed since the grant was
  written, grants nothing and is logged. It never locks anyone out.
- **Per request**: credential, then user, then the route's right and the
  account from the path against the effective rights. A batch is checked
  per action: `batch_messages` and the right of the single action.
- **Cross-account operations filter.** `list_accounts`, `/v1/messages`,
  `/v1/changes` and the UI's mail page show the accounts the user has a
  right on, and leave the others out.
- **Not seen, not there.** An account outside every grant answers `404`.
  An account inside a grant, but without the right asked for, answers
  `403` and names the missing right.
- **`/v1/me`** answers who the caller is, every account it may act on
  with the operations there, the operations not bound to an account, and
  a warning per account the caller may read mail in and send it anywhere
  from. The MCP server builds its tools from it. The UI's overview and
  user page show the same in words.

## 5. Delegation

A user with `users.manage` administers users, and the model keeps that
from becoming a way up:

- **Hands out only what it holds.** Every grant given, directly or
  through a role, must be covered by the giver's own effective rights, on
  the same accounts. A send right is covered only by a send right of the
  giver with recipients and a limit at least as narrow.
- **Manages only whom it covers.** Changing, deleting, giving a token or
  a password to a user needs the giver to cover that user's effective
  rights. A token or a password for another user means signing in as
  that user, so it is bound by the same rule.
- **A role is changed only by someone who covers it** and every user
  who holds it, since every holder gains what is added and loses what is
  taken. A role in use cannot be deleted.

- **Nobody locks itself out.** A user cannot delete or disable itself
  and cannot take its own UI sign-in.
- **The recovery key is `admin` only**, after the password again.

## 6. Credentials and kinds of user

- **API users** hold tokens. A token carries its user's rights, no more
  and no less. A device gets a token of its own, revoked on its own.
- **UI users** sign in with a password. The switch `ui_sign_in` says
  whether a user may sign in to the UI at all. A new user is an API user
  unless the switch is set. Off means no password, no session, and a
  sign-in that answers as a wrong password does.
- **Both** is a person who also runs a script or the MCP server under
  their own name. The audit then names the token.
- **Disabled** ends every credential at once. Rights changes count from
  the next request.
- Later: TOTP or a passkey as a second factor for UI users, OAuth client
  credentials for machines (IDEAS). New credential kinds, the same
  rights.

## 7. Where the model shows

- **API**: `x-permission` on every operation, `/v1/me`,
  `/v1/permissions`, the user and role resources, `403` naming the right.
- **UI**: the grant editor with a row per grant, accounts as tick boxes,
  groups as tick boxes with their rights as a hint, single rights in a
  text field, recipients and the daily limit. The user's page shows the
  effective rights per account, the sending limits and the warning
  "reads and sends anywhere". Pages and buttons appear only for those
  with the right.
- **MCP server**: at start `/v1/me` decides which tools exist. The
  warning per account goes into the server's instructions, since a mail
  with injected instructions could carry data out through a user that
  reads mail and sends anywhere.
- **Audit**: sends in the database (`/v1/accounts/{id}/sends`, UI Sends).
  Sign-ins, failed sign-ins, password changes and rights changes in the
  service log.

## 8. What should change

Eight changes, each one pull request. The first two change the model,
the rest add to it. None removes a right anyone holds.

### 8.1 Service rights leave the grant

Today a service right sits in a grant whose accounts list means nothing,
and connecting an account needs a grant with `*` although it is not
about any existing account. The editor shows tick boxes for accounts
that do not apply. The proposal: a user (and a role) has two lists.

```json
{
  "id": "usr_7f3a",
  "name": "Operator",
  "roles": [],
  "service": ["accounts.connect", "webhooks.manage"],
  "grants": [
    {"accounts": ["*"], "allow": ["accounts.manage", "mail.read"]}
  ]
}
```

- `service` names service rights: `users.read` and `users.manage` (8.2),
  `webhooks.manage`, `accounts.connect` and `admin`. No accounts, no
  constraints.
- `grants` names account-bound rights, as today. `accounts.manage` keeps
  `update_account`, `delete_account`, `verify_account` and signing in
  again, all about one account.
- `accounts.connect` is a new group of `discover_account`,
  `create_account` and `start_oauth`. Whoever connects an account holds
  its password for a moment and needs a grant on it afterwards: the
  creator gets `accounts.manage` on the new account, and nothing else, so
  it can verify and remove what it connected. Mail rights on it are given
  as on any account.
- `admin` in `service` means every right, as today. `admin` in a grant's
  `allow` is no longer accepted.
- Migration: a stored grant that names a service right or `admin` moves
  those names to `service` and keeps the rest. A grant with `*` and
  `accounts.manage` gets `accounts.connect` in `service`, since it could
  connect before. Nobody loses a right.
- API: `service` on the user and the role, in `POST`, `PATCH` and `PUT`.
  `/v1/me` lists them under `operations` as today. Regenerate the
  OpenAPI document. UI: the editor gets a card **Service rights** with
  one tick box per right, above the grant rows. MCP server: no change,
  it reads `/v1/me`.

### 8.2 `users.manage` splits in two

Reading who exists and giving someone a token are far apart. A support
person, a dashboard or an audit script should see users, roles and
tokens without being able to create any.

| Group | Rights |
|---|---|
| `users.read` | `list_users`, `get_user`, `list_tokens`, `list_roles`, `get_role` |
| `users.manage` | `users.read` and `create_user`, `update_user`, `delete_user`, `create_token`, `revoke_token`, `set_password`, `create_role`, `replace_role`, `delete_role` |

Migration: none, `users.manage` keeps every right it had.

### 8.3 The last administrator stays

Today a user cannot delete or disable itself. It can still take its own
`admin` away, and one administrator can disable the other, until nobody
is left who may sign in to the UI and repair it. The way back is then
the host: `users set-password`. The proposal: the service refuses a
change that would leave no enabled user with `admin` and `ui_sign_in`,
with `409` and a message that says so. The host command stays as the
last resort.

### 8.4 A grant can expire

`expires_at` on a grant, null for never. An expired grant grants
nothing, and the user's page shows it as expired until someone removes
it. Made for trying the MCP server on an account for a week, or a
contractor's script for a month, without a reminder to take the right
away. The token's own `expires_at` stays: the one ends the credential,
the other the right.

### 8.5 Two more constraints

Both narrow a grant and are checked in the domain, as `recipients` is:

- **`folders`**: a list of folder roles or names the grant reaches, null
  for every folder. `mail.read` with `folders: ["inbox", "Invoices"]`
  lists and reads there and nowhere else. `mail.write` with folders
  moves only between them. Planned in CONCEPT 7.5 already.
- **`identities`**: which sender identities of an account a send may use,
  null for every one (IDEAS). Waits for identities in the account model.

A constraint applies per grant, as today: a call passes when one grant
that allows it accepts everything about the call.

### 8.6 An audit of administration

Sends have an audit in the database. Sign-ins and changes to users,
roles, tokens, passwords, accounts and webhooks have only the service
log, which a container may drop. The proposal: one table `events` with
time, user, credential, operation, the record touched, the client
address and the outcome. Never a secret, never content. Written by the
domain services where the log lines are written today.

- `GET /v1/audit`, right `audit` on the service (a service right, so
  `audit` appears in both lists), paged newest first, filters by user,
  operation and day.
- UI: a card **Recent activity** on the user's page with its own events,
  and a page **Audit** under Service for `users.read`.
- Kept for `MAILBOX_SERVICE_AUDIT_DAYS` days, 90 by default.

### 8.7 Roles to start from

Most deployments need the same four roles. The UI's **New role** page
offers them as templates, not stored until saved and changed at will:

| Template | Grants |
|---|---|
| Reader | `mail.read` on chosen accounts |
| Assistant | `mail.read`, `mail.write`, `drafts` on chosen accounts. What the MCP server needs to sort and draft, without sending |
| Sender | `send` with `recipients` required and a daily limit, on chosen accounts |
| Operator | `accounts.manage`, `audit` on every account, `accounts.connect` and `webhooks.manage` in service |

The API gets nothing new: a template is a filled form.

### 8.8 `/v1/me` names the sending limits

Per account the caller may send from, the recipients and the daily
limit of each grant that allows it, and how many sends are left today.
The MCP server tells the model before it tries, and the UI's overview
shows the person what its own token may send. IDEAS has the shape.

## 9. Order of work

1. This file, one pull request of documentation. CONCEPT 7.5 and the
   roadmap point here.
2. 8.3, the last administrator: small, no schema change.
3. 8.1 and 8.2 together: schema, migration, model, API, OpenAPI, editor,
   tests, live check. The largest step, and the one the others build on.
4. 8.8 and 8.4, both small once 8.1 is in.
5. 8.6, the audit: schema, domain, API, two pages.
6. 8.7, the templates: UI only.
7. 8.5, the constraints, when identities exist and folders are asked for.

Every step keeps the existing tests green, adds its own and, where a
page changes, a walk in `live/ui.py`.

## 10. Open questions

- 8.1: should the creator of an account get `accounts.manage` on it, or
  nothing until an administrator grants it?
- 8.3: refuse the change, or allow it and warn on the overview until it
  is repaired?
- 8.6: is 90 days the right default, and does the audit page belong
  under Service or on the overview?
- 8.7: are four templates enough, and are their names right?
- Is a grant per user still wanted at all, or should every right come
  through a role? Grants per user keep small deployments simple, roles
  keep large ones honest. The proposal keeps both.
