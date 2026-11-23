# Logging: the activities

Part of [LOGGING.md](../LOGGING.md): section 5.

## 5. The activities

One table per area: the level, the line, its fields, and a note where
one helps. Fields in brackets are absent when unknown. The activities
the audit keeps as well are listed in [AUDIT.md](../AUDIT.md) section 2.

### 5.1 Lifecycle

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | the service started: settings from X, database Y, schema N | env file, database path, schema version | "storage in memory" without a database |
| INFO | the database schema was migrated from N to M, notes | versions, the migrations' notes | "created the database" for a new one |
| INFO | the service stopped | | |
| ERROR | a background loop ended | which, traceback | the service then stops, and `serve` ends with an error, for a supervisor to start it anew |
| ERROR | a round of a background loop failed, the next one runs | which, traceback | |
| WARNING | the master key comes from the environment | | |
| WARNING | another service uses this database | | |

### 5.2 Sign-in and sessions

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | signed in to the UI [with a code of D / with the passkey D] | user, source, how: `password`, `password+totp`, `password+recovery`, `password+passkey`, the device | after the code, for a user with a second factor |
| WARNING | failed sign-in to the UI as X: reason | the user when the name is a user's, else "an unknown name", reason, source | |
| WARNING | someone typed a wrong code to sign in to the UI as X | user, source | after the right password ([AUTHENTICATION.md](../AUTHENTICATION.md) 4) |
| WARNING | X signed in with a recovery code, N left | user, count, source | its app is gone or out of reach |
| WARNING | X signed in to the UI, which ended its oldest session / its N oldest sessions: at most M at once | user, count, limit, source | a user holds a few sessions at most ([LIMITS.md](../LIMITS.md)). Many in a row may be a stolen password |
| INFO | signed out | user | |
| WARNING | someone presented token T of U: reason | token name and id, user id, source, reason: revoked, expired or its user disabled | a token the service does not know counts against the sign-in throttle alone |
| WARNING | a wrong password or code to confirm a step | user | |

Sessions ending by idleness or restart are not logged. The lockouts of
the sign-in throttle are in 5.9 with the other limits.

### 5.3 Users, passwords, tokens, roles

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | X created user Y: roles, rights, where it signs in | actor, user, roles, counts, ui_sign_in | |
| INFO | X changed user Y: name, roles, service, grants, disabled, ui_sign_in | actor, user, the fields that changed | |
| WARNING | X could not disable / enable / give role R to / take role R from user Y in a batch: reason | actor, user, action, role, reason | one per user a batch of the users list refused. Then it changes none |
| INFO | X made Y an API user: its password is deleted | actor, user | when its UI sign-in is taken |
| INFO | the host let Y sign in to the UI again | user | `users set-password` for an API user |
| INFO | X deleted user Y and its N webhooks | actor, user, count | |
| INFO | X changed its password | user | |
| INFO | X set the password of Y / a one-time password for Y | actor, user | |
| INFO | X added the authenticator app D to its second factor[, which turns it on] | user, device | TOTP. The first device turns the second factor on |
| INFO | X renamed its authenticator app D to E | user, both names | TOTP |
| INFO | X removed its authenticator app D / the authenticator app D of Y[, the last one: the second factor is off] | actor, user, device | TOTP |
| INFO | X added the passkey D to its second factor[, which turns it on] | user, passkey | The first device turns the second factor on |
| INFO | X renamed its passkey D to E | user, both names | |
| INFO | X removed its passkey D / the passkey D of Y[, the last device: the second factor is off] | actor, user, passkey | |
| INFO | X removed every device of the second factor of Y | actor, user | every method and the recovery codes. The host too, with `users reset-second-factor` |
| INFO | X made new recovery codes for its second factor | user | |
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
| WARNING | X could not finish a sign-in with P: reason | actor, provider, reason, no `state` | |
| INFO | account A can do otherwise now: +gained, -lost | account, the capabilities gained and lost | when the server answers other capabilities than were stored, e.g. after it stopped offering IDLE |
| DEBUG | the token of A was refreshed | account | |

