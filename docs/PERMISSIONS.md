# Users, roles and rights

Proposal of 2026-09-27, section 8 decided on 2026-10-05. One place for
the whole model: who may do what, how that is written down, checked and
shown, and what should change.
[CONCEPT 7.5](CONCEPT.md#75-users-permissions-and-authentication) keeps
the record of decisions and the details of credentials. [UI.md](UI.md)
says how the pages look. This file says how the rights work, as they are
today (sections 1 to 7), and the changes of section 8, which are built
but `identities` of 8.5. What the user decides is marked as decided,
everything else is the proposal.

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
| **Grant** | rights on accounts, with constraints: `{accounts, allow, recipients, max_sends_per_day, folders, expires_at}` | part of a user or a role |
| **Service rights** | rights of the service, bound to no account: `{service: [...]}` | part of a user or a role |
| **Role** | a named, reusable set of grants and service rights | `/v1/roles`, UI Roles |
| **Constraint** | a narrowing of a grant that changes no right: which recipients, how many sends a day, which folders, until when | part of the grant |
| **Effective rights** | the union of a user's rights and those of its roles | `/v1/me`, the user's page |

## 3. The catalogue

The groups as `domain/rights/permissions.py` holds them today:

| Group | Rights | Bound to |
|---|---|---|
| `accounts.read` | `list_accounts`, `get_account`, `get_status` | an account |
| `mail.read` | `list_all_messages`, `list_folders`, `list_messages`, `get_message`, `get_message_raw`, `get_attachment`, `list_changes`, `list_all_changes` | an account |
| `mail.write` | `update_message`, `delete_message` (to the trash), `batch_messages`, `create_folder`, `update_folder` | an account |
| `mail.delete` | `delete_message_permanent`, `delete_folder` | an account |
| `drafts` | `list_drafts`, `create_draft`, `update_draft`, `delete_draft` | an account |
| `send` | `send_message`, `send_draft` | an account |
| `audit` | `list_sends`, `list_all_sends` | an account |
| `audit` | `list_activity`, the audit of administration (8.6) | the service |
| `accounts.manage` | `update_account`, `delete_account`, `verify_account` | an account |
| `accounts.connect` | `discover_account`, `start_device_oauth`, `poll_device_oauth`, `create_account` | the service |
| `webhooks.manage` | `list_webhooks`, `get_webhook`, `create_webhook`, `delete_webhook` | the service |
| `users.read` | `list_users`, `get_user`, `list_tokens`, `get_second_factor`, `list_roles`, `get_role` | the service |
| `users.manage` | `users.read` and changes to users, tokens, passwords, roles: fourteen rights | the service |
| `admin` | everything, and `show_recovery_key` and `read_service_log`, which nothing else gives | the service |

Two kinds of right, kept in two lists of a user or a role (8.1):

- **Rights on accounts** act on one account. A grant names them in
  `allow`, and names the accounts, `*` for every account, also those
  added later.
- **Rights of the service** act on no account: `accounts.connect`,
  `users.read`, `users.manage`, `webhooks.manage`, `audit` and `admin`,
  or single operations of them. They are named in `service`. A name in
  the wrong list answers `400`.
- `audit` is in both lists. In a grant it reads the sends of the
  accounts, in `service` the audit of administration (8.6).
- Whoever connects an account gets `accounts.manage` on it, unless it
  holds that there already.

Two operations are open to every user: `get_me` and `list_permissions`.

## 4. How a right is resolved

- **Effective rights** are the union of the user's grants and service
  rights and those of its roles. A role is a name for grants, nothing more. A right
  unknown to the catalogue, for example one renamed since the grant was
  written, grants nothing and is logged. It never locks anyone out.
- **Per request**: credential, then user, then the route's right and the
  account from the path against the effective rights. A batch is checked
  per action: `batch_messages` and the right of the single action.
- **Cross-account operations filter.** `list_accounts`, `/v1/messages`,
  `/v1/changes` and the UI's mail page show the accounts the user has a
  right on, and leave the others out.
- **Folders.** Where every grant that allows an operation on mail names
  `folders`, the call keeps to them: folders listed and their
  subfolders, by role, name or id. On an IMAP server that keeps every
  folder below the inbox (`INBOX.Sent`), the folders right below it are
  at the top, as mail clients show them. A message or folder outside answers
  `404`, a move or a new folder outside answers `403`. Lists, the change
  feed and webhooks leave out what is outside. A change keeps the folder
  it happened in. A deletion whose folder is unknown, made before the
  folder was kept or in an account without an index, goes to everyone
  who may read the account: it names an id and nothing else.
- **Not seen, not there.** An account outside every grant answers `404`.
  An account inside a grant, but without the right asked for, answers
  `403` and names the missing right.
- **`/v1/me`** answers who the caller is, every account it may act on
  with the operations there and the limits of each grant that allows
  sending, with the sends left, the operations of the service, and a
  warning per account the caller may read mail in and send it anywhere
  from. The MCP server builds its tools from it. The UI's overview and
  user page show the same in words.

## 5. Delegation

A user with `users.manage` administers users, and the model keeps that
from becoming a way up:

- **Hands out only what it holds.** Every grant given, directly or
  through a role, must be covered by the giver's own effective rights, on
  the same accounts. A send right is covered only by a send right of the
  giver with recipients and a limit at least as narrow. A grant of the
  giver that expires covers only a grant that expires no later.
- **Manages only whom it covers.** Changing, deleting, giving a token or
  a password to a user needs the giver to cover that user's effective
  rights. A token or a password for another user means signing in as
  that user, so it is bound by the same rule.
- **A role is changed only by someone who covers it** and every user
  who holds it, since every holder gains what is added and loses what is
  taken. A role in use cannot be deleted.
- **Nobody locks itself out.** A user cannot delete or disable itself
  and cannot take its own UI sign-in.
- **The recovery key and the service log are `admin` only**, the key
  after the password again.

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
- A second factor for UI users, TOTP, since 2026-10-09
  ([AUTHENTICATION.md](AUTHENTICATION.md)). Later a passkey, OAuth
  client credentials for machines (IDEAS). New credential kinds, the same
  rights.

## 7. Where the model shows

- **API**: `x-permission` on every operation, `/v1/me`,
  `/v1/permissions`, the user and role resources, `403` naming the right.
- **UI**: the editor with the service rights as tick boxes and single
  rights in a text field, and a row per grant: accounts as tick boxes,
  groups as tick boxes with their rights as a hint, single rights in a
  text field, recipients, the daily limit, the folders and "Valid
  until". The user's page shows the
  effective rights per account, the sending limits and the warning
  "reads and sends anywhere". Pages and buttons appear only for those
  with the right.
- **MCP server**: at start `/v1/me` decides which tools exist.
  `list_accounts` names the limits on sending per account, and warns of
  an account where the token may read mail and send it anywhere, since a
  mail with injected instructions could carry data out through it.
- **Audit**: sends in the database (`/v1/accounts/{id}/sends`,
  `/v1/sends`, UI Sends). Sign-ins and changes to users, roles, tokens,
  passwords, accounts and webhooks in the audit of administration
  (`/v1/audit`, UI Audit and the card Recent activity, 8.6), and in the
  service log.

## 8. What should change

Eight changes. The first two change the model, the rest add to it.
None removes a right anyone holds. **Decided 2026-10-05:** 8.1 to 8.5,
8.7 and 8.8 as below, with the answers of section 10. 8.6 followed on
its own, with the answers of AUDIT.md section 7. All of it is built but
`identities` of 8.5.

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
  `webhooks.manage`, `accounts.connect`, `audit` (8.6) and `admin`. No
  accounts, no constraints.
- `grants` names account-bound rights, as today. `accounts.manage` keeps
  `update_account`, `delete_account`, `verify_account` and signing in
  again, all about one account.
- `accounts.connect` is a new group of `discover_account`,
  `create_account` and `start_oauth`, and for sign-in with a code
  `start_device_oauth` and `poll_device_oauth` (`start_oauth` went with
  its route on 2026-10-07: the sign-in in a browser is the UI's, and a
  sign-in needs `create_account` or `update_account`). Whoever connects an
  account holds its password for a moment and needs a grant on it
  afterwards: the creator gets `accounts.manage` on the new account, and
  nothing else, so it can verify and remove what it connected. Mail
  rights on it are given as on any account. **Decided 2026-10-05.**
- `admin` in `service` means every right, as today. `admin` in a grant's
  `allow` is no longer accepted. **Decided 2026-10-05:** a request that
  names a service right or `admin` in a grant's `allow` answers `400`
  and says it belongs in `service`. Nothing is rewritten silently.
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
| `users.read` | `list_users`, `get_user`, `list_tokens`, `get_second_factor`, `list_roles`, `get_role` |
| `users.manage` | `users.read` and `create_user`, `update_user`, `delete_user`, `create_token`, `revoke_token`, `set_password`, `remove_second_factor`, `remove_factor_device`, `create_role`, `replace_role`, `delete_role` |

Migration: none, `users.manage` keeps every right it had.

### 8.3 The last administrator stays

Today a user cannot delete or disable itself. It can still take its own
`admin` away, and one administrator can disable the other, until nobody
is left who may sign in to the UI and repair it. The way back is then
the host: `users set-password`. The proposal: the service refuses a
change that would leave no enabled user with `admin` and `ui_sign_in`,
with `409` and a message that says so. The host command stays as the
last resort. **Decided 2026-10-05:** refused, not allowed with a
warning.

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
  **Decided 2026-10-05:** a listed folder includes its subfolders, so
  `Invoices` covers `Invoices/2026`. Deleting to the trash stays allowed
  under `mail.write` with folders. Reading the trash needs it in the
  list. Deleting for good stays a right of its own.
- **`identities`**: which sender identities of an account a send may use,
  null for every one (IDEAS). Waits for identities in the account model.
  **Decided 2026-10-05:** not built now.

A constraint applies per grant, as today: a call passes when one grant
that allows it accepts everything about the call.

### 8.6 An audit of administration

Sends have an audit in the database. Sign-ins and changes to users,
roles, tokens, passwords, accounts and webhooks have only the service
log, which a container may drop. The proposal: one table `activity` with
time, user, credential, activity, the record touched, the client
address and the outcome. Never a secret, never content. Written by the
domain services where the log lines are written today. The design in
full, which activities, which fields, storage, API and page, is
[AUDIT.md](AUDIT.md); the activities themselves are those of
[LOGGING.md](LOGGING.md) section 5.

- `GET /v1/audit`, right `audit` on the service (a service right, so
  `audit` appears in both lists), paged newest first, filters by user,
  activity (a name or its area), record, and time with `after` and
  `before`.
- UI: a card **Recent activity** on the user's page with its own
  activities, and a page **Audit** under Service, both for `audit`
  in `service`.
- Kept for `MAILBOX_SERVICE_AUDIT_DAYS` days, 90 by default. The
  setting exists since 0.2.0 for the audit of sends.

### 8.7 Roles to start from

Most deployments need the same four roles. The UI's **New role** page
offers them as templates, not stored until saved and changed at will:

| Template | Grants |
|---|---|
| Reader | `mail.read` on chosen accounts |
| Agent | `mail.read`, `mail.write`, `drafts` on chosen accounts. What the MCP server needs to sort and draft, without sending |
| Sender | `send` with `recipients` required and a daily limit, on chosen accounts |
| Operator | `accounts.manage`, `audit` on every account, `accounts.connect` and `webhooks.manage` in service |

The API gets nothing new: a template is a filled form. **Decided
2026-10-05:** these four, the second named Agent.

### 8.8 `/v1/me` names the sending limits

Per account the caller may send from, the recipients and the daily
limit of each grant that allows it, and how many sends are left today.
The MCP server tells the model before it tries, and the UI's overview
shows the person what its own token may send.
**Decided 2026-10-05:** the MCP server's `list_accounts` names the limits
and the warning about reading and sending anywhere, so the model knows
them before it sends.

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
page changes, a walk in `live/ui.py`. **Decided 2026-10-05:** steps 2,
3, 4, 6 and 7 on one branch, a commit per step, one pull request. Step 5
follows on its own branch.

Steps 2, 3, 4, 6 and 7 were one pull request and step 5 one of its own:
all seven are done but `identities` of step 7, which waits for
identities in the account model.

## 10. Questions answered

- **Decided 2026-10-05:** the creator of an account gets
  `accounts.manage` on it (8.1).
- **Decided 2026-10-05:** a change that would leave no administrator is
  refused (8.3).
- **Decided 2026-10-05:** four templates, Reader, Agent, Sender and
  Operator (8.7).
- **Decided 2026-10-05:** grants per user stay beside roles.
- **Decided 2026-10-05:** the audit of 8.6 keeps its records 90 days
  by default, its page is under Service, and `audit` in `service` reads
  it. The rest of its answers are in [AUDIT.md](AUDIT.md) section 7.
