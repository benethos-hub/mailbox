# The service log

Proposal of 2026-09-28, the first of two steps. What the service
writes to its log, at which level, with which fields, and what never
goes into a line. It builds on what exists since the log page: one
stream on stderr with time, level and source, secrets masked, the newest
lines on a page for the admin ([CONCEPT 7.4](CONCEPT.md#74-handling-rules),
[UI.md 6.5](UI.md)). The second step, an audit of administration in the
database, is [AUDIT.md](AUDIT.md) and comes later: it takes the activities
named here and stores those someone caused. What the user decides is
marked as decided, everything else is the proposal.

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

`logs.py` writes time, level, source and message. The source of an
activity is its area: `activity.auth`, `activity.users` (section 7). The source
of a technical line is its module: `domain.worker`. The message is one
sentence in the past tense, in this order:

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
- **from where**: the client address, when the activity came from a
  request. Section 6 says how it reaches the domain.
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
   part. A discovery lookup names the domain only. The access log of
   uvicorn writes a request's query today, and with it these terms: it
   writes the path alone from step 2 of section 8 on.
5. **Webhook URLs beyond the host**: a URL may carry a key in its query.
   A webhook is its id and the host it posts to.
6. **Request bodies and library traffic**: never at any level of the
   service's loggers.

Allowed on purpose: user names, account addresses (an operator needs
them), client addresses, our ids, folder names, counts, error messages
of the service and of providers after masking.

The masking of `data/secrets/redact.py` stays the second line of
defence, not the first: a line is written as if there were no masking.

## 5. The activities

One table per area: the level, the line, its fields, and whether it
exists today. Fields in brackets are absent when unknown. Which of
these activities become audit records later is AUDIT.md's list.

### 5.1 Lifecycle

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | the service started: settings from X, database Y, schema N | env file, database path, schema version | printed, not logged |
| INFO | schema migrated from N to M, notes | versions, the migrations' notes | per step as warning in `database.py`, moves to `main` |
| INFO | the service stopped | | new |
| ERROR | a background loop ended | which, traceback | worker and dispatcher log per round |
| ERROR | a round of a background loop failed, the next one runs | which, traceback | yes |
| WARNING | the master key comes from the environment | | yes |
| WARNING | another service uses this database | | yes |

### 5.2 Sign-in and sessions

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | signed in to the UI | user, source | yes |
| WARNING | failed sign-in to the UI as X: reason | the user when the name is a user's, else "an unknown name", reason, source | yes |
| INFO | signed out | user | new |
| WARNING | a token was presented that is revoked or expired, or whose user is disabled | token id, source | new, `authenticate` knows it |
| WARNING | a wrong password to confirm a step | user | yes |

Sessions ending by idleness or restart are not logged. The lockouts of
the sign-in throttle are in 5.9 with the other limits.

### 5.3 Users, passwords, tokens, roles

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | X created user Y (roles, N grants, ui_sign_in) | actor, user, counts | new |
| INFO | X changed user Y: name, roles, grants, disabled, ui_sign_in | actor, user, the fields that changed | partly (API user switch) |
| INFO | X deleted user Y and its N webhooks | actor, user, count | yes |
| INFO | X changed its password | user | yes |
| INFO | X set the password of Y / a one-time password for Y | actor, user | yes |
| INFO | X issued token Z (name, expires) for Y | actor, token, user, expiry | new |
| INFO | X revoked token Z of Y | actor, token, user | new |
| INFO | X created / replaced / deleted role R | actor, role | new |
| WARNING | a stored grant names rights that do not exist | names | yes |
| INFO | the host made a one-time password for Y | user | yes |

### 5.4 Accounts and OAuth

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | X connected account A (provider, host) | actor, account, provider, host | new |
| INFO | X changed account A: settings, display name, password | actor, account, what changed | new |
| INFO | X verified account A | actor, account | new |
| INFO | X removed account A | actor, account | new |
| WARNING | connecting A failed: reason | address, reason | new |
| INFO | account A is connected again | account | new, on status change |
| WARNING | account A needs a new sign-in: reason | account, reason | new, where `NEEDS_REAUTH` is set |
| WARNING | account A is unreachable: reason | account, reason | new, once per change, not per round |
| INFO | X started a sign-in with P for A | actor, provider, [account] | new |
| INFO | X finished the sign-in with P: A connected / signed in again | actor, provider, account | new |
| WARNING | a sign-in with P failed: reason | provider, reason, no `state` | new |
| DEBUG | the token of A was refreshed | account | new |
| WARNING | the refresh for A was refused: reason | account, reason | the line "A needs a new sign-in: reason" above |

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

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | X sent a message from A to N recipients | actor, account, count, `msg_` id | new |
| WARNING | X was refused to send from A: reason | actor, account, reason | new |
| WARNING | sent, but …: reason | account, what failed | yes, one of them in the adapter, moves to `outgoing` |
| ERROR | sent, but not recorded in the audit | traceback | yes |
| DEBUG | an Idempotency-Key was replayed | account, operation | new |

Drafts are mail content and change nothing others see: not logged.

### 5.7 Webhooks

| Level | Line | Fields | Today |
|---|---|---|---|
| INFO | X created webhook W to host H for N events | actor, webhook id, host, events, accounts or "every" | new |
| INFO | X removed webhook W | actor, webhook | new |
| WARNING | webhook W: post failed, attempt N of M: reason | webhook, attempt, reason | partly |
| WARNING | webhook W gave up on event E after M attempts | webhook, seq | new |
| INFO | webhook W delivers again | webhook | new, on recovery |
| ERROR | a round of webhook posts failed | traceback | yes |

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

| Level | Line | Fields | Today |
|---|---|---|---|
| WARNING | too many failed sign-ins from S: locked out for N minutes | source, minutes | new (`SignInThrottle`, 10 in 15 min) |
| WARNING | too many failed sign-ins as X: waiting N seconds | name as typed, seconds | new (the brake per name) |
| INFO | the lockout of S ended | source | new, when the lockout is lifted |
| WARNING | X reached the discovery limit (N in a minute) | user, count | new (`DiscoveryService`, 10 per user) |
| WARNING | X reached the send limit on A: N in 24 hours, the grants allow M | actor, account, counts, `retry_after` | new, in the send audit as `denied` |
| WARNING | a request from S was refused: body of N bytes, the limit is M | source, path, sizes | new (`web/limits.py`, 413) |
| WARNING | too many requests from S / with token Z: limited for N seconds | source or token, path, seconds | new, with the HTTP limit below |
| DEBUG | paced A: waited N ms | account, wait | new (`Guard`, the token bucket) |
| WARNING | provider of A asked to wait N seconds (Retry-After) | account, seconds | new (Microsoft `_rest_until`) |
| WARNING | provider of A refused for rate: reason | account, reason | new (IMAP `[LIMIT]`, SMTP 4xx) |

A limit that keeps being hit is logged once per lockout or pause, not
per refused request: the throttle logs when it locks, the provider
pause when it starts. Each refused request still answers `429` with
`Retry-After`, and the access log has the line.

**HTTP requests as such are not limited by the service today.** The
API refuses a body above the limit and slows sign-ins, nothing else. A
token that loops, or a client without one that guesses paths, can call
as fast as the service answers. **Decided 2026-09-28:** the service
limits them, as a pull request of its own after this concept: a limit
per client address for requests without a valid credential, and one
per token for requests with one, both as tokens per minute with a
burst, in `web/limits.py` beside the body limit, refused with `429` and
`Retry-After`. The values go into `Settings`
(`MAILBOX_SERVICE_RATE_LIMIT_PER_MINUTE`, per address and per token),
with a default generous enough for the MCP server's start, which calls
`/v1/me` and lists folders for every account. Its log line is the row
above, once per client or token when the limit engages, not per refused
request. The sign-in throttle stays where it is: it covers guessed
credentials and knows the outcome, which a limit on requests cannot.

### 5.10 The MCP server

Its own process, its own log on stderr, its own rules, the same spirit:

- `INFO` at start: transport, the service's URL, which tools were
  registered, the warning per account that reads mail and sends
  anywhere.
- `WARNING` for a tool that failed with the service's error message.
- Never a tool's arguments, never a search term, never mail content,
  never the token. `httpx` and the MCP library at `WARNING`, so no
  request URL is written.

## 6. Rules for writing a line

1. **Activities go through `ActivityLog.record`**, every line of
   section 5. A domain service builds the activity and hands it over,
   it writes no line of its own. The recorder logs under the logger of
   the activity's area. A technical line outside section 5 keeps one
   logger per module, `log = logging.getLogger(__name__)`.
2. **The domain logs activities, the layers around it do not.** A route
   knows the request, the domain knows what happened and who did it.
   The client address reaches the domain on `Access`: `Access.source`,
   set where the caller is established (bearer for the API, session for
   the UI), absent for the worker and the host. The audit of AUDIT.md
   needs it there as well. The data layer writes no line at `INFO` or
   above: it
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
7. **Every new activity has a test** with `caplog`: the level, the text,
   and that no secret of the test is in it. A test walks the catalogue:
   each class has a level and a line, and no field of a type that holds
   a secret or mail content. `test_logs.py` keeps a test that a noted
   secret is masked in message, argument and traceback.
8. **The CLI prints, the service logs.** A command talks to the person
   at the terminal on stderr, and a command that changes the database
   (`users`, `keys`, `restore`) writes the same as a log line, so the log
   page of the next start knows it. Whether that line survives is the
   host's business.

## 7. Where the activities live

**Decided 2026-09-28:** a package of its own in the domain, the activities
as small classes, one module per area of section 5. Not one file per
activity: sixty files would cost more than they say. The package is
`activity`, not `events`: an event is a change in a mailbox today, and
the word stays free for an event-driven design later (section 7.1).

```
domain/
  activity/
    __init__.py      ActivityLog and Activity: what the domain services use
    base.py          Activity: who, from where, when, level, audited, line()
    recorder.py      ActivityLog.record(activity): the log line, and the
                       audit record of AUDIT.md for one marked audited
    catalogue/       one module per area of section 5
      lifecycle.py     5.1  the service started, schema migrated, ...
      auth.py          5.2  signed in, failed sign-in, token refused, ...
      users.py         5.3  user created, token issued, role replaced, ...
      accounts.py      5.4  account connected, needs a new sign-in, OAuth
      sync.py          5.5  a pass, a failed sync, IDLE
      sending.py       5.6  sent, refused, replayed
      webhooks.py      5.7  created, removed, a post failed, given up
      service.py       5.8  discovery, recovery key shown, log read, backup
      limits.py        5.9  lockouts, send limit, provider pauses
```

- **`Activity`** is a frozen dataclass. Every activity carries who acted and
  from where, taken from `Access` (the user, its token, `Access.source`),
  or the worker, the dispatcher or the host, and when. The class says
  its `level` and whether the audit keeps it (`audited`, AUDIT.md
  section 2). `line()` writes the sentence of section 3.
- **An activity is one class** in the module of its area, named for what
  happened: `SignedIn`, `TokenRevoked`, `AccountNeedsSignIn`. Its fields
  are typed: a `User`, an `Account`, a count. There is no field for a
  password, a token's value or the words of a mail, so none can reach a
  line. An activity that failed carries the error, and the recorder logs
  a traceback for what is not a `MailboxServiceError` (rule 6.5).
- **`ActivityLog`** is a service like the others: `build_services` makes it
  with the clock and, from AUDIT.md on, the repository. The domain
  services that record get it in their constructor. `record()` logs the
  line under `activity.<area>`, at the activity's level, and returns
  the activity, for tests.
- **A change in a mailbox is no activity.** It stays with
  `domain/changes.py` and its `EventType`, for clients. The docstring of
  `domain/activity/` says the difference.

### 7.1 Three words

| Word | What | Where |
|---|---|---|
| activity | what was done in the service, and by whom | `domain/activity/`, the log, the audit |
| change | what changed in a mailbox: `message.created` and the like | `domain/changes.py`, the change feed, webhooks |
| event | not used for either. Kept free for an event-driven design | |

A webhook's `events` and its five values keep their names, since they
are part of the API. The code's names around them, `EventType` and
`Event`, are [REFACTORING.md](REFACTORING.md) section 3's matter.

## 8. Order of work

1. This file and AUDIT.md, one pull request of documentation.
   CONCEPT 7.4 and PERMISSIONS.md 8.6 point here.
2. `domain/activity/` with `Activity`, `ActivityLog` and the catalogue
   test. `Access.source`, the lifecycle activities of 5.1, the two lines under
   `data/` moved up, and the architecture test of rule 6.2. The lines
   of today move onto activity classes, each where it is written now. The
   access log without the query of a request (section 4).
3. The missing activities of 5.3 and 5.4: users, tokens, roles, accounts,
   OAuth. Each with its test.
4. The missing lines of 5.5 to 5.9: sync at `DEBUG` with counts, the
   status flips, sending, webhooks, discovery, the log page read, the
   rate limits and provider pauses.
5. The MCP server's lines of 5.10.
6. The HTTP request limit of 5.9, as a pull request of its own, with
   its settings, tests, a CHANGELOG entry and its line.

Steps 2 to 5 are one branch, one commit per step. AUDIT.md follows
when the user asks for it.

## 9. Questions answered

- **Decided 2026-09-28:** an account is named by its address and its id,
  as section 3 says.
- **Decided 2026-09-28:** each sync pass writes one line with its counts
  at `DEBUG`.
