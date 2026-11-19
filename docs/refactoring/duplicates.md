# Refactoring: code written twice

Part of [REFACTORING.md](../REFACTORING.md): section 9.

## 9. Code written twice

Found 2026-09-28 by reading every layer, each finding checked in both
places. Section 8 moves modules and changes nothing. This section
changes code: a helper replaces its copies, behaviour stays, and the
helper gets a test. It comes after section 8, so that no file is moved
and edited in the same step (9.4). Paths are under
`packages/mailbox-service/src/benethos_mailbox_service/`.

### 9.1 More helpers for `common`

Beyond `redact` and `ratelimit` (8.2). Each is standard library only
and read by more than one layer.

| # | What | Where today | Proposed |
|---|---|---|---|
| A1 | HTML to text, `from_html` | `data/mail/text.py`, read by `data` (compose) and `web` (the mail page) | `common/plaintext.py`. The one plain helper `web` takes from `data` besides `redact` |
| A2 | The local time to the millisecond | the same f-string in `logs.py` and `web/pages/templates.py` (`moment`) | `local_moment` in `common/clock.py` |
| A3 | A host name normalised: lower case, trailing dot off, IDNA, syntax | `data/discovery/autoconfig.py` (`_host`, `_HOST`), `domain/discovery/service.py` (its own, with `_LABEL`), lower and rstrip alone in `data/http/safe.py` and `data/discovery/suffix.py` | `common/hosts.py`: `ascii_host`, `unicode_host`, `is_host_name`. Side finding: `safe.py` compares configured internal hosts without IDNA, so a Unicode host never matches |
| A4 | Megabytes as text, the byte constants | `// (1024 * 1024)` and "MB" in `web/limits.py` and `activity/catalogue/http.py`, `40 * 1024 * 1024` three times, "25 MB" as text beside `MAX_ATTACHMENT_BYTES` in `outgoing.py` | `common/sizes.py`: `MIB`, `megabytes(n)` |
| A5 | `iso` and `parse_iso` | `data/storage/sqlite/database.py`, rebuilt by hand in `domain/mailbox/sending.py` and `domain/sync/service.py`, `datetime.now(UTC)` instead of `utc_now` in `data/secrets/backup.py` and `protocols/imap.py`, ISO parsing again in `microsoft/mappers.py` | `common/clock.py`. Borderline: the domain's times are UTC already, so this is consistency |
| A6 | Chunking, `range(0, len(x), N)` | six times in `data` | `batched()` in `common`, until Python 3.12 is the minimum and `itertools.batched` exists |
| A7 | Base64 without padding | `common/opaque.py`, `data/secrets/passwords.py`, `data/providers/protocols/oauth.py` | exported from `common/opaque.py`, with a flag for the alphabet |

