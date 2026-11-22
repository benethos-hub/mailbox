# Roadmap: phases 5 and 5a

Part of the [roadmap](../ROADMAP.md): phase 5, in progress, and phase 5a, done.

## Phase 5 – More providers and the configuration UI

**In progress.** What is done is listed first, what is open at the end.

- **`microsoft` adapter over Graph with OAuth (5.4)**, done: folders,
  list and search, messages, attachments, flags, move, delete, drafts
  and sending, with immutable ids. The project's own app is the
  default, a public client without a secret. An app of the deployment's
  own stays the option. A person signs in in the browser (UI) or with a
  code (UI and API). `MAILBOX_SERVICE_PROVIDERS` names the kinds of
  account a deployment offers. Live-checked in `live/microsoft.py`
  - decided 2026-09-25: tenant `common` by default, the callback at
    `/ui/oauth/{provider}/callback` (CONCEPT 5.4)
  - decided 2026-10-06: one app per deployment, both ways to sign in
    offered, the kinds of account in `MAILBOX_SERVICE_PROVIDERS`
    (CONCEPT 5.4)
- **`gmail` adapter with OAuth, own Google Cloud client per deployment
  (5.5)**, built: the client in the settings, the sign-in in the
  browser only, labels as folders with "All Mail", flags, moves,
  trash and delete for good, drafts, sending, the search filter as a
  Gmail query (`docs/mailbox-service/GOOGLE.md`). Checked live against a Gmail account
  (`live/gmail.py`)
- **Gmail history in the worker**, built: `history.list` since a
  history id, polled
- **A second factor for the UI sign-in, TOTP with recovery codes
  ([AUTHENTICATION.md](../mailbox-service/AUTHENTICATION.md))**, decided 2026-10-09, done:
  schemas 18 and 19, the code after the password, up to ten named devices on
  the page Second factor with a QR code, added, renamed and removed by
  the owner, removed by a user with `users.manage` and all at once by
  `users reset-second-factor` on the host, the devices in the API.
  Live-checked in `live/ui.py`. Decided 2026-10-09: several devices
  per user, a further one and new recovery codes after a code, one set
  of recovery codes, the second factor a frame and TOTP its first
  method
- **Passkeys, the second method of the second factor
  ([AUTHENTICATION.md](../mailbox-service/AUTHENTICATION.md) 3.2)**, decided 2026-11-18,
  done: schema 23, WebAuthn with `fido2` behind
  `data/secrets/passkeys.py`, a passkey after the password and in place
  of a code, the card Passkeys, `remove_passkey` in the API and both
  clients. Checked in Chromium by the browser suite, with its virtual
  authenticator
- **The UI rework of 2026-10 ([UI.md](../mailbox-service/UI.md) 10)**, decided 2026-10-09,
  done: an icon sprite of its own, dialogs before a change, copy
  buttons beside every secret shown once, the sidebar folding to icons,
  the Status page gone into the overview and the Accounts list, actions
  in the row of a list, the user page in tabs with the grant editor in
  lines, and webhooks changeable (`update_webhook`,
  `renew_webhook_secret`). Live-checked in `live/ui.py`
- **`jmap` adapter for Fastmail and JMAP servers (5.6)**, decided
  2026-10-06, done: a password or an API token, sending through JMAP,
  changes since a state and push through the event source. Discovery
  asks `/.well-known/jmap` and SRV, JMAP before IMAP. Checked against
  Stalwart (`live/jmap.py`)
- Configuration UI under `/ui` (1.1), brought forward on 2026-09-24:
  - **frame: server-side session, CSRF, security headers, layout**, done
  - **accounts: connect through autodiscovery or by hand, change, verify,
    remove**, done
  - **users, roles and their grants, tokens**, done
  - **reading mail: every inbox, folders, search, a message, attachments**,
    done
  - **writing: flags, moving, deleting, folders, compose, reply, forward,
    drafts, sending**, done
  - **the audit of sends**, done
  - **the service log: every line on stderr with time, level and source,
    each secret masked, the newest 1000 on a page for the admin (UI
    6.5, CONCEPT 7.4)**, done, live-checked in `live/ui.py`
  - **the service log activity by activity ([LOGGING.md](../mailbox-service/LOGGING.md))**,
    done: every line an activity of `domain/activity/catalogue/`, one
    module per area, the MCP server's lines described in LOGGING.md as
    well, and the HTTP
    request limit with every limit a setting ([LIMITS.md](../mailbox-service/LIMITS.md))
  - **the audit of administration of [AUDIT.md](../mailbox-service/AUDIT.md)**, decided
    2026-10-05 (PERMISSIONS.md 8.6), done: the table `activity`,
    `GET /v1/audit` with `audit` in `service`, the Audit page and the
    Recent activity card
