# The service log

Proposal of 2026-09-28. What the service writes to its log, at which
level, with which fields, and what never goes into a line. It builds on
what exists since the log page: one stream on stderr with time, level
and source, secrets masked, the newest lines on a page for the admin
([CONCEPT 7.4](CONCEPT.md#74-handling-rules), [UI.md 6.5](UI.md)). It
also draws the line to the audit of
[PERMISSIONS.md 8.6](PERMISSIONS.md#86-an-audit-of-administration), so
the log lines written now become the audit records later without a
second design. What the user decides is marked as decided, everything
else is the proposal.

## 1. What the log is for

The log tells an operator what the service did and what went wrong, in
the order it happened, for this process. It is read at a terminal, in a
container log or the journal, and on the log page. It is not the audit:
the audit answers "who changed what, when", per record, in the database,
for as long as the deployment keeps it. The log may be dropped by the
host, the audit may not.

Three readers, three questions:

| Reader | Question | Level |
|---|---|---|
| The operator at night | is something broken that needs me? | `ERROR` |
| The operator in the morning | what failed or was refused, and did it heal? | `WARNING` |
| The operator who asks "what happened to account X" | what did people and the service do? | `INFO` |
| The developer | which steps did the service take? | `DEBUG` |

## 2. Levels

- **`ERROR`**: the service could not do something it must, and an
  operator has to act. A background loop died, storage failed, a bug
  raised. Always with the traceback. Never for a failure the service
  heals on its own.
- **`WARNING`**: something failed or was refused, and the service goes
  on. A sync that failed this round, a webhook post that will be retried,
  a sign-in with a wrong password, a grant that names a right the
  catalogue does not know. A `MailboxServiceError` is a warning with its
  message and no traceback. Anything else is an error with one.
- **`INFO`**: one line per change of state that someone or something
  caused, and the lifecycle of the process. A sign-in, a user created, an
  account connected, a token issued, a webhook removed, an account that
  needs a new sign-in. Reading changes nothing and is not logged, with
  two exceptions: the recovery key shown and the log page read, since
  both hand out what others must not see.
- **`DEBUG`**: the steps the service takes, one line per step, with
  counts: a sync pass of one account, an IDLE renewed, a token refreshed,
  an idempotent send replayed, a discovery lookup. Never the wire
  traffic of a library.
- **`TRACE`**: the libraries' own debug output, never `imaplib`'s, which
  echoes the login.

The service's own loggers follow `MAILBOX_SERVICE_LOG_LEVEL`, libraries
log from `WARNING` on, as `logs.py` sets it. `INFO` is the default: a day
of an ordinary deployment fits on one screen.

## 3. The shape of a line

`logs.py` writes time, level, source and message. The source is the
module: `domain.auth`, `domain.worker`. The message is one sentence in
the past tense, in this order:

```
<who> <did what> <to which> [from <where>][: <why>]
```

- **who**: the user's name and id, `admin (usr_7f3a…)`. When the user
  came with a token, the token's name after it: `Claude Desktop
  (usr_91c0…, token laptop)`. The service itself is `the worker`, `the
  dispatcher`, `the host` for a CLI command.
- **did what**: the verb of the operation: signed in, connected,
  changed, removed, issued, revoked, sent.
- **to which**: the record: a user by name and id, an account by address
  and id, a token by name and id, a role and a webhook by id. A message
  by its `msg_` id, never by subject.
- **from where**: the client address, when the event came from a
  request. Section 7 says how it reaches the domain.
- **why**: the message of the error or the refusal, masked, when there
  is one.

Ids are written in full. A person searches the log page for an id
copied from a page, and a prefix would not match. Nothing else about the
format changes: no key-value pairs and no JSON, since the log page
searches text and a person reads it.

## 4. What never goes into a line

1. **Secrets**: passwords, one-time passwords, tokens, the recovery key,
   the master key, webhook secrets, OAuth tokens, codes and `state`,
   session ids, CSRF tokens. A token is named by its name and id.
2. **Mail content**: subject, body, attachment names, headers. A message
   is its `msg_` id. A draft the same.
3. **Recipients and senders of mail**: addresses of people. A send is
   logged with the count of its recipients, the addresses are in the
   audit of sends alone.
4. **Search terms** and filter values a person typed: the API's `q`,
   `from`, `subject`, the UI's search, the discovery address's local
   part. A discovery lookup names the domain only.
5. **Webhook URLs beyond the host**: a URL may carry a key in its query.
   A webhook is its id and the host it posts to.
6. **Request bodies and library traffic**: never at any level of the
   service's loggers.

Allowed on purpose: user names, account addresses (an operator needs
them), client addresses, our ids, folder names, counts, error messages
of the service and of providers after masking.

The masking of `data/secrets/redact.py` stays the second line of
defence, not the first: a line is written as if there were no masking.

## 5. The events

One table per area: the level, the line, its fields, whether it exists
today, and whether it goes into the audit later (section 6). Fields in
brackets are absent when unknown.

### 5.1 Lifecycle

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | the service started: settings from X, database Y, schema N | env file, database path, schema version | printed, not logged |
| INFO | schema migrated from N to M, notes | versions, the migrations' notes | per step as warning in `database.py`, moves to `main` |
| INFO | the service stopped | | new |
| ERROR | a background loop ended | which, traceback | worker and dispatcher log per round |
| WARNING | the master key comes from the environment | | yes |

### 5.2 Sign-in and sessions

| Level | Line | Fields | Today | Audit |
|---|---|---|---|---|
| INFO | signed in to the UI | user, source | yes | yes |
| WARNING | failed sign-in to the UI as X: reason | name as typed, reason, source | yes | yes |
| INFO | signed out | user | new | no |
| WARNING | a token was presented that is revoked or expired | token id, source | new, `authenticate` knows it | yes |
| WARNING | a wrong password to confirm a step | user | yes | yes |

Sessions ending by idleness or restart are not logged. The lockouts of
the sign-in throttle are in 5.9 with the other limits.

### 5.3 Users, passwords, tokens, roles

| Level | Line | Fields | Today | Audit |
|---|---|---|---|---|
| INFO | X created user Y (roles, N grants, ui_sign_in) | actor, user, counts | new | yes |
| INFO | X changed user Y: name, roles, grants, disabled, ui_sign_in | actor, user, the fields that changed | partly (API user switch) | yes |
| INFO | X deleted user Y and its N webhooks | actor, user, count | yes | yes |
| INFO | X changed its password | user | yes | yes |
| INFO | X set the password of Y / a one-time password for Y | actor, user | yes | yes |
| INFO | X issued token Z (name, expires) for Y | actor, token, user, expiry | new | yes |
| INFO | X revoked token Z of Y | actor, token, user | new | yes |
| INFO | X created / replaced / deleted role R | actor, role | new | yes |
| WARNING | a stored grant names rights that do not exist | names | yes | no |
| INFO | the host made a one-time password for Y | user | yes | yes |

### 5.4 Accounts and OAuth

| Level | Line | Fields | Today | Audit |
|---|---|---|---|---|
| INFO | X connected account A (provider, host) | actor, account, provider, host | new | yes |
| INFO | X changed account A: settings, display name, password | actor, account, what changed | new | yes |
| INFO | X verified account A | actor, account | new | yes |
| INFO | X removed account A | actor, account | new | yes |
| WARNING | connecting A failed: reason | address, reason | new | yes |
| INFO | account A is connected again | account | new, on status change | no |
| WARNING | account A needs a new sign-in: reason | account, reason | new, where `NEEDS_REAUTH` is set | no |
| WARNING | account A is unreachable: reason | account, reason | new, once per change, not per round | no |
| INFO | X started a sign-in with P for A | actor, provider, [account] | new | yes |
| INFO | X finished the sign-in with P: A connected / signed in again | actor, provider, account | new | yes |
| WARNING | a sign-in with P failed: reason | provider, reason, no `state` | new | yes |
| DEBUG | the token of A was refreshed | account | new | no |
| WARNING | the refresh for A was refused: reason | account, reason | new | no |

A status that flips every round (unreachable, reachable) is logged on
the change, not on every round: the worker keeps the last status and
compares.

### 5.5 Sync and the worker

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | the worker started: interval, push | settings | new |
| DEBUG | synced A: N folders, +a −r ~u | account, counts | new |
| WARNING | sync of A failed: reason | account, reason | yes |
| ERROR | sync of A failed | account, traceback | yes |
| INFO | watching A / A cannot push changes: polling only | account | partly |
| WARNING | watching A failed, next try in Ns: reason | account, pause, reason | yes |
| DEBUG | IDLE on A renewed | account | new |
| WARNING | the change log was purged of N entries older than D | counts | new, once per purge |

### 5.6 Sending, drafts, idempotency

| Level | Line | Fields | Today | Audit |
|---|---|---|---|---|
| INFO | X sent a message from A to N recipients | actor, account, count, `msg_` id | new | in the send audit |
| WARNING | X was refused to send from A: reason | actor, account, reason | new | in the send audit |
| WARNING | sent, but …: reason | account, what failed | yes, one of them in the adapter, moves to `outgoing` | no |
| ERROR | sent, but not recorded in the audit | traceback | yes | no |
| DEBUG | an Idempotency-Key was replayed | account, operation | new | no |

Drafts are mail content and change nothing others see: not logged.

### 5.7 Webhooks

| Level | Line | Fields | Today | Audit |
|---|---|---|---|---|
| INFO | X created webhook W to host H for N events | actor, webhook id, host, events, accounts or "every" | new | yes |
| INFO | X removed webhook W | actor, webhook | new | yes |
| WARNING | webhook W: post failed, attempt N of M: reason | webhook, attempt, reason | partly | no |
| WARNING | webhook W gave up on event E after M attempts | webhook, seq | new | no |
| INFO | webhook W delivers again | webhook | new, on recovery | no |
| ERROR | a round of webhook posts failed | traceback | yes | no |

### 5.8 Discovery, throttle, the rest

| Level | Line | Fields | Today |
|---|---|---|---|
| DEBUG | discovery for domain D: N candidates from sources | domain, counts, no address | new |
| WARNING | X reached the discovery limit | user | new |
| INFO | the recovery key was shown to X | user | yes |
| INFO | X read the service log | user | new |
| INFO | backup written / restored (from the host) | file, schema, time | printed, add the line |

### 5.9 Rate limits

Every limit the service enforces, and every pause a provider asks for,
writes a line: the operator must see who is being slowed down and why,
and the log page is where a locked-out person's report is checked.

| Level | Line | Fields | Today | Audit |
|---|---|---|---|---|
| WARNING | too many failed sign-ins from S: locked out for N minutes | source, minutes | new (`SignInThrottle`, 10 in 15 min) | yes |
| WARNING | too many failed sign-ins as X: waiting N seconds | name as typed, seconds | new (the brake per name) | yes |
| INFO | the lockout of S ended | source | new, when the lockout is lifted | no |
| WARNING | X reached the discovery limit (N in a minute) | user, count | new (`DiscoveryService`, 10 per user) | no |
| WARNING | X reached the send limit on A: N in 24 hours, the grants allow M | actor, account, counts, `retry_after` | new, in the send audit as `denied` | in the send audit |
| WARNING | a request from S was refused: body of N bytes, the limit is M | source, path, sizes | new (`web/limits.py`, 413) | no |
| DEBUG | paced A: waited N ms | account, wait | new (`Guard`, the token bucket) | no |
| WARNING | provider of A asked to wait N seconds (Retry-After) | account, seconds | new (Microsoft `_rest_until`) | no |
| WARNING | provider of A refused for rate: reason | account, reason | new (IMAP `[LIMIT]`, SMTP 4xx) | no |

A limit that keeps being hit is logged once per lockout or pause, not
per refused request: the throttle logs when it locks, the provider
pause when it starts. Each refused request still answers `429` with
`Retry-After`, and the access log has the line.

**HTTP requests as such are not limited by the service.** The API
refuses a body above the limit and slows sign-ins, nothing else.
**Decided 2026-09-28:** it stays that way. The sign-in throttle in the
domain covers guessed credentials for both front ends, and a limit on
requests with a valid token is load protection, which a reverse proxy
in front of the service does better than the service itself.

### 5.10 The MCP server

Its own process, its own log on stderr, its own rules, the same spirit:

- `INFO` at start: transport, the service's URL, which tools were
  registered, the warning per account that reads mail and sends
  anywhere.
- `WARNING` for a tool that failed with the service's error message.
- Never a tool's arguments, never a search term, never mail content,
  never the token. `httpx` and the MCP library at `WARNING`, so no
  request URL is written.

## 6. The line to the audit

Every event marked "yes" in section 5 is an administrative action or a
sign-in: someone did something to a record. Those become the records of
the `events` table of PERMISSIONS.md 8.6, with the same fields the line
carries: time, user, credential, operation, record, source, outcome.
The rest stays in the log alone: what the worker, the dispatcher and the
providers did on their own.

So that the two never drift, a domain event is written from one place:
a small helper in the domain, `events.record(...)`, that logs the line
now and, once 8.6 is built, stores the record as well. Each domain
service calls it where it changes a record, after the change is stored.
Nothing else in the code writes an `INFO` line about a user's action.

## 7. Rules for writing a line

1. **One logger per module**, `log = logging.getLogger(__name__)`, so
   the source names the module.
2. **The domain logs events, the layers around it do not.** A route
   knows the request, the domain knows what happened and who did it.
   The client address reaches the domain on `Access`: `Access.source`,
   set where the caller is established (bearer for the API, session for
   the UI), absent for the worker and the host. The audit needs it
   there too. The data layer writes no line at `INFO` or above: it
   decides nothing, and it knows neither the actor nor the reason. What
   it notices goes up as a result or an error, and the domain logs it.
   The two lines under `data/` today move that way: the IMAP adapter
   reports a missing sent copy in `SentMessage`, and `outgoing` logs it;
   the migrations return their notes, and `main` logs them at start.
   `DEBUG` stays allowed under `data/` for the technical steps the
   domain cannot see: a reconnect, a retry, a token refresh, a pause a
   provider asked for. `test_architecture.py` checks that no module
   under `data/` calls `log.info`, `log.warning`, `log.error` or
   `log.exception`. The web layer logs nothing but what it refuses
   before the domain sees the request, the body limit, at `WARNING`.
3. **After the change, not before.** A line says what happened, so it is
   written once the store took the change. A refusal is logged where it
   is refused.
4. **`%s` arguments, never f-strings**, so a line costs nothing below
   its level and the masking sees message and arguments alike.
5. **A MailboxServiceError is `exc.message` at WARNING.** `log.exception`
   only for what is not ours, at ERROR, once per failure, not again by
   the caller.
6. **Once per change of state**, not per round: the worker and the
   dispatcher remember the last outcome per account and webhook and log
   when it flips.
7. **Every new line has a test** with `caplog`: the level, the text, and
   that no secret of the test is in it. `test_logs.py` keeps a test that
   a noted secret is masked in message, argument and traceback.
8. **The CLI prints, the service logs.** A command talks to the person
   at the terminal on stderr, and a command that changes the database
   (`users`, `keys`, `restore`) writes the same as a log line, so the log
   page of the next start knows it. Whether that line survives is the
   host's business.

## 8. Order of work

1. This file, one pull request of documentation. CONCEPT 7.4 and
   PERMISSIONS.md 8.6 point here.
2. `Access.source` and the `events` helper in the domain, the two
   existing sign-in lines moved onto it. The lifecycle lines of 5.1.
   The two lines under `data/` moved up, and the architecture test of
   rule 7.2.
3. The missing lines of 5.3 and 5.4: users, tokens, roles, accounts,
   OAuth. Each with its test.
4. The missing lines of 5.5 to 5.9: sync at `DEBUG` with counts, the
   status flips, sending, webhooks, discovery, the log page read, the
   rate limits and provider pauses.
5. The MCP server's lines of 5.10.
6. When 8.6 is built: the helper stores what it logs, nothing else
   changes.

## 9. Open questions

- Account addresses in the log: they help an operator, but a log that
  leaves the machine then carries personal data. Ids alone, or both?
- `DEBUG` per sync pass is one line per account every five minutes.
  Acceptable at `DEBUG`, or should the counts go to the status page
  only?
- Should the `events` helper come now, before 8.6, or is a plain
  `log.info` per service enough until the audit exists?