Considered and left: the `rpartition("@")` one-liners, the
case-insensitive substring filter (five places, an idiom), the address
shown as "Name <email>" (three purposes), `quote(safe="")` (one call),
`encode_recovery` (the key's own format, stays in `data.secrets`). The
MCP package repeats `from_html`, the address format, the idempotency
fingerprint and the path quoting: allowed, the two packages share no
code.

### 9.2 Domain and web

| # | What | Where | Proposed |
|---|---|---|---|
| B1 | Record an activity and re-raise: five equal `except MailboxServiceError` blocks. Record and swallow: `_after_sending` in `outgoing.py`, rebuilt by hand in `sending.py` and `idempotency.py` | `accounts/service.py`, `accounts/oauth.py`, `mailbox/sending.py` (three), `mailbox/idempotency.py` | two context managers on `ActivityLog` in `activity/recorder.py`, about 35 lines to 12 |
| B2 | Load the user, check the caller covers it: six copies. Own user or `get_user`: two | `users/service.py` | `_managed(access, op, user_id)` and `_self_or_get_user` |
| B3 | Bounded tables: drop the expired, then the oldest. Sliding window trimmed and capped | `auth/throttle.py`, `discovery/service.py` (twice) | one helper beside `locks.py`, domain only |
| B4 | Cursors and pages: decode then "invalid cursor" in `sending.py` and `merge.py`, own decoding in `changes/feed.py` and `system/servicelog.py`, encoding straight with `opaque` in three, `limit + 1` and `more` in four | `domain/paging.py` gets `encode_cursor`, `decode_cursor(prefix, value, parse)`, `split_page(found, limit)` |
| B5 | Pages: build a model, turn `ValidationError` into `FormError` | `mailform.py`, `routes/folders.py`, `routes/webhooks.py`, `routes/sends.py`, `grants.py` | `model_of(...)` in `web/pages/forms.py` |
| B6 | The account ids the caller may do X on | `mailbox/service.py` (twice), `mailbox/sending.py`, `webhooks/delivery.py`, `accounts/service.py` | `Access.filter(operation, ids)` in `rights/access.py` |
| B7 | Pages: call the domain if allowed, else a default: eight copies | `routes/sends.py`, `routes/users.py` (four), `routes/mail.py`, `routes/home.py`, and `system/status.py` | `if_allowed(...)` in `web/pages/deps.py` |
| B8 | The web decides what the domain decides: `effective.py` rebuilds `ACCOUNT_FREE \| ALL_ACCOUNTS` (`access.py` builds it three times), `navigation.py` recomputes `StatusService.may_see`, `routes/mail.py` derives the batch rule that `mailbox/service.py` enforces | one constant and two predicates in `rights`, the web calls them |
| B9 | AuthService: load a user, refuse if missing or disabled, three times. The name key twice | `auth/service.py` | `_live_user`, `_name_key` |
| B10 | The background loop: repeat, record a failed round, sleep, in two places, wrapped once more by `main.py`. `Retries.pause` in `delivery.py` rebuilds `backoff` without jitter | `webhooks/delivery.py`, `sync/worker.py`, `main.py` | one `rounds(...)` helper in the domain, `backoff` from `common` (after 8.2) |
| B11 | The fingerprint as sorted JSON under two names | `mailbox/merge.py`, `mailbox/idempotency.py` | one helper. Changing the idempotency hash invalidates stored keys, kept 24 h: a commit of its own, noted in the CHANGELOG |
| B12 | Pages read the same form fields twice, once to show them again, once for the call | `routes/webhooks.py`, `routes/users.py`, `routes/accounts.py` | read once into the typed dict |
| B13 | SyncWorker: look up the account, record only if it still exists, four times | `sync/worker.py` | `_record(account_id, make)` |
| B14 | Small: the mail page URL built three times. `quote(safe="")` twice in `web`. `LOG_LEVELS` beside `servicelog.LEVELS`. The admin grant literal in `users/service.py` and `access.py` (`Access.admin` unused). The mail form's field keys listed three times. `str(form.get(x) or "")` 39 times. `why()` six times in the activity catalogue. `TokenInfo.of(...)` three times | | each a one-line helper or a constant |

### 9.3 Data

| # | What | Where | Proposed |
|---|---|---|---|
| C1 | Three SQLite repositories rewrite `SqliteRows`: list, get, delete with the same SQL | `sqlite/accounts.py`, `sqlite/webhooks.py`, `sqlite/users.py` (tokens) | `SqliteRows` gets `order` and a public `row(id)`, the three hold one |
| C2 | In-memory repositories rewrite `Table`: webhooks in full, the conflict scan in `sends.py` and `credentials.py`, "drop keys where" three times | `storage/webhooks.py`, `storage/sends.py`, `storage/credentials.py`, `storage/idempotency.py` | `Table`, plus `drop_where` in `table.py` |
| C3 | Chunked `IN` queries with the same limit of 500 and the same comment | `sqlite/changes.py`, `sqlite/index.py` | `Database.query_in(...)`, on A6 |
| C4 | IMAP and SMTP wrappers are twins: `ImapServer` and `SmtpServer` the same dataclass, the same `UnicodeError` clause with its comment, the same connect lines | `protocols/imap.py`, `protocols/smtp.py` | a `Server` dataclass and the clause in `transport.py` |
| C5 | Microsoft repeats itself: the move call four times, the parent-folder check twice, the `@odata.nextLink` loop twice, `retry-after` read twice | `microsoft/provider.py` | `_move`, `_parent`, one page generator, in the same file |
| C6 | `port_of` and `rate_of` near copies | `providers/rules.py` | one private `_number(...)` |
| C7 | The vault's `read` and `unseal` share the decrypt path | `secrets/vault.py` | one private `_open(...)` |
| C8 | Folder with role X or `no_folder`, in each provider, though `rules.role_folder` exists | `memory/provider.py`, `imap/provider.py` (three places), `microsoft/provider.py` | `rules.require_role_folder(folders, role)` |
| C9 | An address on the wire, punycode or fail: identical | `mail/compose.py` (`_wire`), `protocols/smtp.py` (`_on_the_wire`) | `wire_address` in `mail/fields.py` |
| C10 | `missing(what, id)` exists in `table.py`, about twenty places build the same text by hand | `imap/mappers.py`, `memory/provider.py`, `imap/provider.py`, `microsoft/provider.py`, `mail/convert.py`, `protocols/imap.py` | `missing` to `errors.py`, used everywhere |
| C11 | The flag filter (unread, starred, has_attachments) twice | `memory/provider.py`, `microsoft/mappers.py` | `MessageFilter.matches` in `models/messages.py`, as `SendFilter.matches` |
| C12 | Small: host clean-up inline four times (A3), the deadline message in `guard.py` and `microsoft/provider.py`, two spellings of the schema-version query and of `SELECT 1 ... WHERE id` | | with A3, and one-liners |

Checked and clean: the error translation per library, retry and backoff
(one place), the mappers, the discovery sources, the migrations, the
API routes (thin, no rights checks or cursor parsing of their own), the
error mapping of the web layer (one place), `opaque` as the one cursor
encoder, `config.py` and `errors.py`.

About 150 lines fewer in `data`, about 200 in the domain and the web.
For clarity, A1 to A5, B1, B4, B6 and B8 matter most. For lines, C1 to
C3.

### 9.4 Order, so that nothing overlaps

The moves of section 8 and the merges of this section touch the same
files: the SQLite repositories (A5, C1), the providers (8.3, C4, C5,
C8), the vault (8.2, C7), `delivery.py` and `worker.py` (8.2, B10).
So they run one after the other, never side by side. **Decided
2026-09-28:** one branch for all of it, in this order:

1. **Section 8**, moves only (8.5). Every later step finds the files
   where they will stay.
2. **`common` and the helpers other layers build on** (9.1, and C3 on
   A6, C10). It touches `data`, the domain and the web at the call
   sites, so it goes before the layers, which then start from the
   helpers. The side finding of A3 is fixed in a commit of its own,
   with its CHANGELOG entry.
3. **`data`** (9.3), bottom up as the lines of 8.3: storage (C1, C2),
   then `mail` and `protocols` (C4, C9), then the providers (C5, C6,
   C8, C11), then the vault (C7).
4. **Domain and web** (9.2): `rights` first (B6, B8), then the services
   (B1, B2, B9, B13), `paging` (B4), the loops (B3, B10), then the
   pages (B5, B7, B12, B14). B11 is a commit of its own with its
   CHANGELOG entry. A stored idempotency key or cursor that no longer
   matches is accepted: at worst a test database starts afresh.
5. **ARCHITECTURE.md takes over** everything on the architecture from
   CLAUDE.md (8.6), and CLAUDE.md points to it.

One commit per finding or per row of the tables above. Each commit
passes all checks. A helper new to `common` or the domain gets its test
in the same commit. The live checks run once, at the end. A problem
found on the way is noted, and its step waits until the end.

### 9.5 Built otherwise

Where the code differed from the tables, and what was accepted. **Decided
2026-09-28:** all of it stays as built.

- **B6**: the account list keeps a loop of its own, since it filters by
  two rights and three fields more. `Access.filter` serves the rest.
- **B7**: `if_allowed` is synchronous. The folder list of the mail
  page is awaited and keeps its own check, and `system/status.py` is
  the domain, where the helper does not belong.
- **B10**: `main._loop` stays as the guard around a background loop
  that ends for good. Since #72 it is `_loop` in
  `assembly/lifecycle.py`.
- **A2**: the helper is `log_time` in `common/clock.py`, as
  LOGGING.md 6.9 names the time of a log line. Since the package
  `mailbox-common` it is in its `log/lines.py` (15.2).
- **B14**: the six `why()` of the activity catalogue stay, since their
  reasons are of different types.
- **C8**: the Microsoft adapter keeps its folder roles, which come from
  Graph's well-known names, not from `rules`.
- **C11**: the method is `MessageFilter.flags_match`, not `matches`,
  since it checks unread, starred and attachments alone.

Three small changes in behaviour came with the merges:

- **B2**: a user's new name is checked after the right and the cover.
  A caller who may not manage the user learns nothing about taken
  names: `403` where it was `409`. In the CHANGELOG.
- **B4**: the log page hands out an opaque cursor, as every other list.
- **A3**: `is_host_name(..., dotted=False)` for the domain of an
  address, so its error messages stay as they were.
