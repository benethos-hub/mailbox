# Concept: connecting an account

Part of the [concept](../CONCEPT.md): sections 5.8 to 5.11.

## 5.8 Autodiscovery

**Requirement, 2026-09-24:** adding an account starts with the email
address, nothing else. The service works out provider, adapter, servers,
ports, encryption and the kind of credential to ask for. Only what cannot
be discovered is asked for.

```
 user@example.org
      │
      ▼
 discovery  ──►  candidates, ranked, each with its source
      │           "GMX via IMAP, needs an app password, IMAP must be enabled"
      ▼
 person confirms  ──►  credential entered  ──►  verify  ──►  account stored
```

### Everything stays in the service

Discovery and every connection run in the self-hosted service. No account
and no credential is handed to a third-party cloud to sync from there.
Nothing leaves the service except the lookups listed below, and each lookup
that tells a third party which domain is being set up can be switched off.

### Sources, in order

All sources are asked at once, each with a timeout of 10 seconds, so a
slow source does not hold up the result. Their candidates are merged
and ranked: confirmed before unconfirmed, reachable before unreachable,
JMAP before the rest, then by the order of their sources.

| # | Source | What it asks | Covers |
|---|---|---|---|
| 1 | **Own presets** | domain in the built-in list (5.3 as data: servers, credential kind, hints) | the providers we know, with hints no other source has ("switch on IMAP first", "use the email password, not the login") |
| 2 | **ISP autoconfig** | `https://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress=…`, then `https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml` | providers and self-hosters who publish an autoconfig file |
| 3 | **JMAP well-known** | `https://{domain}/.well-known/jmap`, SRV `_jmap._tcp.{domain}` | JMAP servers (5.6) |
| 4 | **ISPDB** | `https://autoconfig.thunderbird.net/v1.1/{domain}`, Thunderbird's shared database | many smaller providers. Tells Mozilla the domain, so it can be switched off |
| 5 | **MX lookup** | MX record of the domain, then sources 1 and 4 for the MX host's base domain | custom domains hosted elsewhere: MX at `google.com` means Google Workspace, at `protection.outlook.com` Microsoft 365, at `mx.ionos.de` IONOS |
| 6 | **Microsoft realm**, planned | Microsoft's user-realm and Autodiscover v2 endpoints for the address | recognises a Microsoft 365 tenant behind any domain **(to verify: exact endpoints and their stability)** |
| 7 | **SRV records**, planned | RFC 6186: `_imaps._tcp`, `_imap._tcp`, `_submission._tcp`, `_submissions._tcp` | mail servers that publish SRV |
| 8 | **Guessing**, planned | `imap.{domain}`, `mail.{domain}`, `smtp.{domain}` on 993/143 and 465/587 | last resort, lowest confidence |

For the IMAP or POP3 server of a candidate the service then reads what
the server announces before a login, for four servers at most. One
that refuses a password login (`LOGINDISABLED`) and offers
`AUTH=XOAUTH2` asks for OAuth. An SMTP server is not asked. The
account's own capabilities are read from the server when the account
connects (5.11, rule 4).

The result tells the person what to do, not just where the server is:

- **Google or Microsoft:** "Sign in with Google", "Sign in with Microsoft".
  The OAuth round trip, no password.
- **Fastmail:** "Create an API token under Settings, Privacy & Security".
- **GMX, web.de, freenet:** "Switch on IMAP in the web mailer first".
- **Yahoo, iCloud, AOL:** "Create an app password".
- **Tuta:** "Tuta offers no access for other programs", nothing to connect.
- **Proton:** "Requires Proton Mail Bridge on this machine, paid plans only".

### Security rules

Autodiscovery decides where a password is sent. That makes it an attack
surface, and a known one: clients that, failing on the real domain, fell
back to `autodiscover.{tld}` have sent credentials at scale to whoever had
registered that domain.

1. **Discovery never sends a credential.** It only looks up and connects
   anonymously (`CAPABILITY`, TLS handshake). The password is entered after
   the result is shown, and goes only to the server the person confirmed.
2. **No fallback outside the domain.** Never `autodiscover.{tld}`, never a
   parent domain that is a public suffix. The Public Suffix List decides
   where a domain ends.
3. **HTTPS only**, with certificate verification, for every autoconfig and
   JMAP lookup. The autoconfig format still allows plain HTTP, this service
   does not.
4. **Trust follows the source.** Presets and results over HTTPS from the
   address's own domain count as confirmed. A server that SRV records, MX
   or guessing point to on a **different** domain is shown as unconfirmed
   and needs an explicit yes. DNS without DNSSEC can be forged.
