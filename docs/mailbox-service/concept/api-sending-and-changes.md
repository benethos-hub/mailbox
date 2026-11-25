# Concept: the API for sending, changes and lists

Part of the [concept](../CONCEPT.md): sections 6.4 to 6.8.

## 6.4 Sending and drafts

| Method | Path | Purpose |
|---|---|---|
| POST | `{acc}/send` | send. Body: recipients, `reply_to`, subject, text / html, attachments, `attachments_from`, optional `reference: {message_id, action: reply\|reply_all\|forward}`, optional `outbox` and `send_at` for the outbox. Header `Idempotency-Key` |
| GET | `{acc}/drafts` | list |
| POST | `{acc}/drafts` | create (same body as send) |
| PUT | `{acc}/drafts/{draft_id}` | replace, `keep_attachments` names stored attachments that stay. The answer names the draft's id from now on: IMAP keeps it, Gmail, Microsoft and JMAP store a new message under a new id (decided 2026-10-06). Where the old one cannot be deleted, the new one is taken back, and the error names it only where that fails too. IMAP without `UIDPLUS` answers `501` |
| DELETE | `{acc}/drafts/{draft_id}` | delete |
| POST | `{acc}/drafts/{draft_id}/send` | send a draft, `Idempotency-Key`. Optional body `outbox`, `send_at` for the outbox |
| GET | `{acc}/outbox` | the sends of the outbox, newest first, `state` narrows them |
| GET / DELETE | `{acc}/outbox/{job_id}` | one send of the outbox, cancel one that waits |
| GET | `{acc}/sends` | the audit of sends, newest first |
| GET | `/v1/sends` | the audit of sends of every account the caller may audit, or of those in `accounts`, newest first |

**Decided 2026-09-24, reply and forward:**

- After a reply the original gets the mark `$answered`, after a forward
  `$forwarded`, so other mail clients show it too: on IMAP the flag
  `\Answered` and the keyword `$Forwarded`. An account that does not
  write the mark (`marks.written`) leaves the original as it is, and the
  answer says so in `original_marked`.
- `reference.forward_as` chooses how a forward carries the original:
  `inline` (the default, as in common mail clients: quoted with its
  headers, its attachments attached) or `attachment` (the unchanged
  original as `message/rfc822`). Ignored for replies.

Rules of the implementation (phase 2): a reply without recipients goes to
the original's `Reply-To`, else its sender. `reply_all` adds everyone in
`To` and `Cc` except the account itself. Named recipients and a subject
win over these. `attachments_from` names attachments of other messages of
the account by message and attachment id. They are attached as they
are, before the message's own, and need `get_attachment` in a folder the
grants reach (decided 2026-10-12: by reference, so that a file does not
pass through the model). A `reference` needs `get_message` besides `send_message`:
a reply quotes the original and a forward passes it on, so a user who may
only send cannot get at mail this way. When the flag on the original
cannot be set, the send still counts as done.

Rules of the implementation for drafts (phase 2):

- A draft lives where mail clients keep drafts: on IMAP in the folder with
  the drafts role, flagged `\Draft`. An account without one lacks `drafts`
  and answers `501`.
- Its id is a message id, so `get_message` and the raw source read it. The
  draft routes reach only messages in the drafts folder: any other id
  answers `404`, so the right `drafts` cannot touch other mail.
- `PUT` replaces the whole draft. IMAP cannot change a stored message, so
  the new one is appended and the old one deleted. The id follows through
  the id mapping (4.1).
- A draft keeps its Bcc recipients, and its `reference` in the header
  `X-Mailbox-Service-Reference`, until it is sent. Both are removed before it
  goes out. The quote of a reply or forward is written when the draft is
  made, as a mail client does.
- `get_message` shows a draft's `reference`, where its header names an
  action and a message id. Free text in its place shows none. Replaced with that reference
  and `quote: false`, the draft keeps its link to the original (In-Reply-To,
  References, the mark after sending) and nothing of the original is added
  again: the text holds the quote already. The reference of any message
  that is not a draft is not shown: in a received mail the header is the
  sender's.
