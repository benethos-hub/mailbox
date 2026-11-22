# Concept: the API for accounts, folders and messages

Part of the [concept](../CONCEPT.md): sections 6 to 6.3.

## 6. REST API

Base path `/v1`, JSON, bearer authentication on everything except
`/health` and `GET /v1/links/{secret}`, the link to an attachment
(6.3). `{acc}` stands for `/v1/accounts/{account_id}`.

### 6.1 Accounts

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/accounts` | list, paged by address (6.6) |
| POST | `/v1/accounts` | create with credentials (IMAP, POP3 and SMTP with a password or app password, JMAP with a password or an API token), connection is tested first. OAuth accounts connect through the sign-in routes below |
| GET | `/v1/accounts/{account_id}` | get, including `status`, `capabilities`, `marks` and `operations` |
| PATCH | `/v1/accounts/{account_id}` | display name, settings, new credentials |
| DELETE | `/v1/accounts/{account_id}` | remove, credentials deleted |
| POST | `/v1/accounts/{account_id}/verify` | test the connection now |
| GET | `/v1/accounts/{account_id}/server-names` | the names receiving servers wrote into the newest ten mails of the inbox, each with how many mails carry it and in how many it is the topmost entry, for choosing `settings.authserv_id` (6.3). Empty for Gmail and Microsoft. Needs `update_account` |
| POST | `/v1/oauth/{provider}/device` | sign in with a code (5.4): the code, the page to enter it at and a `sign_in_id`, to connect an account or, with `account_id`, sign it in again |
| POST | `/v1/oauth/{provider}/device/{sign_in_id}` | poll the sign-in with a code: `connected` false until the person signed in, then the account, no sooner than its `interval` |
| GET | `/ui/oauth/{provider}/callback` | where the provider sends the browser back after the UI's sign-in in a browser: a UI page, not part of the API. The person is signed in to the UI as the user who started. The account is created or signed in again |
| POST | `/v1/discovery` | autodiscovery from the email address alone: adapter, servers, credential kind, hints (5.8) |
| GET | `/v1/status` | the sync worker and the accounts the caller may see the status of, as the UI's overview and Accounts list show them. Nothing is asked of a provider |
| GET | `/v1/metrics` | the same state for Prometheus, in its text format, of every account, without an address or the text of an error. Needs `get_metrics` |

**Decided 2026-10-06, the status at the API:** `get_status` in
`accounts.read`, for the accounts the caller may list. The worker names
how many accounts it watches, never which. Webhooks are not part of it:
`GET /v1/webhooks?failing=true` names the failing ones. The MCP server
has no tool for it.

**The metrics.** `GET /v1/metrics` hands the same state to Prometheus,
as figures: the worker, the accounts by status and how many need a
look, each account with its status, whether it needs a look, whether a
pass syncs it, its last pass that succeeded and how many did, and the
webhooks of every user with how many fail. An account is named by its
id, its provider and its status. Its address, its name and the text of
an error never go out, nor the URL of a webhook. A point in time that
does not exist yet, such as the last round before the first, is no
series, never 0. A deleted account is gone from the next answer. The
figures live in memory and start again after a restart. The route
answers `404` while `MAILBOX_SERVICE_METRICS=false`. Three alerts on the
figures come with the service: the command `alert-rules` prints them. How
to scrape it and load them: [containers/production/README.md](../../../containers/production/README.md#monitoring-with-prometheus).

**Decided 2026-11-22:** a right of its own, `get_metrics`, a right of
the service, since `GET /v1/status` hands out the address and the text
of the last error. The path is `/v1/metrics`. The count of failing
webhooks is part of it. The format comes from `prometheus_client`. The
MCP server gets no such endpoint.

### 6.2 Folders

| Method | Path | Purpose |
|---|---|---|
| GET | `{acc}/folders` | list |
| POST | `{acc}/folders` | create |
| PATCH | `{acc}/folders/{folder_id}` | rename, move |
| DELETE | `{acc}/folders/{folder_id}` | delete |

Rules of the implementation (phase 2):

- A new folder goes into the user's personal namespace (RFC 2342), e.g.
  below `INBOX.` where the server keeps every folder there. It is
  subscribed, since Outlook and other clients list only subscribed
  folders. Renaming moves the subscription along, deleting drops it.
- Folders with a role (inbox, sent, trash, ...) are neither renamed nor
  deleted: `409`. `RENAME INBOX` would move the inbox's messages.
- Only an empty folder without subfolders is deleted, otherwise `409`: on
  many servers `DELETE` takes the messages inside with it.
- On IMAP a folder's id follows its name and changes when it is renamed.
  The messages inside keep their ids: a sync follows them at once (4.1).

### 6.3 Messages

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/messages` | list and search **across accounts** (6.6) |
| GET | `{acc}/messages` | list and search in one account (6.6) |
| GET | `{acc}/messages/{message_id}` | full message, text and HTML body |
| PATCH | `{acc}/messages/{message_id}` | `unread`, `starred`, `keywords`, `folder_ids` (a move is a change of `folder_ids`), `add_keywords`, `remove_keywords`, `add_folder_ids`, `remove_folder_ids` |
| DELETE | `{acc}/messages/{message_id}` | to trash, `?permanent=true` expunges |
| GET | `{acc}/messages/{message_id}/raw` | RFC 822 source (`message/rfc822`) |
| GET | `{acc}/messages/{message_id}/attachments/{attachment_id}` | attachment content, with its type and file name |
| POST | `{acc}/messages/{message_id}/attachments/{attachment_id}/links` | a link to the attachment for another service (`share_attachment`): its URL, when it ends, the type, size and file name |
| GET | `/v1/links/{secret}` | the attachment a link hands out, once, without a token (`get_linked_attachment`) |
| POST | `{acc}/messages/batch` | bulk `update` / `delete` for up to 100 ids, per-id result. A move is an `update` of `folder_ids` |
| GET | `{acc}/threads` | the threads of a folder (`folder`, required), each where its newest message in the folder is |
| GET | `{acc}/threads/{thread_id}` | a thread with its message summaries in every folder, oldest first |

