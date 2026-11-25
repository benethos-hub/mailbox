# The service log

What the service writes to its log, at which level, with which fields,
and what never goes into a line. The log is one stream on stderr with
time, level and source, secrets masked, and its newest lines are on a
page for the admin ([CONCEPT 7.4](concept/security.md#74-handling-rules),
[UI.md 6.5](UI.md)). The audit of administration in the database is
[AUDIT.md](AUDIT.md): it stores the activities named here that someone
caused.

This file is the overview. It holds what the log is for, the levels,
the shape of a line, what never goes into one and the rules for
writing one. The rest is in [logging/](logging/), under the same
section numbers.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The activities](logging/activities.md) | 5 | Every line the service writes, one table per area: the level, the line, its fields. |
| [Where the activities live](logging/code.md) | 7 | The package `activity` of the domain: the activities as small classes, one module per area. |

## Every section

- [1. What the log is for](#1-what-the-log-is-for)
- [2. Levels](#2-levels)
- [3. The shape of a line](#3-the-shape-of-a-line)
- [4. What never goes into a line](#4-what-never-goes-into-a-line)
- [5. The activities](logging/activities.md#5-the-activities): [5.1 Lifecycle](logging/activities.md#51-lifecycle) · [5.2 Sign-in and sessions](logging/activities.md#52-sign-in-and-sessions) · [5.3 Users, passwords, tokens, roles](logging/activities.md#53-users-passwords-tokens-roles) · [5.4 Accounts and OAuth](logging/activities.md#54-accounts-and-oauth) · [5.5 Sync and the worker](logging/activities.md#55-sync-and-the-worker) · [5.6 Sending, drafts, idempotency, links](logging/activities.md#56-sending-drafts-idempotency-links) · [5.7 Webhooks](logging/activities.md#57-webhooks) · [5.8 Discovery and the rest](logging/activities.md#58-discovery-and-the-rest) · [5.9 Rate limits](logging/activities.md#59-rate-limits) · [5.10 The MCP server](logging/activities.md#510-the-mcp-server)
- [6. Rules for writing a line](#6-rules-for-writing-a-line)
- [7. Where the activities live](logging/code.md#7-where-the-activities-live): [7.1 Three words](logging/code.md#71-three-words) · [7.2 Names](logging/code.md#72-names)
- [9. Questions answered](#9-questions-answered)

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
line is its module: `common.ratelimit`. The console and the log page show
the source without the package's name in front, the plain lines for a
container or the journal with it. The message is one sentence in the
past tense, in this order:

```
<who> <did what> <to which> [from <where>][: <why>]
```

- **who**: the user's name and id, `admin (usr_7f3a…)`. When the user
  came with a token, the token's name after it: `Claude Desktop
  (usr_91c0…, token laptop)`. The service itself is `the worker`, `the
  dispatcher`, `the outbox`, `the host` for a CLI command.
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
copied from a page, and a prefix would not match. The message has no
key-value pairs, since the log page searches text and a person reads
it.

`MAILBOX_SERVICE_LOG_FORMAT=json` writes each line on stderr as one JSON
object instead, for a log collector: `time` as rule 6.9 says, `level`,
`source` with the package's name, `message`, the same sentence, and
`traceback` where there is one. An access line adds `method`, `path`
without its query, `status` as a number and `client`. A noted secret is
masked in each field before it is encoded. The log page shows text
either way. **Decided 2026-11-22:** JSON as an option for the service,
text stays the default. The MCP server has no such setting.

## 4. What never goes into a line

1. **Secrets**: passwords, one-time passwords, tokens, the recovery key,
   the master key, webhook secrets, OAuth tokens, codes and `state`,
   session ids, CSRF tokens, the secret of a link to an attachment. A
   token is named by its name and id, a link by its id. The access log
   of uvicorn and the lines of 5.9 name the path of a link masked,
   `/v1/links/…`.
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

The masking of `log/redact.py` in `mailbox-common` is the second line of
defence, not the first: a line is written as if there were no masking.

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
   So the IMAP adapter
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
   a secret or mail content. `tests/log/test_lines.py` of
   `mailbox-common` keeps a test that a noted secret is masked in the
   message and the traceback of a line, plain or for a terminal.
8. **The CLI prints, the service logs.** A command talks to the person
   at the terminal on stderr, and a command that changes the database
   (`users`, `keys`, `restore`) records the same as an activity. The
   audit keeps those marked `audited`, which are those of `users`. A
   command sets up no log, so a line below WARNING reaches no handler
   and a warning reaches stderr as Python writes it without one. The
   log page shows the lines of its own process alone.
9. **One time in every line.** Every line writes the time alike, at
   every place and in every format: ISO 8601, the local time of the
   machine, to the millisecond, with the offset:
   `2026-09-30T10:12:22.123+02:00`. That holds for the plain lines, the
   console, the JSON lines, the log page, the MCP server's log and a time inside a
   message, such as the end of a purge. `log_time` in `log/lines.py` of
   `mailbox-common` writes it. **Decided 2026-09-30.**
10. **An activity is one line.** A name or an address a caller chose may
    hold a line break. The recorder writes each break, each other
    control character, each mark that turns the direction of the text
    and a lone surrogate as its escape, such as `\n` or `\u2028`, so no
    value starts a line of its own, turns the line around or makes the
    log drop it. `text.escaped` of `mailbox-common` does it. A traceback
    follows its line as before.

## 9. Questions answered

- **Decided 2026-09-28:** an account is named by its address and its id,
  as section 3 says.
- **Decided 2026-09-28:** each sync pass writes one line with its counts
  at `DEBUG`.