- A deleted draft is gone for good, not moved to the trash.
- `send_draft` sends the draft as stored, with the date of the send, and
  then deletes it. The sent folder gets its read copy as with `send`. The
  reference a draft kept marks its original, where the caller may change
  that message itself (`update_message`). A draft without recipients
  answers `400`. It needs only `send_draft`: the draft was written by
  whoever may write drafts.

Sending is **synchronous**: `200` means the provider accepted the
message. After an SMTP send the copy is appended to the sent folder.
Gmail and Graph keep it themselves, JMAP moves the submitted message
there (5.6).

**The outbox, decided 2026-11-25.** A send may go through an outbox
instead, asked for per request with `outbox: true` or a `send_at`. The
answer is then `202` with the job at once, and the service sends it in
the background. Without either, sending stays synchronous as above.

- The mail waits as a draft in the account's drafts folder. The service
  keeps a job that names the draft, a digest of it and the Message-ID
  every attempt sends, never the mail: it still holds no mail (7.8). An
  account without drafts, such as POP3, has no outbox.
- `send_at` lies at most 30 days ahead. Attempts go on for
  `MAILBOX_SERVICE_OUTBOX_RETRY_HOURS`, 48 by default, from the time the
  send is due. Then it fails and its draft stays.
- A send whose outcome cannot be told, such as a connection that drops
  once the server took the message, is never sent twice: the service
  looks for its Message-ID in the sent folder. Found, it went out. Where
  an account cannot look, it ends as `unknown` and is not sent again.
- A draft deleted or changed in a mail client after it was queued is not
  sent: the job is cancelled.
- The send goes with the rights of the user who queued it, read anew for
  each attempt. A right lost in between makes it fail, the draft stays.
- Whoever queued a send sees and cancels it. `list_sends` sees every
  send of the account, `update_account` sees and cancels every one.

`Idempotency-Key`: the result of the first request is stored for 24 hours.
The same key with the same body returns the stored result, with a different
body `409 idempotency_conflict`. A key counts per account and per user:
the same key from another user is a request of its own, never the first
user's result. Two MCP clients, whose keys follow from the call, do not
meet. Requests with the same key run one after the other, so a retry
that arrives while the first is still sending waits for its result. A
request that fails stores nothing and may be tried again.

## 6.5 Changes and webhooks

| Method | Path | Purpose |
|---|---|---|
| GET | `{acc}/changes?since=<state>` | created / updated / deleted message ids since a state token, plus a new state |
| GET | `/v1/changes?since=<state>` | the same across all accounts (`list_all_changes`) |
| GET / POST | `/v1/webhooks` | list, register (URL, events, account filter) |
| GET / PATCH / DELETE | `/v1/webhooks/{webhook_id}` | one webhook with its last 20 posts to the receiver, change its URL, events or accounts, remove |
| POST | `/v1/webhooks/{webhook_id}/secret` | a new signing secret, shown once, the one before void at once (`renew_webhook_secret`) |

Only the user who made a webhook sees, changes and removes it. A change
keeps its deliveries and where its posts stand, so no event is lost or
posted twice. A `PATCH` needs `list_changes` only on the accounts it
adds. `accounts` set to `null` is every account the owner may
read.

Events: `message.created`, `message.updated`, `message.deleted`,
`message.sent`, `message.send_failed`, `message.send_unknown`,
`message.send_cancelled`, `account.needs_reauth`. Payloads carry ids only, signed with
HMAC-SHA256 in a header. The source is IMAP IDLE / polling, POP3
polling, JMAP `Email/changes`, Gmail `history.list` and Graph delta
queries, all normalized into the change feed.

**Decided 2026-09-25:**

- IMAP uses CONDSTORE (RFC 7162) where the server offers it. A pass then
  also asks for the flags changed since the last one, so a message read
  or starred in another client shows as `message.updated`. Without
  CONDSTORE, only created, moved and deleted messages reach the feed.
- Changes are kept for `MAILBOX_SERVICE_CHANGES_DAYS` days, 7 by default.

Changes made through the API enter the feed for every provider. A
`since` older than the kept changes answers `410 changes_expired`, and
the client starts again from a new state. Without `since`, the answer
holds no changes, only the current state. The first sync of an account
records no changes: the messages already there are not new. **Decided
2026-10-06:** the worker takes an account up at once when it is connected,
its servers or credential change, or it is verified, not at its next
round: its first sync runs then, and a watcher starts where the server
can push. A mail that arrives after that first sync is in the feed. With
the worker off, nothing changes. The feed may
name a change more than once, e.g. a flag set through the API and seen
again through CONDSTORE. A client treats a repeated entry as harmless.