**Decided 2026-09-24, changing messages:**

- `PATCH` answers the changed message as a summary, with the same id.
- No change puts a message into the drafts folder: a `PATCH` or a batch
  that names it answers `400`, for every caller. The draft routes would
  take such a message for a draft.
- Moving needs `MOVE` or `UIDPLUS` on an IMAP server. Without both, a move
  would have to expunge the whole folder, other clients' deleted messages
  included, so the account lacks `move` and a move answers
  `501 not_supported`.
- `DELETE` without a folder with the trash role answers `501`: the account
  lacks `trash`. It never deletes for good instead.
- Permanent deletion is the right `delete_message_permanent` in the group
  `mail.delete`, so it can also be granted on its own.

A message already in the trash answers `DELETE` without `permanent` with
`409`: otherwise two calls with `mail.write` would delete for good what
needs `mail.delete`. Deleting for good needs `UIDPLUS` on an IMAP server,
for the same reason as a move. On Microsoft, Graph's delete of a message
outside Deleted Items only moves it there, so the adapter moves the
message into the trash and deletes it from there. A deleted or replaced
draft goes the same way.

`keywords` follow JMAP (RFC 8621): `$answered`, `$forwarded`, `$draft` and
the provider's own keywords as they are. `\Seen` and `\Flagged` are
`unread` and `starred`. A `PATCH` with `keywords` replaces the list.
A mark the message has, such as `$answered`, stays until
`remove_keywords` names it (decided 2026-10-28, UNIFORM.md 3). A mark in
the list needs to be among the account's `marks.written`.

**Decided 2026-10-12:** keywords and folders are also added and taken off,
in the API rather than in the MCP server, so that a batch of messages
with different labels keeps the rest of each. `add_keywords` and
`remove_keywords` change the keywords a message has, `add_folder_ids` and
`remove_folder_ids` its folders, each list by id or by role. They go
beside the list they change, not with it. Folders are added and taken off
only where a message can be in several (`labels`: Gmail, JMAP), and a
message keeps one folder at least. Elsewhere a message is moved with
`folder_ids`.

**Decided 2026-09-24, threads for IMAP:** IMAP's `THREAD` extension
(RFC 5256) works within one folder only, while a conversation is spread
over the inbox, the sent folder and the archive. The service builds IMAP
threads itself, across all folders, from `Message-ID`, `In-Reply-To` and
`References` in the id mapping (4.1).

**Decided 2026-10-12, threads:** A thread lives in one account. Threads
across accounts come later. For IMAP only the headers tie messages
together, never the subject. When a late message ties two threads
together, the younger one goes into the older one. Its id answers `404`
from then on, and its messages show as updated in the change feed. POP3
answers `501`. A thread lists at most 500 messages, and of the
`References` of a message the last 20 count. Both are settings. The MCP
server has `get_thread` alone, which takes a message id or a thread id.
The UI has a card with the conversation on the message page and a list
of the messages by threads.

**Decided 2026-10-16, a message without a thread:** where the index
keeps the threads (IMAP) and has none for a message yet, as when its
headers could not be read, the list of threads shows it as a thread of
its own under the message's id. That id finds the message alone, and
once the index has threaded it, the thread it is in.

**Decided 2026-10-15, links to attachments:** another service takes over
an attachment without the file passing through the model and without a
token of this service. The MCP server asks for a link, the model carries
only its URL across, and the other service fetches the bytes from this
service directly.

- The link is stored, not signed: a random secret of 128 characters,
  kept in the database as its digest only, as an API token is. No new
  key material.
- It holds once. A fetch that breaks off is not tried again: the model
  shares anew.
- It belongs to the API token that made it. When it is used, that
  token's rights are resolved anew, as if the token asked: the token
  valid and not revoked, its user enabled, a grant that still allows
  `get_attachment` and `share_attachment` on the account and the
  message. The request itself carries no `Authorization`: the secret is
  the credential.
- It holds `MAILBOX_SERVICE_LINK_SECONDS`, 120 by default, any value
  from 1 second on, without a ceiling. `share_attachment` may ask for
  fewer with `expires_in`, never for more: more answers `400`.