5. **TLS is required.** Candidates without TLS or STARTTLS are dropped, and
   a STARTTLS offer is followed, never skipped.
6. **No requests into the local network.** Discovery makes the service
   connect to addresses derived from user input, which is how server-side
   request forgery works. Hosts resolving to private, loopback or
   link-local addresses are refused, unless an operator allows a list of
   internal mail servers in the settings. The same check runs on the
   hosts in an account's settings (`host`, `smtp_host`) when the account
   is created or changed, before the first connection: `400`. Every
   connection runs the check again, the probes of discovery and each
   connection of an adapter to IMAP or SMTP. It goes to the address just
   checked, with TLS verified against the host name, so a DNS answer that
   changes later cannot point the service inward.
7. **Safe XML.** Autoconfig files are parsed with `defusedxml`, never the
   plain standard-library parser, so a hostile file cannot expand entities
   or read local files.
8. **Limits.** Short timeouts, a cap on redirects and response size, a rate
   limit per user, and results cached per domain for a day.
9. **Privacy switches.** ISPDB and the Microsoft lookup (planned) each
   tell a third party which domain is being set up, and each can be
   switched off. The other sources only talk to the domain itself.

### In the API

| Method | Path | Right | Purpose |
|---|---|---|---|
| POST | `/v1/discovery` | `accounts.connect` | body `{"email": "…"}`, returns ranked candidates |

POST rather than GET, so the address does not end up in access logs. A
candidate carries: adapter, servers with host, port and encryption, the
credential kind to ask for, OAuth provider if any, hints with help links,
`source`, `confirmed` (4 above), and for the server it reads mail from
what that one announced.
`POST /v1/accounts` then takes the chosen candidate plus the credential, and
verifies before it stores (7.4). The configuration UI is the main user:
address field, result, then either an OAuth button or a password field.

### In the code

Each source is a module under `data/discovery/`, behind one
`DiscoverySource` protocol, so a source can be added, removed or switched off
without touching the others. `domain/discovery/` runs them, applies the
security rules, ranks and merges. The presets are data, one file, shared
with the provider hints of 5.3. Its dependencies, each wrapped in one
module: `dnspython` for MX and SRV (the standard library cannot query them),
`defusedxml` for the XML, `publicsuffixlist` for where a domain ends.

**Decided 2026-09-24:** the Public Suffix List is the copy bundled with
`publicsuffixlist`, updated with the package, no download at runtime. It is
wrapped in one module so a live list can be added later.

## 5.9 Being a good client

Providers protect themselves against clients that log in too often or ask
too much. GMX, web.de and T-Online answer with a CAPTCHA or a temporary
lock, and a locked account also locks out its owner's other mail programs.
The service therefore behaves conservatively towards every provider:

- **One rate limiter per IMAP or POP3 account.** Every request to its
  server passes it, retries and paging follow-ups included: 60 requests
  a minute with a burst of 10, set by
  `MAILBOX_SERVICE_IMAP_REQUESTS_PER_MINUTE` and
  `MAILBOX_SERVICE_IMAP_BURST`, or for one account by its
  `max_requests_per_minute`. No preset carries a limit.
- **Few connections.** One IMAP connection per account for commands, a
  second one only for `IDLE`. Never one per API request.
- **A failed login is not retried.** After one authentication failure the
  account goes to `needs_reauth`, the event `account.needs_reauth` is raised,
  and nothing tries that credential again until it is replaced or a person
  runs `verify`. Repeating a wrong password is exactly what triggers a lock.
  A connection the server drops during the login is not a failed login:
  it is retried like any other dropped connection.