**Webhooks, decided 2026-09-26:** a webhook may point into the local
network, e.g. to an automation server, since it is registered on purpose.

A webhook belongs to the user who creates it, and each user sees and
removes only their own. It hears of the accounts that user may read with
`list_changes`, checked again at every post, so a right taken away also
stops the webhook. `accounts` narrows that further. The signing secret
starts with `whsec_`, is shown once, when the webhook is created or its secret
renewed, and is
kept sealed with the data key. A new webhook hears of what happens from
then on. The events come from the same log as the change feed, which also
holds `message.sent` (the copy in the sent folder, or else the Message-ID
header), the three ends of a send from the outbox that did not go out,
`message.send_failed`, `message.send_unknown` and
`message.send_cancelled` (the outbox job id), and
`account.needs_reauth` (the account id).

The service posts a webhook's events as JSON, up to 100 in one post:
`{"webhook_id", "delivery_id", "events": [{type, id, account_id, at}],
"more"}`. `X-Mailbox-Signature: t=<unix time>,v1=<hex>` carries the
HMAC-SHA256 of `<unix time>.` followed by the body, with the webhook's
secret. A receiver checks it and may refuse an old time. Each webhook
keeps the point in the log it has posted up to, so a restart loses
nothing and repeats nothing a receiver took. A post the receiver does not
answer with 2xx is tried again after 30 seconds, then twice as long each
time up to an hour, 8 times in all (the settings
`MAILBOX_SERVICE_WEBHOOK_ATTEMPTS`, `_FIRST_RETRY`, `_LONGEST_RETRY`).
After the last try its events are dropped and the webhook notes why in
`last_error`. The connection goes to the address that was checked. A host
in the local network passes, link-local, multicast and unspecified
addresses do not, nor the metadata services of cloud hosts outside
link-local that are known (AWS over IPv6, Alibaba Cloud). Redirects are
not followed.

## 6.6 Listing, search and pagination

`GET {acc}/messages` parameters:

| Parameter | Meaning |
|---|---|
| `folder` | folder id, or a role such as `inbox`. Left out: the inbox, on every account. The role `all` lists every folder but the trash and junk: Gmail's All Mail, a server's own `\All` folder on IMAP or JMAP, and otherwise, on Microsoft and on IMAP or JMAP servers without one, a folder "All Mail" the service shows (5.11). POP3 answers `501`. A grant narrowed to folders lists `all` within them |
| `q` | free text (subject, addresses, body where the provider can) |
| `from`, `to`, `subject` | structured filters |
| `after`, `before` | days, `YYYY-MM-DD`: `after` includes its day, `before` does not. The audits take a time with a zone instead |
| `unread`, `starred`, `has_attachments` | booleans |
| `limit` | 1–200, default 50 |
| `cursor` | opaque, from `next_cursor` of the previous page |

Every paged list answers `{"items": [...], "next_cursor": "..."}`,
`next_cursor` null on the last page. There is no
total count, because IMAP and Graph cannot provide one cheaply after a
filter.

Rules of the implementation (built before phase 3):

- Text filters are case-insensitive. On IMAP they match parts of words,
  as IMAP `SEARCH` compares them. Gmail, Microsoft and JMAP search their
  own index: Microsoft matches whole words or their beginnings, Gmail
  whole words only, a JMAP server as it indexes (5.11).
  They hold no control characters (`422`): IMAP clients quote search text
  but keep line breaks, which would end the command and start another.
- `after` and `before` are days, as IMAP searches by day: `after` includes
  its day, `before` does not.
- `has_attachments` searches with the provider's own rule: on IMAP a
  `multipart/mixed` message, elsewhere the provider's index. It comes
  near the field of the same name, which every account counts alike,
  but is not always the same.
- A parameter for the provider's own search syntax is not built.

### The service's own lists