- Every refusal of `GET /v1/links/{secret}` is the same `404`, for an
  address locked out after failed sign-ins too, so the slowing down
  stays silent. A failure counts as a wrong token in the lockout per
  address. **Decided 2026-10-16:** where the mail server fails, the link
  holds, nothing counts, and the answer is `502 provider_unavailable`,
  so the other service tries again.
- `share_attachment` is the group `mail.share` of its own, in no role
  template ([PERMISSIONS.md](../PERMISSIONS.md) 8.7): a grant names it on
  purpose.
- The service logs the path of the route masked.

Two fetches at once have one winner: the link is marked used in the
transaction of its audit record, before its bytes are read. The limit
on requests answers there with the same `404` as well. The answer
carries `Cache-Control: no-store`.

#### The sender check

Every message carries `sender_check`: what the account's own receiving
server stated about the domain in `from`. The server writes it into the
header `Authentication-Results` (RFC 8601) when the mail arrives. It is
a fact about the sender's domain. It says nothing about the content.
The service reads it with each request and stores nothing. It hands out
no header as it stands, and no free text of a header reaches the API,
the log or an error.

**Decided 2026-11-18:**

- The strict line. `pass` means the account's own server confirmed the
  domain in `from`. In doubt the result is `unknown`.
- Exactly one entry under the own server's name counts. Two make it
  `unknown`. Entries under another name are passed over.
- Without a DMARC result, a DKIM or SPF pass counts where its domain
  equals the domain in `from`.
- For IMAP, POP3 and JMAP a person names the server at the account.
- ARC is not read.
- The field and the capability are named `sender_check`.
- The service, the Python client, the MCP server and the UI show it.

The fields: `result` is `pass`, `fail` or `unknown`. `domain` is the
domain the server checked, `matches_from` whether it is the one in
`from`, `method` one of `dmarc`, `dkim` and `spf`. `reason` says why
the result is `unknown`. The first row that applies counts:

| Situation | `result` | `domain` | `matches_from` | `method` | `reason` |
|---|---|---|---|---|---|
| The account names no receiving server | `unknown` | | | | `account` |
| No `Authentication-Results` under the own server's name | `unknown` | | | | `no_entry` |
| More than one under that name | `unknown` | | | | `several_entries` |
| The one cannot be read, or a domain in it is no host name | `unknown` | | | | `unreadable` |
| `dmarc=pass`, `header.from` equals the domain in `from` | `pass` | that domain | `true` | `dmarc` | |
| `dmarc=pass`, `header.from` missing or another | `unknown` | `header.from` where given | `false` | `dmarc` | `from_differs` |
| `dmarc=fail` | `fail` | `header.from` where given | the comparison | `dmarc` | |
| No DMARC result, `dkim=pass` for the domain in `from` (`header.d`, else the domain of `header.i`) | `pass` | that domain | `true` | `dkim` | |
| No DMARC result, `spf=pass`, the domain of `smtp.mailfrom` equals the domain in `from` | `pass` | that domain | `true` | `spf` | |
| No DMARC result, DKIM or SPF passed for another domain only | `unknown` | the other | `false` | `dkim` or `spf` | `other_domain` |
| No DMARC result, a `temperror` or `permerror` | `unknown` | | | | `error` |
| Anything else | `unknown` | | | | `no_proof` |

"No DMARC result" is any value but `pass` and `fail`, such as `none`,
`skipped` or `bestguesspass`. Domains are compared without case and
without a dot at their end. The organisational domain does not count.
The domain in `from` is that of its one address. `from` with no
address, several or one without a domain is `unreadable`. A domain
leaves the service only as a host name: ASCII letters, digits, dashes
and dots, 253 characters at most, in lower case. Only the header named
exactly `Authentication-Results` counts, never
`ARC-Authentication-Results` or `X-MS-Exchange-Authentication-Results`.

Where the server's name comes from:

- **IMAP, POP3, JMAP:** the account's setting `authserv_id`, one host
  name or more with commas, with a leading dot for every host below a
  domain. Without it the result is `unknown` with `account`, and the
  account lacks the capability `sender_check`. The account page shows,
  when asked, the names in the newest ten mails of the inbox with how
  many carry each. A server adds its entry on top (RFC 8601 section
  4.1), so the page and the route also count how often a name is the
  topmost entry, and put those most often on top first. A person takes
  one over. The service never sets it.
- **Gmail:** `mx.google.com`, for every account.
- **Microsoft:** `mx.microsoft.com`, for every account. Graph hands out
  the headers of a message only when asked, so a list asks for them as
  well. Measured for 21 mails: 313 KB instead of 25 KB between Graph and
  the service, in the same time.

What it cannot tell:

- Whoever names the server relies on it to remove entries under its
  name that a mail brings along (RFC 8601 section 5). Measured
  2026-11-18: the Stalwart of the test mail server keeps them in a mail
  a signed-in user submits.
- Where the server writes no entry, the topmost one is one the mail
  brought along.
- A domain that only looks like another, and a display name that names
  someone else, pass as long as the domain itself is confirmed.
