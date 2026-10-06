# Limits

Every limit the service enforces, and how the limits work together. The
service limits callers to protect itself and to slow down guessing. It
paces itself to protect the mail servers of its accounts, whose owners
get locked out when a client asks too much (CONCEPT 5.9).

The numbers below are the defaults. Most limits are settings of the
service, `MAILBOX_SERVICE_*` in its `.env`, named in the column "Set
by". What each limit logs is in [LOGGING.md](LOGGING.md) 5.9. How to
report a weakness is in [SECURITY.md](../SECURITY.md).

## 1. Overview

Towards the callers of the service:

| Limit | Counts | Default | Past it | Set by |
|---|---|---|---|---|
| Requests with a credential | per API token, per UI session | 120 a minute, 60 at once | `429 rate_limited` | `MAILBOX_SERVICE_RATE_LIMIT_PER_MINUTE` |
| Requests without a credential | per client address | 30 a minute, 15 at once | `429 rate_limited` | `MAILBOX_SERVICE_RATE_LIMIT_ANONYMOUS_PER_MINUTE` |
| Request body | per request | 40 MB | `413` | fixed |
| Failed sign-ins per address | wrong API tokens and wrong UI passwords alike | 10 in 15 minutes lock the address for 15 minutes | `429 rate_limited` for a wrong credential, the UI names the minutes. A valid token passes. | `MAILBOX_SERVICE_SIGN_IN_FAILURES`, `MAILBOX_SERVICE_SIGN_IN_LOCKOUT_MINUTES` |
| Failed sign-ins per name | UI password, the password asked again before the recovery key | 10 in 15 minutes, from any address, make the name wait 1 minute | `429 rate_limited` | the same failures, `MAILBOX_SERVICE_SIGN_IN_NAME_WAIT` |
| Password hashes | at once, for the whole service | 2 | the next one waits | `MAILBOX_SERVICE_PASSWORD_HASHES_AT_ONCE` |
| UI session | per session | ends after 8 hours without a request | sign in again | `MAILBOX_SERVICE_SESSION_IDLE_HOURS` |
| Discoveries | per user | 10 in any minute, each domain's findings kept a day | `429 rate_limited` | `MAILBOX_SERVICE_DISCOVERY_PER_MINUTE`, the day is fixed |
| Sends | per user and account, under a grant | `max_sends_per_day` in any 24 hours | `429 send_limit_reached` | the grant |

Towards the mail servers:

| Limit | Counts | Default | Past it | Set by |
|---|---|---|---|---|
| IMAP pace | per account, commands and SMTP sends | 60 a minute, 10 at once | the request waits | `MAILBOX_SERVICE_IMAP_REQUESTS_PER_MINUTE`, `MAILBOX_SERVICE_IMAP_BURST`, the account's `max_requests_per_minute` |
| Unreachable server | per account | 3 attempts with backoff, then a pause of 30 seconds, doubled up to 15 minutes | `502 provider_unavailable`, the account shows `unreachable` | `MAILBOX_SERVICE_IMAP_ATTEMPTS`, `MAILBOX_SERVICE_IMAP_FIRST_PAUSE`, `MAILBOX_SERVICE_IMAP_LONGEST_PAUSE` |
| Rejected login | per account | no new attempt until the credential is replaced or the account is verified | `502 provider_auth_failed`, the account shows `needs_reauth` | fixed |
| Watched accounts | for the whole service | 50 at once, an IMAP one waiting in IDLE in a thread of its own, a JMAP one on its event source | further accounts are polled only | `MAILBOX_SERVICE_SYNC_WATCHERS` |
| Microsoft Graph | per account | a pause as long as Graph's `Retry-After` | `502 provider_unavailable` | Graph |
| JMAP server | per account | as many requests at once as the session's `maxConcurrentRequests`, 4 where it names none, and a pause as long as its `Retry-After` | the request waits, or `502 provider_unavailable` during the pause | the server |
| Webhook posts | per webhook | 8 attempts, 30 seconds after the first failure, doubled up to 1 hour, 10 seconds to answer | the events are dropped | `MAILBOX_SERVICE_WEBHOOK_*` |