Decided 2026-10-06. `GET /v1/accounts` (`list_accounts`) and
`GET /v1/users` (`list_users`) are paged like the lists of mail, with
`limit` (1–200, default 50) and `cursor`.

- Accounts come by address, users by name, both regardless of case, and
  by id where two are equal.
- The cursor carries the sort key of the last item on the page. The next
  page starts after it, so an account or user added or removed in
  between does not shift it.
- The filter parameters narrow the list before it is paged. A page holds
  only matches.
- One generic piece pages every list the service holds whole. A list
  names its order: the prefix of its cursors and the key of an item.
- Roles, the tokens of a user, webhooks and folders stay one list. They
  are few, and folders form a tree that is wanted whole. `GET /v1/me`
  and `GET /v1/status` stay whole as well, as an overview of what the
  caller may see.

### Across accounts

`GET /v1/messages` (`list_all_messages`) searches several accounts in one
call. It is what "what came in today" and "find the mail from the tax
advisor" need, whichever account it went to.

- Same parameters as above, plus `accounts` (a list of ids). Without it,
  every account the user may read.
- **Rights filter, not fail.** Accounts without `mail.read` for this user are
  left out silently, like in `list_accounts`.
- `folder` takes a **role** only (`inbox`, `sent`, …), since folder ids
  belong to one account.
- The accounts are asked in parallel, the results merged by the time
  received, newest first. The cursor is opaque and carries the position
  in every account. Each account gives the start of its own list: IMAP lists by arrival,
  so an old mail filed late may come a page early, but no message is
  skipped or given twice. Each page is newest first. An account reads
  at most ten of its own pages for one page of the list. Where the
  grants reach little of the folder, a page may hold fewer messages
  than asked, or none, with a cursor to read on.
- **One slow or failing account does not fail the request.** The answer is
  marked incomplete and says which account failed and why:

  ```json
  {"items": [...], "next_cursor": "...",
   "incomplete": [{"account_id": "acc_x", "code": "provider_error",
                   "message": "..."}]}
  ```
- Every item carries its `account_id`.

## 6.7 Errors

One envelope for every error the API raises itself:

```json
{"error": {"code": "not_found", "message": "account acc_x not found"}}
```

| Status | Code | When |
|---|---|---|
| 400 | `bad_request` | semantically invalid input |
| 401 | `unauthorized` | missing, wrong, expired or revoked credential, or disabled user |
| 403 | `forbidden`, `recipient_not_allowed` | the user has a grant for the account but not for this operation, or not in the folders it names, or no grant allows the recipient (7.5) |
| 404 | `not_found` | account, folder, message, also an account the user has no grant for |
| 409 | `conflict`, `idempotency_conflict`, `credential_missing` | the last: the account has no credential of the kind its sign-in needs |
| 410 | `changes_expired` | a `since` state older than the changes kept (6.5) |
| 413 | `payload_too_large` | a request body above the limit ([LIMITS.md](../LIMITS.md)) |
| 422 | FastAPI validation format | schema violation |
| 429 | `rate_limited`, `send_limit_reached` | with `Retry-After` |
| 501 | `not_supported` | capability missing |
| 500 | `credential_unreadable`, `storage_error`, `internal_error` | a stored credential cannot be decrypted, the service's own database failed, an unexpected failure |
| 502 | `provider_error`, `provider_auth_failed`, `provider_unavailable` | upstream failed. An auth failure sets the account to `needs_reauth`, an unreachable server to `unreachable` |
| 503 | `setup_required` | no user exists yet: run `users create-admin` |

## 6.8 OpenAPI

The API is OpenAPI 3.1, generated by FastAPI from the pydantic models.
Rules, all built and tested:

- `docs/mailbox-service/openapi.json` is checked in. A test fails when it differs from
  the code. Regenerate with `benethos-mailbox-service openapi > docs/mailbox-service/openapi.json`.
- `operationId` is the route function name (`list_messages`,
  `send_message`), unique and stable. Client generators and the MCP server
  depend on it.
- Every `/v1` operation but `get_linked_attachment` declares the
  `bearerAuth` scheme. Each documents its error responses with the
  `ErrorResponse` schema.
- Every `/v1` operation declares its required right as `x-permission`
  (7.5).
- Interactive docs at `/docs` (Swagger UI) and `/redoc`.
