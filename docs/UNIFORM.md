# One way to operate every mailbox

**Decided 2026-10-12, built in 0.5.0.** This file collects where the
API behaved differently per provider before 0.5.0 and the rules that
ended that. The decisions are in section 6, and section 7 names what
the change carried along. Section 8 makes the UI and the MCP server
independent of the providers. Section 5 is the work list. The rules
stand in CONCEPT 5.11, the work in ROADMAP phase 5a.

This file is the overview. It holds the principle, the rules and the
capabilities. The rest is in [uniform/](uniform/), under the same
section numbers.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The API before 0.5.0 and the work](uniform/before-0.5.0.md) | 4, 5, 7 | Where the API behaved differently per provider, the work that ended it in order, and what the change carried along. |
| [The decisions](uniform/decisions.md) | 6 | What was decided on 2026-10-12 and after, point by point. |
| [The UI and the MCP server](uniform/ui-and-mcp.md) | 8 | How the UI and the MCP server came to know nothing about providers. |

## Every section

- [1. The principle](#1-the-principle)
- [2. Rules](#2-rules)
- [3. Capabilities](#3-capabilities)
- [4. Where the API broke the principle before 0.5.0](uniform/before-0.5.0.md#4-where-the-api-broke-the-principle-before-050): [4.1 Keywords and marks](uniform/before-0.5.0.md#41-keywords-and-marks) · [4.2 Listing without a folder, and across accounts](uniform/before-0.5.0.md#42-listing-without-a-folder-and-across-accounts) · [4.3 Dates and order](uniform/before-0.5.0.md#43-dates-and-order) · [4.4 Search and attachments](uniform/before-0.5.0.md#44-search-and-attachments) · [4.5 Sending](uniform/before-0.5.0.md#45-sending) · [4.6 Drafts](uniform/before-0.5.0.md#46-drafts) · [4.7 Folders](uniform/before-0.5.0.md#47-folders) · [4.8 Message fields](uniform/before-0.5.0.md#48-message-fields) · [4.9 Threads](uniform/before-0.5.0.md#49-threads) · [4.10 The change feed](uniform/before-0.5.0.md#410-the-change-feed) · [4.11 Errors and partial effects](uniform/before-0.5.0.md#411-errors-and-partial-effects)
- [5. Work in order](uniform/before-0.5.0.md#5-work-in-order)
- [6. Decisions](uniform/decisions.md#6-decisions)
- [7. What belongs to it](uniform/before-0.5.0.md#7-what-belongs-to-it)
- [8. The UI and the MCP server without provider knowledge](uniform/ui-and-mcp.md#8-the-ui-and-the-mcp-server-without-provider-knowledge): [8.1 Where they knew providers before 0.5.0](uniform/ui-and-mcp.md#81-where-they-knew-providers-before-050) · [8.2 The rules](uniform/ui-and-mcp.md#82-the-rules)

## 1. The principle

From outside, every mailbox is operated the same way. Whatever is common
behaves identically on every account. Whatever an account cannot do
answers an error, and the account says so in advance. Nothing is
silently ignored, and no value silently means something else.

The service is already built on this idea: neutral models, capabilities
per account, `501 not_supported` for what an adapter lacks (CONCEPT 5).
An inventory of all five adapters and the domain on 2026-10-12 found
where it did not hold. Section 4 lists what it found.

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

Before 0.5.0 one capability often covered things that differ per
provider. `flags` covered read state, stars and keywords, although Gmail
has no keywords and Microsoft has no `$` keywords. The finer set, where
each one guards exactly one thing:

| Capability | Means | IMAP | POP3 | Gmail | Microsoft | JMAP |
|---|---|---|---|---|---|---|
| `read_state` | `unread` is kept and can be set | yes | no | yes | yes | yes |
| `stars` | `starred` is kept and can be set | yes | no | yes | yes | yes |
| `keywords` | own keywords, without `$` | if the server keeps them | no | no | yes, as categories | yes |
| `marks` | which marks of RFC 8621 the account reads, and which it writes | those the server keeps | none | reads `$draft` | reads `$draft`, `$answered` and `$forwarded` after a live check (6.4), writes the last two | all |
| `folders` | folders: create, rename, delete | yes | no | yes | yes | yes |
| `move` | moving messages | with MOVE or UIDPLUS | no | yes | yes | yes |
| `trash` | delete into the trash | with a trash folder and `move` | no | yes | yes | with a trash folder |
| `purge` | delete for good | with UIDPLUS | yes | yes | yes | yes |
| `labels` | a message in several folders | no | no | yes | no | yes |
| `search` | the filters of `list_messages` | yes | no | yes | yes | yes |
| `drafts` | drafts | with a drafts folder | no | yes | yes | with a drafts folder |
| `send` | sending | with SMTP | with SMTP | yes | yes | with submission and a drafts or sent folder |
| `refused` | a send names the recipients the server refused at once | with SMTP | with SMTP | no | no | no |
| `sent_copy` | a sent mail is kept and its id answered | with a sent folder | no | yes | yes | with a sent folder |
| `threads` | `thread_id`, `list_threads`, `get_thread` | yes, the service's own | no | yes | yes | yes |
| `push` | changes arrive within seconds | with IDLE | no | no | no | with an event source |
| `external_changes` | the change feed sees read state, stars and keywords changed by other clients | with CONDSTORE | no | yes | yes | yes |
| `sender_check` | `sender_check` of a message can be other than `unknown` | with `authserv_id` | with `authserv_id` | yes | yes | with `authserv_id` |

The marks are the keywords RFC 8621 names besides `$seen` and
`$flagged`, which are `unread` and `starred`: `$answered`,
`$forwarded`, `$draft`, `$junk`, `$notjunk` and `$phishing`. The list
draws the line between a mark and a server note (4.1). Other `$`
keywords, such as `$important` or Thunderbird's `$label1`, pass as
keywords, as before.

A yes or no would be too coarse for `marks`, as it was for `flags`.
Microsoft keeps `$answered` and `$forwarded` but no `$junk`, and Gmail
shows a draft by its label but cannot set `$draft`.
So `marks` is not one capability but two lists on the account: the
marks it reads and the marks it writes. Writing a mark outside the
second list answers `501`. A mark outside the first list never appears,
and its absence means nothing. A list `keywords` that replaces the
keywords keeps the marks the message has, on every provider. Only
`remove_keywords` takes a mark off (decided 2026-10-28).

`refused` (decision 6.1) needs a capability as well: whether the
provider names the recipients it refuses while sending, as SMTP does.
Gmail, Microsoft and JMAP report them later, as a bounce mail. It is
named `refused`, like the field it guards. The two lists of marks are
`marks.read` and `marks.written` on the account.

`sender_check` reads the receiving server's `Authentication-Results`
(CONCEPT 6.3). IMAP, POP3 and JMAP need the server's name at the
account, `authserv_id`, since it is not the host the service reads
from. Gmail and Microsoft name theirs the same for every account. JMAP
reads the header with the summary, Gmail among the headers of a
summary, and Microsoft asks Graph for `internetMessageHeaders` in a
list too.

`stable_ids`, `delta` and `server_search` describe how the service works
inside, not what a client can do. They leave the API (decision
6.8).

