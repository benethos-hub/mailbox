# The service log

Proposal of 2026-09-28, the first of two steps. What the service
writes to its log, at which level, with which fields, and what never
goes into a line. It builds on what exists since the log page: one
stream on stderr with time, level and source, secrets masked, the newest
lines on a page for the admin ([CONCEPT 7.4](CONCEPT.md#74-handling-rules),
[UI.md 6.5](UI.md)). The second step, an audit of administration in the
database, is [AUDIT.md](AUDIT.md): it takes the activities named here and
stores those someone caused. Both steps are built. What the user decides
is marked as decided, everything else is the proposal.

## 1. What the log is for

The log tells an operator what the service did and what went wrong, in
the order it happened, for this process. It is read at a terminal, in a
container log or the journal, and on the log page. It is not the audit:
the audit answers "who changed what, when", per record, in the database,
for as long as the deployment keeps it. The log may be dropped by the
host, the audit may not.

Four readers, four questions:

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
- **`TRACE`**: below `DEBUG`, for the service's own loggers and
  uvicorn's. Libraries stay at `WARNING` whatever the level, `imaplib`
  in particular, which echoes the login.

The service's own loggers follow `MAILBOX_SERVICE_LOG_LEVEL`, libraries
log from `WARNING` on, as `logs.py` sets it. `INFO` is the default: a day
of an ordinary deployment fits on one screen.

## 3. The shape of a line

`logs.py` writes time, level, source and message. The time is written
as rule 6.9 says. The source of an
activity is its area and its name: `activity.auth.signed_in`,
`activity.users.token_revoked` (section 7.2). The source of a technical
line is its module: `domain.sync.worker`. The console and the log page show
the source without the package's name in front, the plain lines for a
container or the journal with it. The message is one sentence in the
past tense, in this order:

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
   uvicorn writes the path of a request alone, without its query, which
   holds these terms.
5. **Webhook URLs beyond the host**: a URL may carry a key in its query.
   A webhook is its id and the host it posts to.
6. **Request bodies and library traffic**: never at any level of the
   service's loggers.

Allowed on purpose: user names, account addresses (an operator needs
them), client addresses, our ids, folder names, counts, error messages
of the service and of providers after masking.

The masking of `common/redact.py` stays the second line of
defence, not the first: a line is written as if there were no masking.

## 5. The activities

One table per area: the level, the line, its fields, and a note where
one helps. Fields in brackets are absent when unknown. The activities
the audit keeps as well are listed in [AUDIT.md](AUDIT.md) section 2.

### 5.1 Lifecycle

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | the service started: settings from X, database Y, schema N | env file, database path, schema version | "storage in memory" without a database |
| INFO | the database schema was migrated from N to M, notes | versions, the migrations' notes | "created the database" for a new one |
| INFO | the service stopped | | |
| ERROR | a background loop ended | which, traceback | |
| ERROR | a round of a background loop failed, the next one runs | which, traceback | |
| WARNING | the master key comes from the environment | | |
| WARNING | another service uses this database | | |

### 5.2 Sign-in and sessions

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | signed in to the UI | user, source | |
| WARNING | failed sign-in to the UI as X: reason | the user when the name is a user's, else "an unknown name", reason, source | |
| INFO | signed out | user | |
| WARNING | someone presented token T of U: reason | token name and id, user id, source, reason: revoked, expired or its user disabled | a token the service does not know counts against the sign-in throttle alone |
| WARNING | a wrong password to confirm a step | user | |

Sessions ending by idleness or restart are not logged. The lockouts of
the sign-in throttle are in 5.9 with the other limits.

### 5.3 Users, passwords, tokens, roles

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | X created user Y: roles, rights, where it signs in | actor, user, roles, counts, ui_sign_in | |
| INFO | X changed user Y: name, roles, grants, disabled, ui_sign_in | actor, user, the fields that changed | |
| INFO | X made Y an API user: its password is deleted | actor, user | when its UI sign-in is taken |
| INFO | the host let Y sign in to the UI again | user | `users set-password` for an API user |
| INFO | X deleted user Y and its N webhooks | actor, user, count | |
| INFO | X changed its password | user | |
| INFO | X set the password of Y / a one-time password for Y | actor, user | |
| INFO | X issued token Z for Y, with its expiry | actor, token name and id, user, expiry | |
| INFO | X revoked token Z of Y | actor, token name and id, user | |
| INFO | X created / replaced / deleted role R | actor, role, [its rights] | |
| WARNING | the grants and roles of Y name rights that do not exist, which give nothing: names | user, names | once per user and names, when its access is built |
| INFO | the host made a one-time password for Y | user | the line of a set password above, from `users create-admin` and `users set-password` |

### 5.4 Accounts and OAuth

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | X connected account A: provider [at host] | actor, account, provider, [host] | |
| INFO | X changed account A: what changed | actor, account, the display name, settings, the names of credentials | |
| INFO | X verified account A | actor, account | |
| INFO | X removed account A | actor, account | |
| WARNING | X could not connect the address (provider): reason | the address as typed, provider, reason | the account was not stored |
| INFO | the service reached account A again | account | on a change of status, after it needed a sign-in or could not be reached |
| WARNING | account A needs a new sign-in: reason | account, reason | a login or a token refresh was refused. On a change of status |
| WARNING | account A could not be reached: reason | account, reason | on a change of status, not per round |
| INFO | X started a sign-in with P for A | actor, provider, [account] | without an account to connect a new one |
| INFO | X finished the sign-in with P: A connected / signed in again | actor, provider, account | |
| WARNING | a sign-in with P failed: reason | provider, reason, no `state` | |
| DEBUG | the token of A was refreshed | account | |

A status that flips every round (unreachable, reachable) is logged on
the change, not on every round: the service keeps the last status of
each account and compares.

### 5.5 Sync and the worker

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | the worker started: interval, push | settings | |
| DEBUG | synced A: N folders, +a −r ~u | account, counts | added, removed, updated |
| WARNING | sync of A failed: reason | account, reason | |
| ERROR | sync of A failed | account, traceback | the same activity, for a failure that is not a `MailboxServiceError` (rule 6.5) |
| INFO | watching A / A cannot push changes: polling only | account | |
| INFO | polls A only: all N watchers are in use | account, cap | once per account while the cap holds, `MAILBOX_SERVICE_SYNC_WATCHERS` |
| WARNING | watching A failed, next try in Ns: reason | account, pause, reason | |
| DEBUG | IDLE on A renewed | account | |
| INFO | the change log was purged of N entries older than D | counts | once per purge. `INFO`, not `WARNING`: a purge is the normal course, at start and at most once an hour |

### 5.6 Sending, drafts, idempotency

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | X sent a message from A to N recipients | actor, account, count, the `msg_` id of the sent copy, else its Message-ID | |
| WARNING | X was refused to send from A: reason | actor, account id, the error's code | The code, as in the audit of sends: the message of a refusal or of a mail server may name a recipient |
| WARNING | X could not send from A: reason | actor, account id, the error's code | the provider did not take the message |
| WARNING | X sent a message from A, but …: reason | actor, account, what failed | the send stands |
| ERROR | sent, but not recorded in the audit of sends | account id, traceback | |
| DEBUG | an Idempotency-Key was replayed | account id, operation | |
| ERROR | did the operation on A, but could not keep its result for the Idempotency-Key | account id, operation, traceback | a retry with the same key would do it again |
| INFO | purged N records older than D from the audit of sends | count, before | at start and once an hour at most, `MAILBOX_SERVICE_AUDIT_DAYS` |

Drafts are mail content and change nothing others see: not logged.

### 5.7 Webhooks

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | X created webhook W to host H for its events of N accounts | actor, webhook id, host, events, accounts or "every account" | |
| INFO | X removed webhook W to host H | actor, webhook, host | |
| WARNING | could not post for webhook W, attempt N of M: reason | webhook, attempt, attempts, reason | the post is tried again |
| WARNING | gave up on N changes for webhook W after M attempts: reason | webhook, count of changes, attempts, reason | |
| INFO | posted for webhook W again | webhook | the first post that went through after failures |
| ERROR | could not post for webhook W | webhook, traceback | a failure in the round of one webhook, a `WARNING` for a `MailboxServiceError`. The other webhooks go on |

### 5.8 Discovery and the rest

| Level | Line | Fields | Note |
|---|---|---|---|
| DEBUG | looked up the servers of D: N candidates from M sources | domain, counts, no address | |
| INFO | the recovery key was shown to X | user | |
| INFO | X read the service log | user | once per visit or search, not for every further page |
| INFO | the host created the master key and the data key | | `keys init` |
| INFO | the host stored the master key from a recovery key | | `keys import` |
| INFO | opened the database with schema N; the file was rewritten once: from now on it shrinks after deletions | schema, notes | `system.migrated`, once for a database made by an earlier version |
| INFO | the host wrote a backup / restored the backup of time T | file, schema, [time] | |
| INFO | purged N records older than D from the audit | count, before | at start and once an hour at most, `MAILBOX_SERVICE_AUDIT_DAYS` ([AUDIT.md](AUDIT.md)) |
| ERROR | an activity could not be kept in the audit | the activity, traceback | its line is in the log |

### 5.9 Rate limits

Every limit the service enforces, and every pause a provider asks for,
writes a line: the operator must see who is being slowed down and why,
and the log page is where a locked-out person's report is checked. The
limits themselves, and how they work together, are in
[LIMITS.md](LIMITS.md).

| Level | Line | Fields | Note |
|---|---|---|---|
| WARNING | too many failed sign-ins from S: locked out for N minutes | source, minutes | `SignInThrottle`, 10 in 15 min by default |
| WARNING | too many failed sign-ins as X: the name waits N seconds | the user when the name is a user's, else "an unknown name", seconds | the brake per name, from any address |
| INFO | the lockout of S ended | source | at the next attempt after it ran out: any sign-in in the UI, a wrong token on the API |
| WARNING | X reached the discovery limit of N in a minute | user, limit | `DiscoveryService`, 10 per user by default |
| WARNING | X reached the send limit on A: reason, the next in N seconds | actor, account id, reason, `retry_after` | in the audit of sends as `denied` |
| WARNING | a request from S to P larger than N MB: refused | source, path, limit | `web/limits.py`, 413 |
| WARNING | X sent too many requests, the last to P: limited to N a minute, refused for M seconds | token, session or source, path, rate, seconds | `web/limits.py`, 429 |
| DEBUG | paced requests to H: waited N ms | host, wait | no activity: a technical line of the token bucket in front of a provider, which knows the server but not the account |
| DEBUG | microsoft asked to wait N seconds (Retry-After), gmail asked to wait N seconds | seconds | no activity: a technical line of the Microsoft or the Gmail adapter |
| WARNING | account A could not be reached: the provider's reason | account, reason | the status line of 5.4, no activity of its own: a pause or a refusal for rate reaches the domain as an error, and the account's status changes once |

A limit that keeps being hit is logged once per lockout or pause, not
per refused request: the throttle logs when it locks, the provider
pause when it starts. Each refused request still answers `429` with
`Retry-After`, and the access log has the line.

**HTTP requests are limited.** **Decided 2026-09-28:** a limit per
token for requests with a credential, and one per client address for
requests without, both as tokens per minute with a burst, in
`web/limits.py` beside the body limit, refused with `429` and
`Retry-After`. **Decided 2026-09-29:** the values and the details.

- A signed-in caller counts per API token or per UI session, where its
  credential is checked: `MAILBOX_SERVICE_RATE_LIMIT_PER_MINUTE`, 120
  by default.
- Any other request counts per client address, before the app sees it:
  the sign-in page and its files, a wrong path, the API's documentation.
  `MAILBOX_SERVICE_RATE_LIMIT_ANONYMOUS_PER_MINUTE`, 30 by default.
- A burst of half as many passes at once. That covers the MCP server's
  start, which calls `/v1/me` and lists folders for every account. `0`
  switches a limit off.
- `/health` is not limited.
- The OpenAPI document names the `429` once, in its description, not at
  every operation.

A wrong credential is left to the sign-in throttle, which locks the
address after ten failures by default. A valid token passes a locked
address, since it cannot be guessed (LIMITS.md 3). The sign-in throttle
stays where it is: it covers guessed credentials and knows the outcome,
which a limit on requests cannot. Its log line is the row above, once per caller when
the limit engages, not per refused request.

### 5.10 The MCP server

Its own process, its own log on stderr, its own rules, the same spirit:

- `INFO` at start: transport, the service's URL, which tools were
  registered, and before it a `WARNING` per account that reads mail
  and sends anywhere.
- `WARNING` for a tool that failed, with the tool's name and the code of
  the service's error and its HTTP status, not its message: a message
  may repeat an address or a search term the model sent. A refusal of
  the server's own checks says "the arguments were refused".
- Never a tool's arguments, never a search term, never mail content,
  never the token. `httpx` and the MCP library at `WARNING`, so no
  request URL is written.
- Each line has the time of rule 6.9, the level, the source and the
  message. Over HTTP, uvicorn's lines go through the same format.

## 6. Rules for writing a line

1. **Activities go through `ActivityLog.record`**, every line of
   section 5. A domain service builds the activity and hands it over,
   it writes no line of its own. The recorder logs under the logger of
   the activity, `activity.<area>.<name>`. No module of the domain but
   those of `domain/activity` has a logger of its own, and
   `test_code_rules.py` checks it. A technical line outside the
   domain keeps one logger per module, `log = logging.getLogger(__name__)`.
2. **The domain logs activities, the layers around it do not.** A route
   knows the request, the domain knows what happened and who did it.
   The client address reaches the domain on `Access`: `Access.source`,
   set where the caller is established (bearer for the API, session for
   the UI), absent for the worker and the host. The audit of AUDIT.md
   takes it from there as well. The data layer writes no line at `INFO` or
   above: it
   decides nothing, and it knows neither the actor nor the reason. What
   it notices goes up as a result or an error, and the domain logs it.
   The two lines that were under `data/` moved that way: the IMAP adapter
   reports a missing sent copy in `SentMessage`, and `outgoing` logs it.
   The migrations return their notes, and `assembly` logs them at start.
   `DEBUG` stays allowed under `data/` for the technical steps the
   domain cannot see: a reconnect, a retry, a token refresh, a pause a
   provider asked for. `test_code_rules.py` checks that no module
   under `data/` calls `log.info`, `log.warning`, `log.error` or
   `log.exception`. The web layer logs nothing but what it refuses
   before the domain sees the request, the body limit and the limit on
   requests, at `WARNING`.
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
   (`users`, `keys`, `restore`) records the same as an activity, so the
   audit keeps it. A command sets up no log, so its line reaches no
   handler, and the log page shows the lines of its own process alone.
9. **One time in every line.** Every line writes the time alike, at
   every place and in every format: ISO 8601, the local time of the
   machine, to the millisecond, with the offset:
   `2026-09-30T10:12:22.123+02:00`. That holds for the plain lines, the
   console, the log page, the MCP server's log and a time inside a
   message, such as the end of a purge. `log_time` in
   `common/clock.py` writes it. **Decided 2026-09-30.**
10. **An activity is one line.** A name or an address a caller chose may
    hold a line break. The recorder writes each break and each other
    control character as its escape, such as `\n` or `\u2028`, so no
    value starts a line of its own. A traceback follows its line as
    before.

## 7. Where the activities live

**Decided 2026-09-28:** a package of its own in the domain, the activities
as small classes, one module per area of section 5. Not one file per
activity: sixty files would cost more than they say. The package is
`activity`, not `events`: an event is a change in a mailbox today, and
the word stays free for an event-driven design later (section 7.1).

```
domain/
  activity/
    __init__.py      ActivityLog and Activity, and the module of each
                       area: what the domain services use
    base.py          Activity: who, from where, when, level, audited, line()
    recorder.py      ActivityLog.record(activity): the log line, and the
                       audit record of AUDIT.md for one marked audited
    catalogue/       one module per area, the areas of section 7.2
      system.py        start, schema, stop, loops, recovery key, log
                         read, keys, backups
      auth.py          signed in, failed sign-in, token refused, lockouts
      users.py         user created, token issued, role replaced, ...
      accounts.py      account connected, needs a new sign-in, OAuth
      discovery.py     a lookup, the discovery limit
      mailbox.py       sent, refused, replayed, the send limit
      sync.py          a pass, a failed sync, IDLE
      changes.py       the change log purged
      webhooks.py      created, removed, a post failed, given up
      http.py          what the web layer refuses: a body too large,
                         a caller out of requests
```

- **`Activity`** is a frozen dataclass. Every activity carries who acted and
  from where, taken from `Access` (the user, its token, `Access.source`),
  or the worker, the dispatcher or the host, and when. The class says
  its `level` and whether the audit keeps it (`audited`, AUDIT.md
  section 2). `line()` writes the sentence of section 3.
- **An activity is one class** in the module of its area, named for what
  happened: `UiSignIn`, `TokenRevoked`, `AccountNeedsSignIn`. Its fields
  are typed: a `User`, an `Account`, a count. There is no field for a
  password, a token's value or the words of a mail, so none can reach a
  line. An activity that failed carries the error, and the recorder logs
  a traceback for what is not a `MailboxServiceError` (rule 6.5).
- **`ActivityLog`** is a service like the others: `build_services` makes it
  with the clock and the audit of AUDIT.md. The domain
  services that record get it in their constructor. `record()` logs the
  line under `activity.<area>.<name>`, at the activity's level, and
  returns the activity, for tests.
- **A change in a mailbox is no activity.** It stays with
  `domain/changes/` and its classes, for clients. The docstrings of
  both packages say the difference.

### 7.1 Three words

| Word | What | Where |
|---|---|---|
| activity | what was done in the service, and by whom | `domain/activity/`, the log, the audit |
| change | what changed in a mailbox: `message.created` and the like | `domain/changes/`, the change feed, webhooks |
| event | not used for either. Kept free for an event-driven design | |

A webhook's `events` and its five values keep their names, since they
are part of the API. The code's names around them are `ChangeKind` and
`ChangeRecord` ([REFACTORING.md](REFACTORING.md) section 3).

### 7.2 Names

**Decided 2026-09-28:** each activity has a name, and it logs under
`activity.<area>.<name>`.

- **The area is a package of the domain** ([REFACTORING.md](REFACTORING.md)
  section 4): `auth`, `users`, `accounts`, `discovery`, `mailbox`,
  `sync`, `changes`, `webhooks`, `system`. An activity belongs to the
  package whose code records it, so a reader finds the code of
  `activity.mailbox.sent` in `domain/mailbox/`. Two areas are more than
  a package of the domain: `system`
  also holds what the assembly records, the start, the schema and the
  stop, and `http` holds what the web layer refuses before the domain
  sees a request. The limits of section 5.9 are with the area that
  enforces them: the lockouts in `auth`, the send limit in `mailbox`.
- **The name is set in the class, not taken from it**: `name =
  "token_revoked"`. A class renamed in the code keeps its name in the
  log, in the filters of an operator and in the audit, which keeps it
  as the kind of a record.
- **A name says what happened**, in the past tense or as a state,
  lowercase with underscores. It is unique within its area. The area is
  not repeated: `activity.users.created`, not
  `activity.users.user_created`.
- **Short enough for a column**: `activity.<area>.<name>` has 32
  characters at most, so the console aligns every line.
- **Each has its own logger.** A level set on one name silences it
  alone, e.g. `activity.sync.synced`. A search for `activity.users` on
  the log page still finds the whole area.

A test checks that every activity has a name that follows these rules
and that each is listed here.

| Name | What |
|---|---|
| `system.started` | the service started: settings, database, schema |
| `system.migrated` | the schema was migrated or created, with its notes |
| `system.stopped` | the service stopped |
| `system.loop_ended` | a background loop ended |
| `system.round_failed` | a round of a background loop failed |
| `system.key_from_env` | the master key comes from the environment |
| `system.shared_db` | another service uses this database |
| `system.recovery_shown` | the recovery key was shown |
| `system.log_read` | the service log was read |
| `system.keys_created` | the host created the keys |
| `system.key_imported` | the host stored the master key from a recovery key |
| `system.backup_written` | the host wrote a backup |
| `system.backup_restored` | the host restored a backup |
| `system.audit_purged` | old records purged from the audit of administration |
| `system.not_audited` | an activity the audit could not keep |
| `auth.signed_in` | a sign-in to the UI |
| `auth.sign_in_failed` | a failed sign-in to the UI |
| `auth.signed_out` | a sign-out of the UI |
| `auth.confirm_failed` | a wrong password to confirm a step |
| `auth.token_refused` | a token that is revoked, expired or of a disabled user |
| `auth.locked_out` | a client address locked out after failed sign-ins |
| `auth.lockout_ended` | its lockout ended |
| `auth.name_braked` | a user name slowed down after failed sign-ins |
| `users.created` | a user created |
| `users.changed` | a user changed |
| `users.deleted` | a user deleted |
| `users.made_api_user` | a user's UI sign-in taken |
| `users.sign_in_allowed` | the host gave a user its UI sign-in back |
| `users.password_changed` | a user changed its own password |
| `users.password_set` | a password or one-time password set for a user |
| `users.token_issued` | a token issued |
| `users.token_revoked` | a token revoked |
| `users.role_created` | a role created |
| `users.role_replaced` | a role replaced |
| `users.role_deleted` | a role deleted |
| `users.unknown_rights` | stored grants or roles name rights that do not exist |
| `accounts.connected` | an account connected |
| `accounts.connect_failed` | an account could not be connected |
| `accounts.changed` | an account changed |
| `accounts.verified` | an account verified |
| `accounts.removed` | an account removed |
| `accounts.reachable` | an account reached again |
| `accounts.needs_sign_in` | an account needs a new sign-in |
| `accounts.unreachable` | an account could not be reached |
| `accounts.oauth_started` | an OAuth sign-in started |
| `accounts.oauth_finished` | an OAuth sign-in finished |
| `accounts.oauth_failed` | an OAuth sign-in failed |
| `accounts.token_renewed` | an account's access token refreshed |
| `discovery.looked_up` | the servers of a domain looked up |
| `discovery.limit_reached` | a user reached the discovery limit |
| `mailbox.sent` | a message sent |
| `mailbox.refused` | a send refused by the grants |
| `mailbox.send_failed` | a send the provider did not take |
| `mailbox.sent_but` | a step after a send failed |
| `mailbox.not_in_audit` | a send not recorded in the audit of sends |
| `mailbox.send_limit` | a user reached the send limit |
| `mailbox.replayed` | a result given again for an Idempotency-Key |
| `mailbox.sends_purged` | old records purged from the audit of sends |
| `mailbox.result_not_kept` | a result not kept for its Idempotency-Key |
| `sync.worker_started` | the worker started |
| `sync.synced` | a pass over an account, with counts |
| `sync.failed` | a pass that failed |
| `sync.watching` | the worker watches an account |
| `sync.push_unavailable` | an account cannot push changes |
| `sync.watch_postponed` | an account is polled only: every watcher is in use |
| `sync.idle_renewed` | IDLE renewed |
| `sync.watch_failed` | watching an account failed |
| `changes.purged` | old changes purged from the change log |
| `webhooks.created` | a webhook created |
| `webhooks.removed` | a webhook removed |
| `webhooks.post_failed` | a post failed, to be tried again |
| `webhooks.gave_up` | the posts of a batch given up |
| `webhooks.delivers_again` | a post went through after failures |
| `webhooks.failed` | a post failed with a bug |
| `http.body_too_large` | a request body over the limit refused |
| `http.rate_limited` | a token, a UI session or an address ran out of requests |

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

Steps 2 to 5 were one branch, one commit per step, and step 6 a pull
request of its own: all six are done. The audit of AUDIT.md was built
after them, in the order of work of its section 6.

## 9. Questions answered

- **Decided 2026-09-28:** an account is named by its address and its id,
  as section 3 says.
- **Decided 2026-09-28:** each sync pass writes one line with its counts
  at `DEBUG`.