- **Threads (6.3)**, decided 2026-10-12, done: IMAP
  messages carry the `thread_id` the index keeps, built across folders
  from `Message-ID`, `In-Reply-To` and `References`. Gmail, JMAP and
  Microsoft read their own. `GET .../threads` (`list_threads`) and
  `GET .../threads/{thread_id}` (`get_thread`) in `mail.read`, both on
  the Python client, the MCP tool `get_thread`, and in the UI a folder
  listed by conversations, the page of a conversation and the card of
  the others below a message. Threads across accounts come later
- **Users, roles and rights: the changes of
  [PERMISSIONS.md](../mailbox-service/PERMISSIONS.md) section 8**, decided 2026-10-05,
  done: the last administrator stays (8.3), service rights apart from
  grants and `users.read` (8.1, 8.2), sending limits in `/v1/me` and
  grants that expire (8.8, 8.4), role templates (8.7), the grant
  constraint `folders` (8.5), the audit of administration (8.6) on its
  own branch. `identities` (8.5) waits for identities in the account
  model
- **The API and the UI show the same data**, decided 2026-10-06, done:
  the UI's filters of sends, users, accounts and webhooks at the API with
  the same query names, a user's sign-in to the UI in `UserInfo`,
  keywords in the UI, and `GET /v1/status` with `get_status` in
  `accounts.read`
- **Metrics for Prometheus (6.1)**, decided 2026-11-22, done:
  `GET /v1/metrics` with `get_metrics`, a right of the service in the
  group `metrics`, on unless `MAILBOX_SERVICE_METRICS=false`. An account
  by its id, provider and status, never its address or the text of an
  error. Not in the MCP server
- **Paging for the lists that answered everything at once (6.6)**,
  decided 2026-10-06, done: accounts and users, in the API and the UI,
  with one generic pager for lists held whole. Roles, tokens, webhooks
  and folders stay one list
- **The worker takes up an account at once (6.5)**, decided 2026-10-06,
  done: connected, changed or verified, it is synced and watched
  without waiting for the next round
- **`pop3` adapter (5.2)**, decided 2026-10-06, done: one inbox, read
  and deleted for good, polled by the sync. Accounts and `/v1/me` name
  their capabilities, the UI and the MCP server go by them. Discovery
  offers POP3 only where no IMAP is
- **The layout of the code ([REFACTORING.md](../REFACTORING.md),
  [ARCHITECTURE.md](../mailbox-service/ARCHITECTURE.md))**, done: the domain and the data
  layer in packages by area, the change feed as typed classes like the
  activities, `assembly/` and `cli/`, the adapters in parts behind one
  protocol per ability, the code written twice merged into helpers,
  the MCP server's tools one module per kind, the client's endpoints
  one module per resource, the limits on the size of the code, and the
  tests in folders like the source
- **Settings and data in the folders of the operating system, for a
  service installed without the repository (7.4)**, decided 2026-10-06,
  done: `%LOCALAPPDATA%` on Windows, `~/.config` and `~/.local/share`
  on Linux (`platformdirs`). A file named with `--env-file` and the
  repository's folders stay first, `paths` names what applies. The key
  file never in the data folder (7.3). The MCP server reads an optional
  `.env` alike
- **Containers in operation (8.1)**, decided 2026-10-06, done:
  `containers/production/` runs the published images with a fixed
  version, Caddy for HTTPS as a profile, `setup.sh` for the first start.
  The MCP server runs with each client, an instance per client. `containers/` holds `images/`, and `development/`,
  `production/` and `test-mail-server/` each with its own `secrets/`
- **MCP server instances and certificates in operation (8.1)**, decided
  2026-10-06, done: instances beside the service from the template
  `mcp.yaml` with the profile `mcp`, reached on `127.0.0.1` or through a
  route of Caddy each. `MAILBOX_TLS` picks Let's Encrypt, Caddy's CA or
  a certificate of your own
- **Hardening before 0.3.0**, decided 2026-10-07, done: a change and its
  audit record in one transaction (AUDIT.md 4), backups in blocks of
  1 MiB as format 2 (7.8), line breaks refused before the IMAP, POP3 and
  SMTP commands and kept out of the log, the address, hosts and display
  name of an account checked, the worker's notes of a deleted account
  dropped, and every broad `except` checked by a test
- **The Python client as a package of its own (8.2)**, decided
  2026-10-07, done: `mailbox-client`, each endpoint described once, an
  async and a sync client over it. The MCP server is built on it