A status that flips every round (unreachable, reachable) is logged on
the change, not on every round: the service keeps the last status of
each account and compares.

### 5.5 Sync and the worker

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | the worker started: interval, push | settings | |
| DEBUG | synced A: N folders, +a −r ~u | account, counts | added, removed, updated |
| DEBUG | read A again: a change made through the service overtook the pass | account | the pass applied nothing |
| INFO | left the index of A to the next pass: changes made through the service overtook N attempts | account, attempts | |
| WARNING | sync of A failed: reason | account, reason | |
| ERROR | sync of A failed | account, traceback | the same activity, for a failure that is not a `MailboxServiceError` (rule 6.5) |
| INFO | watching A / A cannot push changes: polling only | account | |
| INFO | polls A only: all N watchers are in use | account, cap | once per account while the cap holds, `MAILBOX_SERVICE_SYNC_WATCHERS` |
| WARNING | watching A failed, next try in Ns: reason | account, pause, reason | |
| DEBUG | IDLE on A renewed | account | |
| INFO | the change log was purged of N entries older than D | counts | once per purge. `INFO`, not `WARNING`: a purge is the normal course, at start and at most once an hour |

### 5.6 Sending, drafts, idempotency, links

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
| INFO | X shared attachment T of M in A as link L for N s | actor, the ids of the attachment, the message, the account and the link, seconds | never the secret, never the URL |
| INFO | X had attachment T of M in A fetched through link L | the user of the token that made the link, its token, the address that fetched it, the ids | |
| WARNING | someone was refused link L: reason | source, link id, reason: used, ended, its token or the token's user can no longer act, or what the service answered | a secret that is no link's writes no line, as a wrong token does not |
| WARNING | X had link L handed back, nothing was fetched: reason | the user of the token that made the link, the address that fetched it, link id, reason | the mail server did not hand out the attachment: the link holds for the rest of its time, the answer is `502` |
| INFO | purged N links to attachments, used or ended by D | count, time | at start and once an hour at most, as links are made |

Drafts are mail content and change nothing others see: not logged.

### 5.7 Webhooks

| Level | Line | Fields | Note |
|---|---|---|---|
| INFO | X created webhook W to host H for its events of N accounts | actor, webhook id, host, events, accounts or "every account" | |
| INFO | X changed the url, events, accounts of webhook W, posting to host H | actor, webhook, host now, what changed | |
| INFO | X gave webhook W to host H a new signing secret, the one before stops at once | actor, webhook, host | never the secret |
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
| INFO | purged N records older than D from the audit | count, before | at start and once an hour at most, `MAILBOX_SERVICE_AUDIT_DAYS` ([AUDIT.md](../AUDIT.md)) |
| ERROR | an activity could not be kept in the audit | the activity, traceback | its line is in the log |

### 5.9 Rate limits

Every limit the service enforces, and every pause a provider asks for,
writes a line: the operator must see who is being slowed down and why,
and the log page is where a locked-out person's report is checked. The
limits themselves, and how they work together, are in
[LIMITS.md](../LIMITS.md).