Every `429` carries `Retry-After` in seconds. A limit of `0` switches the
limit on requests off. The other limits can be set, not switched off.

## 2. A request, step by step

The limits apply in this order. The first that refuses answers.

1. **Before the app.** A request without a credential counts against its
   client address. A credential is a bearer token on a path under `/v1`
   or a session of the UI the service knows. `/health` is never counted.
2. **While the body is read.** A body above 40 MB is refused as soon as
   it grows past the limit.
3. **The credential.**
   - API without a token: `401`. It counted against its address in
     step 1, and counts no failure.
   - API with a token: a wrong, expired or revoked token counts a
     failure for the address and answers `401`, or `429` while the
     address is locked out. A valid one passes, locked out or not, and
     counts against the token.
   - UI with a session: the request counts against the session.
   - The UI's sign-in form: the address's lockout and the name's wait
     first, then the password is hashed, two at a time.
4. **The domain.** Rights first (`403`, or `404` for an account the
   caller may not see). Then the discovery limit, or the send limit,
   where only mails that went out count.
5. **The mail server.** The account's pace makes the request wait. A
   rejected login, an unreachable server or a pause Graph or a JMAP
   server asked for refuses it.

## 3. How they work together

**Refused or slowed.** The limits towards the callers refuse at once and
say when to come back. The pace towards a mail server makes a request
wait instead, so it takes longer. A waiting request holds a worker
thread. A client that works on one IMAP account meets the pace of 60 a
minute before its own limit of 120, as far as its requests reach the
server.

**A wrong token.** A request with a bearer token under `/v1` passes the
limit per address, and a wrong token is left to the sign-in throttle.
After 10 failures within 15 minutes the address is locked out for 15
minutes: every wrong token from it answers `429`, without being told
that it is wrong. A valid token passes during the lockout and clears no
failures. A token cannot be guessed, so the lockout hides nothing a
valid token could reveal, and a client with a stale token behind an
address it shares with others must not stop them. A session of the UI
is not checked against the lockout either. Only a successful sign-in in
the UI clears the failures of its address.

**Guessing a password.** A sign-in in the UI takes two requests without
a credential: the page and the form. With 30 a minute per address that
allows about 15 attempts a minute, and the tenth failure locks the
address. The limit per name covers guessing from many addresses: 10
failures at one name make it wait a minute, from anywhere, so its owner
is never locked out for long. Two hashes at a time keep a flood of forms
from taking the memory. The others wait.

**Many clients at one address.** Behind a reverse proxy the service sees
the proxy's address, unless `MAILBOX_SERVICE_FORWARDED_ALLOW_IPS` names
the proxy. Then every visitor shares the 30 requests a minute without a
credential and one lockout. Signed-in callers keep their own limit per
token or session, and a lockout of the shared address stops only the
wrong credentials behind it: a client with a stale token is refused,
the others pass.

**The MCP server.** It calls the API with one token, so all its tools
share one limit of 120 a minute. Its start asks `/v1/me` and the folders
of every account, which fits into the 60 that pass at once. Past the
limit the model reads "too many requests, try again in N seconds".

**Sending.** A send passes the limit on requests, then the grants: their
recipients and their `max_sends_per_day`. A refused or failed attempt
sent nothing and does not count. A repeated request with the same
`Idempotency-Key` within 24 hours answers the first result and sends
nothing again. Its SMTP connection passes the account's pace like any
IMAP command.

**Discovery.** It counts per user, 10 in any minute. A domain looked up
within the last day is answered from the cache and reaches no host, but
it still counts.

**The log.** Each limit writes one line when it engages, not one per
refused request: a lockout when it starts and when it ends, a limit on
requests when a caller first runs out. The access log has every refused
request.

## 4. State

The limits on requests, the sign-in throttle, the discovery counts and
the paces are kept in memory, in the one process of the service. A
restart forgets them. Each is capped, so spoofed addresses cannot grow
the memory: 10,000 addresses or callers, the one idle longest forgotten
first, and 1,000 domains in the discovery cache. The sign-in throttle
forgets failures before lockouts, and of the lockouts the one that ends
soonest.

The send limit counts the audit of sends in the database, and the
results of an `Idempotency-Key` are stored there for 24 hours. Both
survive a restart.