- **The client covers the whole API**, decided 2026-10-09, done: the
  records in `models/` one module per resource
  ([REFACTORING.md](../REFACTORING.md) 14), each method one line made from
  its endpoint, every operation of `docs/mailbox-service/openapi.json` a method of both
  clients named like its `operationId`, held by a test. Only
  `get_linked_attachment` has none: its URL is the credential. A secret
  shown once comes as a `Secret`. The live checks administer through it
  (`live/checks/admin.py`, `accounts.py`, `live/register.py`)
- **A fourth package, `mailbox-common` ([REFACTORING.md](../REFACTORING.md)
  15)**, decided 2026-10-09, done: what the service and the MCP server
  both need, held once. The MCP server's log is the service's, with
  colours and masking. It holds the settings base of both,
  the client answers records for messages, and a test holds every
  package boundary to named records ([REFACTORING.md](../REFACTORING.md)
  16)
- **The MCP server in the MCP Registry and as a Claude Desktop
  extension (8)**, decided 2026-10-10, done: the entry
  `io.github.benethos-hub/benethos-mailbox-mcp` names the PyPI package
  and the extension `benethos-mailbox-mcp.mcpb`, which every release
  carries. Both ask for the token alone, the address and plain http
  are optional. `.github/publish/` holds the entry and the manifest,
  each held by a test. `publish.yml` builds the extension after the
  PyPI upload and publishes the entry last
- **The mail tools close their gaps to the API**, decided 2026-10-12,
  done: labels and keywords added and taken off (the API gained
  `add_`/`remove_` lists), a reply without the quote and a forward as a
  file, `reply_to`, attachments as base64 and of other mail (the API
  gained `attachments_from`), the tool `update_folder`, and how each
  account fares in `list_accounts` (the API's `/v1/me` gained it)
- **A link to an attachment for another service (6.3)**, decided
  2026-10-15, done: `share_attachment` in the API, the client and the
  MCP server, the group `mail.share`, and `GET /v1/links/{secret}`,
  which hands the file out once, without a token
- **The MCP server follows its token's rights while it runs (7.5)**,
  decided 2026-10-16, done: it asks `/v1/me` every
  `MAILBOX_MCP_RIGHTS_SECONDS` and sends `notifications/tools/list_changed`
- **The MCP tool `server_status`, always offered (7.5, 8)**, decided
  2026-10-29, done: the server's version, transport, Python, MCP library
  and uptime, with `details` the service as the server last saw it, its
  version from `/health`. Live-checked in `live/mcp_stdio.py` and
  `live/mcp_http.py`
- **A catalogue of the MCP server's tools without a service (8)**,
  decided 2026-11-09, done: `MAILBOX_MCP_CATALOGUE=true` lists every
  tool and refuses every call but `server_status`, and `--list-tools`
  prints the tools as a client lists them, kept in
  `docs/mailbox-mcp/mcp-tools.json`
- **The sender check of a message (6.3)**, decided 2026-11-18, done:
  `sender_check` from the receiving server's `Authentication-Results`,
  in the API, the client, the MCP server and the UI, for every kind of
  account. For IMAP, POP3 and JMAP a person names the receiving server
  in `settings.authserv_id`. `GET /v1/accounts/{account_id}/server-names`
  and **Look in the mailbox** on the account page list the names of the
  newest ten mails, with how often each is on top. Live-checked in
  `live/smoke.py`

Open in this phase, each planned in CONCEPT.md:

- Microsoft changes by push, with change-notification subscriptions
  (5.4). The worker polls delta queries today
- the discovery sources 6 to 8: Microsoft's realm, SRV records and
  guessing (5.8)
- the token refresher for SASL XOAUTH2 on IMAP and SMTP (5.1)
- `keys rotate` (7.3) and scheduled backups (7.8)
- the integration job against the test mail server in the CI (10)
- threads across accounts (6.3)

## Phase 5a – One way to operate every mailbox

**Done.**

Decided 2026-10-12 (5.11). Every mailbox is operated the same way,
and what an account cannot do answers `501`, announced by its
capabilities ([UNIFORM.md](../mailbox-service/UNIFORM.md)). Delivered: the finer
capabilities, read from the server and stored with the account. `date`
and `received`. The inbox as the list without a folder, and the role
`all`. Server notes out of `keywords`, and the two lists of marks. One
test suite for all adapters. A UI and an MCP server that know no
providers.

All of it shipped in 0.5.0, the changes of the contract marked as
breaking in the changelog. One rule changed
later: a replacement list `keywords` keeps the marks a message has
(UNIFORM 3, decided 2026-10-28), shipped in 0.6.0 as a breaking change.