| Level | Line | Fields | Note |
|---|---|---|---|
| WARNING | too many failed sign-ins from S: locked out for N minutes | source, minutes | `SignInThrottle`, 10 in 15 min by default |
| WARNING | too many failed sign-ins as X: the name waits N seconds | the user when the name is a user's, else "an unknown name", seconds | the brake per name, from any address |
| INFO | the lockout of S ended | source | at the next attempt after it ran out: any sign-in in the UI, a wrong token on the API |
| WARNING | X reached the discovery limit of N in a minute | user, limit | `DiscoveryService`, 10 per user by default |
| WARNING | X reached the send limit on A: reason, the next in N seconds | actor, account id, reason, `retry_after` | in the audit of sends as `denied` |
| WARNING | a request from S to P larger than N MB: refused | source, path, a link's masked, limit | `web/limits.py`, 413 |
| WARNING | X sent too many requests, the last to P: limited to N a minute, refused for M seconds | token, session or source, path, a link's masked, rate, seconds | `web/limits.py`, 429, a link `404` |
| DEBUG | paced requests to H: waited N ms | host, wait | no activity: a technical line of the token bucket in front of a provider, which knows the server but not the account |
| DEBUG | microsoft asked to wait N seconds (Retry-After), microsoft answered a conflict on attempt N, gmail asked to wait N seconds, gmail answered STATUS on attempt N | seconds, the status and the attempt | no activity: a technical line of the Microsoft or the Gmail adapter |
| WARNING | account A could not be reached: the provider's reason | account, reason | the status line of 5.4, no activity of its own: a pause or a refusal for rate reaches the domain as an error, and the account's status changes once |

A limit that keeps being hit is logged once per lockout or pause, not
per refused request: the throttle logs when it locks, the provider
pause when it starts. The send limit is the exception: it logs each
send it stops. Each refused request still answers `429` with
`Retry-After`, and the access log has the line.

**HTTP requests are limited.** **Decided 2026-09-28:** a limit per
token for requests with a credential, and one per client address for
requests without, both as tokens per minute with a burst, in
`web/limits.py` beside the body limit, refused with `429` and
`Retry-After`. **Decided 2026-09-29:** the values and the details, which
are in [LIMITS.md](../LIMITS.md) sections 1 to 3. The OpenAPI document
names the `429` in its description and at every operation that takes a
token. The line of this limit is the row above, once per caller when
the limit engages, not per refused request.

### 5.10 The MCP server

Its own process, its own log on stderr, its own rules, the same spirit:

- `INFO` at start: the settings file it read, if any, the transport,
  over HTTP its address and whether a bearer token is required, the
  service's URL and which tools were registered, and before those a
  `WARNING` per account that reads mail and sends anywhere. A
  `WARNING` over HTTP without a bearer token, which only a loopback
  address or a catalogue allows, and over stdio where one is set and
  ignored.
- As a catalogue (`MAILBOX_MCP_CATALOGUE`), one `WARNING` at start that
  it lists every tool and runs none but `server_status`, without a
  service. It stands in place of the warnings per account and of the
  line with the service's URL and the tools. The lines for the
  settings file, the transport and the bearer token stay. A call it
  refuses writes nothing.
- `INFO` when the tools changed while it runs: which came and went, and
  how many clients were told, with the same `WARNING`s after it.
  `WARNING` once when the service could not be asked, `INFO` when it
  answers again. `WARNING` when it refused the token or its user may do
  nothing.
- `WARNING` for a tool that failed, with the tool's name and the code of
  the service's error and its HTTP status, not its message: a message
  may repeat an address or a search term the model sent. An error the
  server raises itself says what kind it was, never the message: "the
  arguments were refused", "the PDF took too long", "the attachment is
  too large" or "no thread".
- `DEBUG` when the service's version could not be asked at `/health`,
  which the server does at start and before each time it asks what its
  token may do. `server_status` itself logs nothing.
- Never a tool's arguments, never a search term, never mail content,
  never the token. `MAILBOX_MCP_LOG_LEVEL` sets the level of the
  server's own lines, every other logger writes at `WARNING` and above,
  as with the agents (2026-11-23). `httpx`, `httpcore`, their copies
  `httpx2` and `httpcore2` that the MCP library brings, and the MCP
  library itself are held at `WARNING` whatever the level says, so no
  request URL is written.
- Each line is written as the service writes it, by the same code in
  `mailbox-common`: the time of rule 6.9, the level, the source and the
  message, short and in colour on a terminal, plain elsewhere. A noted
  secret is masked as `***`: the service's token and the bearer token
  are noted at start, though no line names them. Over HTTP, uvicorn's
  lines go through the same format.
