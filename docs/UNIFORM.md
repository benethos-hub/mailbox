# One way to operate every mailbox

**Decided 2026-10-12.** This file collects where the API behaves
differently per provider today and sets the rules that end that. The
decisions are in section 6, and section 7 names what the change
carries along. Section 8 makes the UI and the MCP server independent
of the providers. Section 5 is the work list. The rules stand in
CONCEPT 5.11, the work in ROADMAP phase 5a.

Contents:
[1. The principle](#1-the-principle) ·
[2. Rules](#2-rules) ·
[3. Capabilities](#3-capabilities) ·
[4. Where the API breaks the principle today](#4-where-the-api-breaks-the-principle-today) ·
[5. Work in order](#5-work-in-order) ·
[6. Decisions](#6-decisions) ·
[7. What belongs to it](#7-what-belongs-to-it) ·
[8. The UI and the MCP server without provider knowledge](#8-the-ui-and-the-mcp-server-without-provider-knowledge)

## 1. The principle

From outside, every mailbox is operated the same way. Whatever is common
behaves identically on every account. Whatever an account cannot do
answers an error, and the account says so in advance. Nothing is
silently ignored, and no value silently means something else.

The service is already built on this idea: neutral models, capabilities
per account, `501 not_supported` for what an adapter lacks (CONCEPT 5).
An inventory of all five adapters and the domain on 2026-10-12 found
where it does not hold. Section 4 lists what it found.

## 2. Rules

**R1. One meaning.** Every field, filter and operation means the same on
every account. Where a provider cannot deliver that meaning, the
adapter does not approximate it. The capability is missing instead.

**R2. Missing means 501.** An operation an account cannot do answers
`501 not_supported`. Never `200` with nothing done, and never `400`,
`404` or `409` for "the provider cannot". Those stay for errors of the
request or the state of the mailbox. A keyword the request spells wrong
is a `400`, a keyword the account cannot keep is a `501`.

**R3. Announced in advance.** Every `501` follows from a missing
capability that `GET /v1/accounts/{id}` lists. The domain checks it once
for every operation, before the adapter is called. A client never has
to try an operation to learn whether it works.

**R4. Capabilities follow the server.** An IMAP or JMAP server is asked
what it offers when the account connects and when it is verified: IDLE,
MOVE, UIDPLUS, CONDSTORE, PERMANENTFLAGS, the special folders, JMAP
submission and event source. The capabilities follow from the answer,
not from the adapter's class.

**R5. Unknown is not false.** A value the provider does not keep is not
read as a fact. A missing capability says that the field carries
nothing (decision 6.1).

**R6. All or nothing.** An operation that answers an error has changed
nothing. Where that cannot be guaranteed, the steps run in the order
that leaves the least behind, and the answer names what was done. An
IMAP change of flags and folder in one request is such a case: IMAP
has no transaction over both.

**R7. The service fills gaps only where the result is the same.** The
domain emulates what a provider lacks only when a client cannot tell the
emulation from the native feature. Otherwise the capability is missing.

**R8. Provider specifics stay out of the common fields.** What only one
provider has, and what a server notes for itself, stays out of the API.

## 3. Capabilities

Today one capability often covers things that differ per provider.
`flags` covers read state, stars and keywords, although Gmail has no
keywords and Microsoft has no `$` keywords. The finer set, where each
one guards exactly one thing:

| Capability | Means | IMAP | POP3 | Gmail | Microsoft | JMAP |
|---|---|---|---|---|---|---|
| `read_state` | `unread` is kept and can be set | yes | no | yes | yes | yes |
| `stars` | `starred` is kept and can be set | yes | no | yes | yes | yes |
| `keywords` | own keywords, without `$` | if the server keeps them | no | no | yes, as categories | yes |
| `marks` | which marks of RFC 8621 the account reads, and which it writes | those the server keeps | none | reads `$draft` | reads `$draft`, `$answered` and `$forwarded` after a live check (6.4), writes the last two | all |
| `folders` | folders: create, rename, delete | yes | no | yes | yes | yes |
| `move` | moving messages | with MOVE or UIDPLUS | no | yes | yes | yes |
| `trash` | delete into the trash | with a trash folder and `move` | no | yes | yes | yes |
| `purge` | delete for good | with UIDPLUS | yes | yes | yes | yes |
| `labels` | a message in several folders | no | no | yes | no | yes |
| `search` | the filters of `list_messages` | yes | no | yes | yes | yes |
| `drafts` | drafts | with a drafts folder | no | yes | yes | yes |
| `send` | sending | with SMTP | with SMTP | yes | yes | with submission |
| `sent_copy` | a sent mail is kept and its id answered | with a sent folder | no | yes | yes | with a sent folder |
| `threads` | `thread_id`, `list_threads`, `get_thread` | yes, the service's own | no | yes | yes | yes |
| `push` | changes arrive within seconds | with IDLE | no | no | no | with an event source |
| `external_changes` | the change feed sees read state, stars and keywords changed by other clients | with CONDSTORE | no | yes | yes | yes |

The marks are the keywords RFC 8621 names besides `$seen` and
`$flagged`, which are `unread` and `starred`: `$answered`,
`$forwarded`, `$draft`, `$junk`, `$notjunk` and `$phishing`. The list
draws the line between a mark and a server note (4.1). Other `$`
keywords, such as `$important` or Thunderbird's `$label1`, pass as
keywords, as today.

A yes or no would be too coarse for `marks`, as it is for `flags`
today. Microsoft could keep `$answered` and `$forwarded` but no
`$junk`, and Gmail shows a draft by its label but cannot set `$draft`.
So `marks` is not one capability but two lists on the account: the
marks it reads and the marks it writes. Writing a mark outside the
second list answers `501`. A mark outside the first list never appears,
and its absence means nothing.

`refused` (decision 6.1) needs a capability as well: whether the
provider names the recipients it refuses while sending, as SMTP does.
Gmail, Microsoft and JMAP report them later, as a bounce mail. Its name
is settled with step 5 of section 5.

`stable_ids`, `delta` and `server_search` describe how the service works
inside, not what a client can do. They leave the API (decision
6.8).

## 4. Where the API breaks the principle today

Each point names what happens, on which provider, and what the rules
would make of it. **Bug** marks what is wrong under today's documentation
and can be fixed without a decision. **Concept** marks what follows from
a decision of section 6 and changes the contract. **Work** marks a
larger piece that is neither, and runs on its own.

### 4.1 Keywords and marks

- **Microsoft drops `$` keywords without an error.** Setting `$answered`
  or `$junk` answers `200`, and nothing is stored
  (`microsoft/mappers.py:149`). A `message.updated` record is written
  anyway. Rule R2: `501`. *Bug.*
- **Gmail announces `flags`, and every keyword change answers `501`**
  (`gmail/messages.py:110`). The UI offers the keyword form on Gmail
  accounts, against CONCEPT 5 ("the UI offers no action an account
  cannot do"). Rule R3: the capability `keywords` is missing. *Concept
  (section 3).*
- **`keywords: []` means "none" on IMAP and JMAP, but "not kept" on
  Gmail and POP3.** Microsoft never reads `$answered` or `$forwarded`.
  A client cannot tell "not answered" from "unknown". Rule R5. *Concept
  (6.1).*
- **Server notes travel as keywords.** `$hasattachment`,
  `$hasnoattachment`, `$mdnsent`, `$submitpending` and `$submitted` come
  through from IMAP and JMAP. `$hasattachment` repeats
  `has_attachments`, the others are the server's own bookkeeping. Rule
  R8: they leave `keywords`. *Concept (6.2).*
- **Keywords come back in lower case**, also Outlook categories with
  spaces or other letters. Such a category cannot be sent back through
  `add_keywords`, because the keyword pattern refuses it (422). *Concept
  (6.3).*
- **One vocabulary for display.** The words for the marks live in the
  UI only (`web/pages/templates.py`). The MCP server shows them raw.
  With the fixed list of marks, the list and its words move to
  `mailbox-common`, used by the UI and the MCP server.

### 4.2 Listing without a folder, and across accounts

- **`list_messages` without `folder` lists every folder on Gmail,
  Microsoft and JMAP, trash and junk included, and the inbox on IMAP and
  POP3.** The same call means two things. It is documented, but against
  R1. The MCP tool `search_messages` inherits it. *Concept (6.5).*
- **`list_all_messages` with a role leaves out an account that has no
  such folder**, without naming it in `incomplete`
  (`domain/mailbox/across.py:111-116`). *Bug.*
- **An account without the folder a role names answers `404` from the
  domain and `409` from the adapters**, for the same situation. Gmail
  has no `archive`, Microsoft no `all` folder. Rule R2: `501`, except
  for Microsoft's `all`, which the adapter emulates. *Concept (6.5).*

### 4.3 Dates and order

- **`date` is the received time on Microsoft** (`receivedDateTime`) and
  the Date header, the sender's time, everywhere else. Microsoft does not
  read `sentDateTime` at all. A list across accounts sorts by `date` and
  mixes both. *Concept (6.6).*
- **The `after` and `before` filters compare the received time
  everywhere**, while `date` shows the Date header. A message can show a
  date outside the range it was found with. *Concept (6.6).*
- **IMAP lists newest first by UID**, which is arrival order. JMAP and
  Microsoft sort by received time. Since the list across accounts merges
  by `date` and pages by count, IMAP messages whose UID order differs
  from their date order can be skipped or repeated between pages. *Bug.*
- **Days count in UTC** on Gmail, Microsoft and JMAP, and in the
  server's day on IMAP.

### 4.4 Search and attachments

- **IMAP matches parts of words** ("ail" finds "mail"), as IMAP `SEARCH`
  compares. **Gmail and Microsoft match whole words or prefixes**, JMAP
  as its server does. No adapter can make the provider's index match
  parts of words. *Concept (6.7).*
- **On Microsoft, `sender`, `to` or `subject` switch the list to Graph's
  `$search`.** `unread`, `starred` and `has_attachments=false` are then
  checked after each page, so a page can come back short or empty with
  a `next_cursor`. Documented with 6.7.
- **A Microsoft cursor keeps its first query.** Sent with another folder
  or filter, it answers the old query's next page, without
  `invalid_cursor` (`microsoft/provider.py:147-151`). *Bug.*
- **`has_attachments` can come out three ways for one message.** The
  field in a list is a header guess (`multipart/mixed`), `get_message`
  counts the parts, and the filter is the provider's own. *Concept
  (6.10).*

### 4.5 Sending

- **A reply or forward marks the original only on IMAP and JMAP.** On
  Gmail and POP3 the mark answers `501`, on Microsoft it is dropped. The
  send answers success either way, and only the log knows
  (`domain/mailbox/outgoing.py:446-456`). Rule R6: the answer says
  whether the original was marked. *Concept (6.4).*
- **A reply through Gmail starts a new Gmail thread.** The send and the
  draft pass no `threadId` (`gmail/sending.py:28, 45`). Gmail's
  documentation asks for it besides the headers, so a reply lands outside
  the original's thread. To confirm live. *Bug.*
- **Microsoft answers no `sent_copy_id`**, although Exchange keeps the
  copy (`microsoft/provider.py:259`). The `message.sent` record then
  carries the Message-ID header in place of a message id. *Bug.* Done:
  the mail is sent as a draft, whose immutable id the copy keeps, the
  way Microsoft documents.
- **POP3 keeps no sent copy**, while `send_message` is documented as
  keeping one. JMAP without a sent folder keeps none either, without a
  word. Capability `sent_copy`. *Concept (section 3).*
- **`refused` is always empty on Gmail, Microsoft and JMAP.** They report
  refused recipients later, as a bounce mail. Empty means "unknown"
  there, but "all accepted" on SMTP. *Concept (6.1).*
- **Microsoft refuses mail above about 3 MB** with a general provider
  error, while the domain allows 25 MiB of attachments. Graph takes at
  most 4 MB per request, and the MIME travels in base64. Larger mail
  needs Graph's upload sessions. *Work.*
- **A send without SMTP answers `409`** on IMAP and POP3, JMAP without
  submission `501`. Rule R2: `501` for both.

### 4.6 Drafts

- **A Gmail draft never shows its `reference`.** The domain keeps it only
  where `$draft` is among the keywords (`domain/mailbox/service.py:196`),
  and Gmail has no keywords. *Bug.*
- **A replaced draft keeps its id on IMAP and gets a new one elsewhere.**
  Documented with the draft id.
- **Replacing a draft can leave two**, with an error, on Microsoft and on
  IMAP without UIDPLUS: the new one is stored before the old one is
  deleted. Rule R6. *Bug.*
- **IMAP and JMAP announce `drafts` without a drafts folder** and answer
  `409` later. Rule R4.

### 4.7 Folders

- **An IMAP folder's id changes when it is renamed**, and so do the ids
  of its subfolders. Documented. The subfolders also lose their
  subscription.
- **Folder counts are null on IMAP and POP3**, and on Gmail's All Mail.
  Microsoft, JMAP and other Gmail labels fill them.
- **Gmail's own folders refuse neutral operations with `400`**: no
  subfolder in the inbox, no move into Sent or Drafts. Rule R2.
- **Microsoft shows Outbox, Conversation History and similar folders
  without a role**, as if a person had made them. Renaming them fails at
  Graph with a general error.
- **IMAP drops `\Noselect` folders but keeps them as `parent_id`** of
  their children. *Bug.*

### 4.8 Message fields

- **`snippet` is always null on IMAP and POP3**, also in `get_message`,
  where the body is known.
- **Microsoft answers HTML only.** A plain text mail has
  `text_body: null` and Exchange's HTML in `html_body`. Graph answers the
  text with `Prefer: outlook.body-content-type="text"`. *Bug.* Done,
  otherwise than proposed: the text Graph answers is Exchange's
  conversion, which no other provider gives. A message is read from its
  MIME, as on Gmail and IMAP.
- **Microsoft answers `in_reply_to: null`** on every mail but drafts.
  *Bug.* Done, from the MIME.
- **Microsoft lists no attachments for a mail whose only parts are
  inline images**, so they cannot be downloaded. *Bug.* Done, from the
  MIME. Attachment ids are then those of the other providers.

### 4.9 Threads

- **`list_threads` answers an empty page on POP3**, while the route
  documents `501`. No capability check runs (`domain/mailbox/threads.py`).
  *Bug.*
- **Providers group differently.** The service threads IMAP by headers
  only. Gmail and Exchange use their own rules, which include the
  subject. JMAP depends on the server. *Concept (6.9).*
- **An IMAP thread id can be null until the backfill reaches the
  message, and a merge turns the younger id into a `404`.** Native
  thread ids never do either.
- **Microsoft cuts long conversations at the pages read first**, which
  may not be the newest messages. Marked unverified in the code.

### 4.10 The change feed

- **IMAP without CONDSTORE never reports read state, stars or keywords
  changed by another client.** Nothing tells a client. Capability
  `external_changes`.
- **IMAP announces `push` without IDLE, and JMAP without an event
  source.** The worker quietly polls instead. IDLE watches the inbox
  only. Rule R4.
- **A JMAP deletion carries no folder.** A message in several folders is
  reported with one of them.
- **`message.updated` also means a thread merge**, documented as "moved
  or flags changed".
- **After an expired JMAP state, messages that arrived in the gap are
  never reported as created.** *Bug.*

### 4.11 Errors and partial effects

- **The same lack answers different codes**: `409` (send without SMTP,
  drafts without a folder, no trash), `400` (several folders without
  `labels`, Gmail's own folders), `404` (a missing role folder, POP3
  folder changes), `200` (POP3 `list_threads`, Microsoft `$` keywords).
  Rule R2.
- **An IMAP change of flags and folder in one request** stores the
  flags, then fails the move with `501`. IMAP has no transaction over
  both, so R6 can only order the steps: check the move first, then
  store. *Work.*
- **Other partial effects with an error**: a batch across IMAP folders
  fails after earlier folders are done. Microsoft's delete for good moves
  to the trash, then deletes, and can stop in between. Rule R6. *Bug.*
- **A JMAP `forbidden`**, as from a read-only token, likely becomes
  `502 provider_auth_failed` and sets the account to `needs_reauth`.
  To verify.
- **The domain checks protocols, not capabilities.** `search`, `labels`
  and `send` are not checked by the domain at all. Each adapter refuses
  in its own way. With R3 the domain checks the capability once for
  every operation.

## 5. Work in order

Step 1 is done. Each step is one pull request or more.

1. **Bugs without a live check**, together on a branch of their own,
   against today's documentation. Done:
   1. POP3 `list_threads` answers `501`. Done.
   2. A Gmail draft keeps its `reference`. Done.
   3. Microsoft answers `501` for `$` keywords. Done.
   4. The Microsoft cursor checks its query. Done.
   5. `list_all_messages` names an account without the role in
      `incomplete`. Done.
   6. IMAP keeps no `\Noselect` folder as a `parent_id`, or lists it.
      Done: its subfolders go below the nearest listed folder.
   7. After an expired JMAP state, the messages of the gap are reported
      as created. Done, for Gmail and Microsoft as well.
   8. A replaced draft never leaves two: where the old one cannot be
      deleted, the answer still names the new one. Done: the new one is
      taken back, and only where that fails too the error names it.
   9. A batch across IMAP folders, and Microsoft's delete for good,
      answer what was done before a step failed. Done, for the batches
      of every adapter.
   10. The list across accounts pages IMAP messages without skipping
       or repeating them, though IMAP orders by UID. Done.
2. **Bugs with a live check** against the test accounts, in this order:
   1. Gmail sends a reply and a draft with the original's `threadId`.
      Done, checked live.
   2. Microsoft answers the text body and `in_reply_to`. Done, from
      the MIME, checked live.
   3. Microsoft answers the sent copy's id, and lists the attachments
      of a mail with inline images only. Done. The sent copy is checked
      live, the inline images offline: the test account holds no such
      mail, and the check sends none to it.
3. **Work**, each on its own:
   1. Microsoft sends large mail through upload sessions. Last, since it
      moves the most code.
   2. IMAP orders the steps of a change of flags and folder.
4. **One test suite for all adapters** (section 7), first with today's
   capabilities.
5. **Capabilities.** The finer set of section 3, read from the server
   (R4), stored as decision 6.11 says, checked by the domain for every
   operation (R3), `501` for every lack (R2). The client, the UI and
   the MCP server follow them (section 7).
6. **Values.** The decisions of section 6: dates, the list without a
   folder, server notes, marks, the case of keywords, `has_attachments`.
7. **IMAP emulates `all`** where the server has no `\All` (decision
   6.5), a piece of its own.
8. **The UI and the MCP server** (section 8, U1 to U5): the vocabulary
   of the marks in `mailbox-common`, and the operations an account
   offers its caller, read from the API.
9. **Setting up an account, described by the domain** (section 8, U6).

Steps 5 and 6 change the contract. With 7 and 8 they ship together as
0.5.0, marked as breaking in the changelog. Steps 1 to 4 can ship
earlier, in a patch release, since they keep the contract.

## 6. Decisions

Decided 2026-10-12, each with the options weighed and why.

1. **Unknown values.** `unread`, `starred`, `keywords` and `refused`
   answer `false` or `[]` where the provider keeps nothing.
   (a) The capability says so and the value stays as it is.
   (b) The field becomes null where it is unknown.
   *Decided: (a).* No break. The capability says what a value
   means, while null would hit every client and the UI.
2. **Server notes** (`$hasattachment`, `$hasnoattachment`, `$mdnsent`,
   `$submitpending`, `$submitted`). (a) Left out of `keywords`. (b) Kept,
   in a field of their own. (c) As today.
   *Decided: (a).* `$hasattachment` repeats a field, the others are
   the server's own bookkeeping. The marks of RFC 8621 stay.
3. **Case of keywords.** (a) As today, in lower case, with Outlook
   categories outside the keyword pattern not writable. (b) As the
   provider spells them, compared without case.
   *Decided: (b).* Outlook categories must go out as they came in.
   An IMAP keyword with a space stays a rule of the account: there a
   `400` is right, since the request is invalid, not the capability
   missing.
4. **Marks where the provider has no place for them.** Gmail stores no
   `$answered`. Exchange keeps "answered" and "forwarded" in a property
   of its own (`PidTagLastVerbExecuted`), readable through Graph's
   extended properties and very likely writable, which is not checked.
   (a) Microsoft reads and writes it, Gmail writes no marks. (b) Neither
   writes marks.
   *Decided: (a), subject to a live check* against the Microsoft
   test account. If it fails, (b) holds for Microsoft. Either way, the
   send answers whether the original was marked, and the account's
   lists of marks (section 3) say so in advance.
5. **A list without a folder.** (a) The inbox, on every account. (b)
   Every folder, on every account, which IMAP would have to emulate
   folder by folder. (c) The folder becomes required.
   *Decided: (a), with the role `all`* as the explicit "search
   everywhere", where the account has such a folder (Gmail's All Mail, a
   JMAP server's, an IMAP server's `\All`), and `501` elsewhere.
   Otherwise the MCP server loses the search across all folders on
   Gmail. An account without the folder of a role answers `501` (R2),
   and across accounts it is named in `incomplete`.
   **Microsoft emulates `all`:** every folder but the trash and junk, as
   Gmail's All Mail, so Microsoft keeps the search across folders it has
   today. Whether Graph leaves out those two folders together with
   `$search` is to be checked first. If it cannot, the adapter leaves
   them out after each page, as it does for `unread` today.
   **IMAP emulates `all` too**, where the server has no `\All`: one
   `SEARCH` in every folder but the trash and junk, the hits merged by
   date, as the list across accounts merges its accounts. The result is
   the same as with `\All`, only slower: one `SEARCH` per folder and
   page. So every account but POP3 searches everywhere.
6. **Dates.** (a) `date` is the Date header everywhere, Microsoft
   included, and a new field `received` carries the received time, by
   which lists sort and filter. (b) `date` is the received time
   everywhere.
   *Decided: (a).* `date` is what people see in every mail program,
   `received` is reliable for order and ranges. On IMAP it is
   INTERNALDATE. On POP3 it is null, or read from the topmost `Received`
   header.
7. **Search semantics.** (a) The contract promises whole words, which
   every provider can keep. IMAP matches more. (b) Parts of words stay
   the promise, and providers that cannot keep it lack `search` for
   text. (c) Two capabilities, one for each.
   *Decided: (a).* A weaker promise that every account keeps. That
   IMAP finds more harms no one. Two capabilities would cost work and
   help no one.
   **The search runs on the provider's server**, so how text matches is
   the provider's, and the contract says so. Every account finds whole
   words. IMAP also finds parts of words, Microsoft beginnings of words
   (`rech*`), a JMAP server as it indexes. Gmail finds whole words
   only. The service keeps no content of the mail that it could search
   itself. Substrings for every account would need an index of the
   service's own, an idea for later (IDEAS.md).

   What `text=rechnung` finds, by the providers' documentation (the
   Gmail and Microsoft rows are to be confirmed live):

   | In the mail | IMAP | Microsoft | Gmail | JMAP (Stalwart) |
   |---|---|---|---|---|
   | Rechnung | yes | yes | yes | yes |
   | RECHNUNG | yes | yes | yes | yes |
   | Rechnungsnummer | yes | yes, a word beginning | no | as it indexes |
   | Stromrechnung | yes | no | no | as it indexes |

   And `sender=mail`: IMAP finds `max@gmail.com` and `mail@example.org`,
   Gmail and Microsoft only the second, where `mail` is a word of the
   address.
8. **Inner capabilities.** `stable_ids`, `delta` and `server_search` (a)
   leave the API or (b) stay, documented.
   *Decided: (a).* They are the service's inner workings. What
   `stable_ids` said about drafts is already in the documentation of the
   draft id.
9. **Threads.** (a) Each provider groups by its own rules, and the
   contract says so. (b) The service threads every account by headers,
   as for IMAP, with its own ids.
   *Decided: (a).* People see exactly this grouping in Gmail and
   Outlook. Threads of the service's own for every account would be
   double work and would differ from it.
10. **`has_attachments`.** Today the list, the filter and `get_message`
    can each answer differently (4.4). (a) One rule, "real attachments,
    not inline images", computed the same way everywhere, for the field
    in a list and in `get_message`. The filter stays the provider's own
    and is documented as an approximation. (b) As today.
    *Decided: (a).* It has a cost on IMAP: a list then fetches
    `BODYSTRUCTURE` beside the headers, a little more per page. POP3
    reads the headers with `TOP` only, so its list keeps the header
    guess, or reads more lines of each message.
11. **Where the capabilities live.** Under R4 they depend on the server,
    so they are found when the account connects and when it is
    verified. (a) Stored with the account in the database, a new
    migration, and found again when a server's answer contradicts them,
    such as IDLE refused. (b) Held in memory only and found at every
    start.
    *Decided: (a).* The account then answers the same capabilities
    while its server cannot be reached, where (b) would answer none.
    Today an account whose adapter cannot be built answers an empty
    list, which reads as "can do nothing" but means "unknown".

## 7. What belongs to it

- **One test suite for all adapters.** Every adapter, through its fake,
  runs the same expectations: each operation either does what the
  neutral model says, or answers `501` and lacks the capability. Without
  such a suite the adapters drift apart again. It runs before the
  capability work (section 5, step 4), so that work is guarded from its
  start.
- **The client package.** Its capability enum gains the new values and
  loses `flags`, `stable_ids`, `delta` and `server_search`. An older
  client that checks the values strictly fails on the new ones. The
  client is pinned to the service's version, but a client of another
  language is not. The changelog names it.
- **The MCP server.** It names what an account lacks from the
  capabilities (`list_accounts`). It follows the new set, and its tool
  descriptions lose what they say per provider, such as "on IMAP" or
  Gmail's way to archive.
- **The UI.** Each action follows the capability that guards it, such
  as the keyword form `keywords` and the mark buttons the list of marks
  written.
- **The contract and the concept.** The descriptions in
  `docs/openapi.json` that admit differences per provider today are
  rewritten: the list without a folder, `has_attachments`, keywords,
  the sent copy. The provider sections of CONCEPT.md (5.2 to 5.6) keep
  how each adapter works, and say what the account lacks rather than
  how its answers differ.
- **The live checks.** Each provider's check covers its capabilities:
  what it announces works, what it lacks answers `501`. Gmail's check
  sends a reply and reads it in the original's thread. Microsoft's check
  marks a reply and sends a large mail.

## 8. The UI and the MCP server without provider knowledge

**Decided 2026-10-12: U1 to U5, and U6 after the rest.** The rules
above make the API the same for every account. The UI and the MCP
server then know nothing about providers either: what they show and offer follows from the API's
answers alone. A new adapter, or a capability that changes, then needs
no change in either.

### 8.1 Where they know providers today

- **Three tables of what an operation needs.** The domain checks
  protocols (`domain/accounts/abilities.py`), the UI maps capabilities
  to its actions (`web/pages/rights.py`), and the MCP server maps them
  to what it names as lacking (`mailbox-mcp/render.py`). The three can
  disagree. The UI's table already sends the trash with `folders` and
  the keyword form with `flags`, which Gmail announces and refuses.
- **Templates read capabilities themselves**, beside the table:
  `"flags" in account.capabilities` in `pages/message.html`.
- **Mark names are spelled in the UI.** `"$answered"` in
  `partials/message_list.html`, the words for the marks in
  `web/pages/templates.py`. The MCP server shows them raw.
- **Tool descriptions of the MCP server speak per provider**: "on IMAP
  it follows the name", Gmail's way to archive, "such as a POP3
  mailbox".
- **Setting up an account** knows each kind: the connection fields of
  IMAP, POP3 and JMAP, ports, the OAuth sign-ins
  (`components/connection.html`, `routes/accounts.py`). That lies in
  its nature, since a connection is what differs.

The UI's comments on ids (a draft's new id, an IMAP folder's id after a
rename) are harmless: the code already takes the id the answer brings.

### 8.2 The rules

**U1. One table, and the API answers it.** The domain holds the one
table of which capability each operation needs, the same one R3 checks.
The API answers, per account, the operations the caller can run there:
the capabilities and the caller's rights together, as a list of
operation names such as `update_message` or `create_draft`. It goes on
the account in `GET /v1/me` and `GET /v1/accounts/{id}`. The UI and the
MCP server only ask whether an operation is in that list. `rights.py`
becomes a lookup, and the MCP server names what is lacking from the
same answer. The field is new, so nothing breaks.

**U2. Templates never ask a capability or a provider**, only what the
page was handed (`can.<operation>`). A rule in `test_code_rules.py`
holds it: no template names a capability or a kind of provider, apart
from setting up an account.

**U3. Values come from one vocabulary.** The marks, their words and
icons live in `mailbox-common` (section 5, step 8). The UI and the MCP
server never spell a `$` keyword.

**U4. Ids come from the answer.** The UI and the MCP server never assume
an id stays: after a change they take the one the answer brings. This
is already so, and is written down as a rule.

**U5. UI tests by capability, not by provider.** The memory adapter
takes the capabilities a test gives it, so the pages are checked once
for every set of offered operations: an account without `move`, without
`keywords`, with marks read only. The provider's own adapter is then
tested at the API, not in the UI.

**U6. Setting up an account, described by the domain.** Each
kind of account describes its connection: the fields, their defaults
and hints, the ways to sign in. The UI draws the form from it. Then a
new adapter needs no new template. It is the one place the UI still
knows providers, and the change is the largest of the six, so it
comes last.

U1 to U5 belong to section 5, step 8. U6 follows as the last step,
once the rest is done.