- **Backoff on everything else.** Timeouts, connection errors, `429` and
  `503` are retried with exponential backoff and jitter, `Retry-After` is
  honoured (Graph's as a pause during which nothing is sent), and a
  persistently unreachable account is shown as `unreachable` rather than
  hammered: 3 attempts, then a rest of 30 seconds doubled up to 15
  minutes, set by `MAILBOX_SERVICE_IMAP_ATTEMPTS`,
  `MAILBOX_SERVICE_IMAP_FIRST_PAUSE` and
  `MAILBOX_SERVICE_IMAP_LONGEST_PAUSE`. A retried step must not do its
  work twice: an IMAP `APPEND`
  is preceded by a search for the message's `Message-ID`, so a draft or a
  sent copy stored before the connection dropped is found, not stored
  again.
- **Push before polling.** `IDLE` where offered, renewed before the 29
  minutes of RFC 2177 run out. Each watched account waits in a thread of
  its own, outside the pool that answers requests, at most
  `MAILBOX_SERVICE_SYNC_WATCHERS` (50) at once. Further accounts are
  polled only. Every account is polled at one interval,
  `MAILBOX_SERVICE_SYNC_INTERVAL`, 300 seconds by default.
- **Say who we are.** The IMAP `ID` command (RFC 2971) sends name and
  version where the server supports it. Some providers require it.

## 5.10 Encodings and other traps

What the adapters handle, covered by tests:

- **Folder names** travel in modified UTF-7 (RFC 3501): "Entwürfe" arrives as
  `Entw&APw-rfe`. `UTF8=ACCEPT` (RFC 6855) is not used. The API only
  ever shows the decoded name.
- **Special folders without `SPECIAL-USE`.** Many servers name them in the
  mailbox language: Gesendet, Entwürfe, Papierkorb, Spam, Archiv. A name
  list per language maps them to roles when the server announces none.
- **Headers** in RFC 2047 encoding, with wrong or missing charset
  declarations. Decoding falls back to a detected charset rather than
  failing the whole message.
- **Internationalised domains** (IDN): punycode on the wire and in DNS
  (autodiscovery), Unicode in the API.
- **Addresses with non-ASCII local parts** need SMTPUTF8 (RFC 6531). Sent
  only when the server announces it, otherwise refused with a clear error.
  Domains go in punycode on the envelope.
- **Bodies are composed 7bit clean**: text beyond ASCII is encoded, since
  the service asks no SMTP server for 8BITMIME.
- **Dates** in every format a `Date` header has ever carried. Stored and
  returned in UTC with offset.

## 5.11 One way to operate every mailbox

**Decided 2026-10-12, built in phase 5a.** From outside, every mailbox is
operated the same way. Whatever is common behaves identically on every
account. Whatever an account cannot do answers an error, and the
account says so in advance. Nothing is silently ignored, and no value
silently means something else.

An inventory of every adapter found where the API broke this, and
0.5.0 ended it. [UNIFORM.md](../UNIFORM.md) holds the decisions, the
reasons and what still differs per provider. The rules:

1. **One meaning.** Every field, filter and operation means the same on
   every account. Where a provider cannot deliver it, the adapter does
   not approximate it. The capability is missing instead.
2. **Missing means `501`.** Never `200` with nothing done, never `400`,
   `404` or `409` for "the provider cannot".
3. **Announced in advance.** Every `501` follows from a missing
   capability. The domain checks it once for every operation, from one
   table of what each operation needs. Only what the call itself shows
   answers `501` without one, such as a role the account has no folder
   for, an IMAP `update_draft` without UIDPLUS or a JMAP method the
   server does not know (UNIFORM.md R3 names them all).
4. **Capabilities follow the server.** IMAP and JMAP servers are asked
   what they offer when an account connects, when it is verified, when
   the sync sees a folder come or go, and when the server refuses what
   was stored.
   The capabilities are stored with the account.
5. **Unknown is not false.** A missing capability says that a field
   carries nothing. The value itself stays as it is.
6. **All or nothing.** An operation that answers an error has changed
   nothing. Where that cannot be guaranteed, the answer names what was
   done.
7. **The service fills gaps only where the result is the same.** It
   emulates the folder `all` on Microsoft, on IMAP servers without
   `\All` and on JMAP servers without a mailbox of that role.
8. **Provider specifics stay out of the common fields.** Notes a server
   keeps for itself, such as `$hasnoattachment`, leave `keywords`.

The capabilities are finer, each guarding one thing: `read_state`,
`stars`, `keywords`, `folders`, `move`, `trash`, `purge`, `labels`,
`search`, `drafts`, `send`, `sent_copy`, `threads`, `push`,
`external_changes`, `refused` and `sender_check` (6.3). The marks are two lists on the
account, `marks.read` and `marks.written`: the marks of RFC 8621 it
reads and those it writes.

Further decisions: `date` is the Date header everywhere, and the
field `received` carries the received time, by which lists sort and
filter. A list without a folder is the inbox on every account, and the
role `all` searches everywhere but the trash and junk. Keywords keep the
provider's spelling. `has_attachments` counts real attachments, not
inline images, the same way everywhere. Each provider groups threads by
its own rules. A reply answers whether the original was marked.

**The search runs on the provider's server.** How text matches is
therefore the provider's: every account finds whole words, IMAP also
parts of words, Microsoft beginnings of words **(to verify)**. The
contract promises whole words.

**The UI and the MCP server know no providers.** The API answers per
account the operations its caller can run there, capabilities and
rights together. The UI and the MCP server ask that list, and the
account's `capabilities` for what it cannot do at all, and the marks
with their words come from `mailbox-common`. Setting up an account is
the one place that knows the kinds of account. The domain describes
each kind's connection, and the UI draws the form from it.
