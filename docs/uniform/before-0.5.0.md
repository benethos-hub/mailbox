# Uniform: the API before 0.5.0 and the work

Part of [UNIFORM.md](../UNIFORM.md): sections 4, 5 and 7.

## 4. Where the API broke the principle before 0.5.0

Each point names what happens, on which provider, and what the rules
would make of it. **Bug** marks what is wrong under today's documentation
and can be fixed without a decision. **Concept** marks what follows from
a decision of section 6 and changes the contract. **Work** marks a
larger piece that is neither, and runs on its own.

### 4.1 Keywords and marks

- **Microsoft drops `$` keywords without an error.** Setting `$answered`
  or `$junk` answers `200`, and nothing is stored
  (`microsoft/mappers.py`). A `message.updated` record is written
  anyway. Rule R2: `501`. *Bug.* Done: `$answered` and `$forwarded`
  are kept as the verb Outlook last carried out (6.4), and every other
  `$` keyword answers `501`.
- **Gmail announces `flags`, and every keyword change answers `501`**
  (`gmail/messages.py`). The UI offers the keyword form on Gmail
  accounts, against CONCEPT 5 ("the UI offers no action an account
  cannot do"). Rule R3: the capability `keywords` is missing. *Concept
  (section 3).* Done: Gmail lacks `keywords`, and the UI offers no
  keyword form there.
- **`keywords: []` means "none" on IMAP and JMAP, but "not kept" on
  Gmail and POP3.** Microsoft never reads `$answered` or `$forwarded`.
  A client cannot tell "not answered" from "unknown". Rule R5. *Concept
  (6.1).* Done: the account's `marks` say what it reads, and Microsoft
  reads both as the verb Outlook last carried out.
- **Server notes travel as keywords.** `$hasattachment`,
  `$hasnoattachment`, `$mdnsent`, `$submitpending` and `$submitted` come
  through from IMAP and JMAP. `$hasattachment` repeats
  `has_attachments`, the others are the server's own bookkeeping. Rule
  R8: they leave `keywords`. *Concept (6.2).* Done.
- **Keywords come back in lower case**, also Outlook categories with
  spaces or other letters. Such a category cannot be sent back through
  `add_keywords`, because the keyword pattern refuses it (422). *Concept
  (6.3).* Done: keywords keep the provider's spelling, the marks that of
  RFC 8621, and the pattern takes any keyword on one line. IMAP and JMAP
  answer `400` for one that is no atom.
- **One vocabulary for display.** The words for the marks live in the
  UI only (`web/pages/templates.py`). The MCP server shows them raw.
  With the fixed list of marks, the list and its words move to
  `mailbox-common`, used by the UI and the MCP server. Done: its
  `mail/marks.py` holds the marks with their words. The UI picks
  their icons in `web/pages/templates.py`.

### 4.2 Listing without a folder, and across accounts

- **`list_messages` without `folder` lists every folder on Gmail,
  Microsoft and JMAP, trash and junk included, and the inbox on IMAP and
  POP3.** The same call means two things. It is documented, but against
  R1. The MCP tool `search_messages` inherits it. *Concept (6.5).* Done:
  the inbox on every account, and `all` everywhere but the trash and
  junk, which Microsoft and IMAP without `\All` emulate.
- **`list_all_messages` with a role leaves out an account that has no
  such folder**, without naming it in `incomplete`
  (`domain/mailbox/across.py`). *Bug.* Done: it is named there
  with `not_supported`.
- **An account without the folder a role names answers `404` from the
  domain and `409` from the adapters**, for the same situation. Gmail
  has no `archive`, Microsoft no `all` folder. Rule R2: `501`, except
  for `all`, which the adapters of Microsoft, IMAP and JMAP emulate.
  *Concept (6.5).*
  Done.

### 4.3 Dates and order

- **`date` is the received time on Microsoft** (`receivedDateTime`) and
  the Date header, the sender's time, everywhere else. Microsoft does not
  read `sentDateTime` at all. A list across accounts sorts by `date` and
  mixes both. *Concept (6.6).* Done.
- **The `after` and `before` filters compare the received time
  everywhere**, while `date` shows the Date header. A message can show a
  date outside the range it was found with. *Concept (6.6).* Done: `date`
  is the Date header everywhere, Microsoft included, and `received` the
  time the filters compare and lists sort by.
- **IMAP lists newest first by UID**, which is arrival order. JMAP and
  Microsoft sort by received time. Since the list across accounts merges
  by `date` and pages by count, IMAP messages whose UID order differs
  from their date order can be skipped or repeated between pages. *Bug.*
  Done: each account's place counts what it gave, and of the accounts'
  next messages the newest comes first. None is skipped or given twice,
  though a page may hold a message older than one of the next page.
- **Days count in UTC** on Gmail, Microsoft and JMAP, and in the
  server's day on IMAP. Stays: a day is the provider's unit.

### 4.4 Search and attachments

- **IMAP matches parts of words** ("ail" finds "mail"), as IMAP `SEARCH`
  compares. **Gmail and Microsoft match whole words or prefixes**, JMAP
  as its server does. No adapter can make the provider's index match
  parts of words. *Concept (6.7).*
- **On Microsoft, `q`, `from`, `to` or `subject` switch the list to
  Graph's `$search`.** `unread`, `starred` and `has_attachments=false` are then
  checked after each page, so a page can come back short or empty with
  a `next_cursor`. Documented with 6.7. Stays.
- **A Microsoft cursor keeps its first query.** Sent with another folder
  or filter, it answers the old query's next page, without
  `invalid_cursor` (`microsoft/provider.py`). *Bug.* Done: the
  cursor is bound to the folder and the search, and another list's
  answers `400 bad_request`, an invalid cursor.
- **`has_attachments` can come out three ways for one message.** The
  field in a list is a header guess (`multipart/mixed`), `get_message`
  counts the parts, and the filter is the provider's own. *Concept
  (6.10).* Done: a list counts as `get_message` does, from IMAP's
  BODYSTRUCTURE, Gmail's parts and JMAP's attachments. Microsoft's
  `hasAttachments` leaves inline parts out already. A POP3 list keeps
  the guess, decided 2026-10-15.

### 4.5 Sending

- **A reply or forward marks the original only on IMAP and JMAP.** On
  Gmail and POP3 the mark answers `501`, on Microsoft it is dropped. The
  send answers success either way, and only the log knows
  (`domain/mailbox/outgoing.py`). Rule R6: the answer says
  whether the original was marked. *Concept (6.4).* Done:
  `original_marked`, and Microsoft writes both marks.
- **A reply through Gmail starts a new Gmail thread.** The send and the
  draft pass no `threadId` (`gmail/sending.py`). Gmail's
  documentation asks for it besides the headers, so a reply lands outside
  the original's thread. To confirm live. *Bug.* Done: the send and the
  draft pass the original's `threadId`, checked live.
- **Microsoft answers no `sent_copy_id`**, although Exchange keeps the
  copy (`microsoft/provider.py`). The `message.sent` record then
  carries the Message-ID header in place of a message id. *Bug.* Done:
  the mail is sent as a draft, whose immutable id the copy keeps, the
  way Microsoft documents.
- **POP3 keeps no sent copy**, while `send_message` is documented as
  keeping one. JMAP without a sent folder keeps none either, without a
  word. Capability `sent_copy`. *Concept (section 3).* Done.
- **`refused` is always empty on Gmail, Microsoft and JMAP.** They report
  refused recipients later, as a bounce mail. Empty means "unknown"
  there, but "all accepted" on SMTP. *Concept (6.1).* Done: the
  capability `refused` says whether a send names them. IMAP and POP3
  have it where they send through SMTP.
- **Microsoft refuses mail above about 3 MB** with a general provider
  error, while the domain allows 25 MiB of attachments. Graph takes at
  most 4 MB per request, and the MIME travels in base64. Larger mail
  needs Graph's upload sessions. *Work.* Done: a mail above 2.5 MiB is
  stored without its files, which follow one by one. A file below
  3,000,000 bytes goes in one request, a larger one through an upload
  session, in ranges.
- **A send without SMTP answers `409`** on IMAP and POP3, JMAP without
  submission `501`. Rule R2: `501` for both. Done: such an account
  lacks `send`.

### 4.6 Drafts

- **A Gmail draft never shows its `reference`.** The domain keeps it only
  where `$draft` is among the keywords (`domain/mailbox/service.py`),
  and Gmail has no keywords. *Bug.* Done: Gmail names `$draft` for a
  message with the label `DRAFT`, so its draft keeps the `reference`.
- **A replaced draft keeps its id on IMAP and gets a new one elsewhere.**
  Documented with the draft id. Stays.
- **Replacing a draft can leave two**, with an error, on Microsoft and on
  IMAP without UIDPLUS: the new one is stored before the old one is
  deleted. Rule R6. *Bug.* Done: where the old one cannot be deleted,
  the new one is taken back, and only where that fails too the error
  names it. IMAP without UIDPLUS refuses before it stores the new one.
- **IMAP and JMAP announce `drafts` without a drafts folder** and answer
  `409` later. Rule R4. Done: without one they lack `drafts`.

### 4.7 Folders

- **An IMAP folder's id changes when it is renamed**, and so do the ids
  of its subfolders. Documented. The subfolders also lose their
  subscription.
- **Folder counts are null on IMAP and POP3**, and on Gmail's All Mail.
  Microsoft, JMAP and other Gmail labels fill them. Stays: IMAP would
  need a `STATUS` per folder, POP3 has one folder.
- **Gmail's own folders refuse neutral operations with `400`**: no
  subfolder in the inbox, no move into Sent or Drafts. Rule R2. Open:
  the domain refuses a change of a folder with a role with `409` first
  (CONCEPT 6.2). Gmail's `400` is left for a folder made or moved below
  one of its own and for a message moved into Sent or Drafts.
- **Microsoft shows Outbox, Conversation History and similar folders
  without a role**, as if a person had made them. Renaming them fails at
  Graph with a general error. Stays.
- **IMAP drops `\Noselect` folders but keeps them as `parent_id`** of
  their children. *Bug.* Done: the subfolders go below the nearest
  listed folder, or to the top.

### 4.8 Message fields

- **`snippet` is always null on IMAP and POP3**, also in `get_message`,
  where the body is known. Stays: IMAP and POP3 read headers for a list.
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
  *Bug.* Done: the domain checks `threads` first and answers `501`.
- **Providers group differently.** The service threads IMAP by headers
  only. Gmail and Exchange use their own rules, which include the
  subject. JMAP depends on the server. *Concept (6.9).*
- **An IMAP thread id can be null until the backfill reaches the
  message, and a merge turns the younger id into a `404`.** Native
  thread ids never do either. Decided 2026-10-16: the list of threads
  shows such a message as a thread of its own under the message's id,
  which finds the thread once the index has it (CONCEPT 6.3). The `404`
  after a merge stays.
- **Microsoft cuts long conversations at the pages read first**, which
  may not be the newest messages. Marked unverified in the code. Open.

### 4.10 The change feed

- **IMAP without CONDSTORE never reports read state, stars or keywords
  changed by another client.** Nothing tells a client. Capability
  `external_changes`. Done. Only the IMAP adapter has `FlagChanges`, the
  others learn of a change of flags from their changes since a point.
- **IMAP announces `push` without IDLE, and JMAP without an event
  source.** The worker quietly polls instead. IDLE watches the inbox
  only. Rule R4. Done: without them the account lacks `push`.
- **A JMAP deletion carries no folder.** A message in several folders is
  reported with one of them. Stays: JMAP does not say where it was.
- **`message.updated` also means a thread merge**, documented as "moved
  or flags changed".
- **After an expired JMAP state, messages that arrived in the gap are
  never reported as created.** *Bug.* Done: they are reported as
  created, for Gmail and Microsoft as well.

### 4.11 Errors and partial effects

- **The same lack answers different codes**: `409` (send without SMTP,
  drafts without a folder, no trash), `400` (several folders without
  `labels`, Gmail's own folders), `404` (a missing role folder, POP3
  folder changes), `200` (POP3 `list_threads`, Microsoft `$` keywords).
  Rule R2. Done for every lack of a capability, and since step 6 a
  missing role folder answers `501` as well.
- **An IMAP change of flags and folder in one request** stores the
  flags, then fails the move with `501`. IMAP has no transaction over
  both, so R6 can only order the steps: check the move first, then
  store. *Work.* Done: the move is checked before the first `STORE`,
  and a move that fails after it says the flags are changed.
- **Other partial effects with an error**: a batch across IMAP folders
  fails after earlier folders are done. Microsoft's delete for good moves
  to the trash, then deletes, and can stop in between. Rule R6. *Bug.*
  Done: a batch on every adapter answers what was done before a step
  failed. Microsoft's delete for good says so when the message stayed
  in the trash.
- **A JMAP `forbidden`**, as from a read-only token, became
  `502 provider_auth_failed` and set the account to `needs_reauth`.
  *Bug.* Done: the method error is a `ProviderError`, as an HTTP `403`
  is.
- **The domain checks protocols, not capabilities.** `search`, `labels`
  and `send` are not checked by the domain at all. Each adapter refuses
  in its own way. With R3 the domain checks the capability once for
  every operation. Done.

## 5. Work in order

Steps 1 to 9 are done. Each step is one pull request or more.

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
      moves the most code. Done.
   2. IMAP orders the steps of a change of flags and folder. Done.
4. **One test suite for all adapters** (section 7), first with today's
   capabilities. Done: `tests/integration/test_conformance.py` holds
   every kind of mailbox to the rules through the API, and
   `tests/data/providers/test_conformance.py` holds each adapter to its
   contract towards the domain. A test that falls short is marked as a
   strict expected failure that names its place here. None is marked
   now.
5. **Capabilities.** The finer set of section 3, read from the server
   (R4), stored as decision 6.11 says, checked by the domain for every
   operation (R3), `501` for every lack (R2). The client, the UI and
   the MCP server follow them (section 7). Done. The server is asked
   when the account is connected or verified, when the sync sees a
   folder come or go, and when it refuses what was stored. Microsoft
   read `$draft` and wrote no mark until the live check of 6.4.
6. **Values.** The decisions of section 6: dates, the list without a
   folder, server notes, marks, the case of keywords, `has_attachments`.
   Done.
7. **IMAP emulates `all`** where the server has no `\All` (decision
   6.5), a piece of its own. Done. Each folder is taken in its own
   order, and of the folders' next mails the newest comes first, as the
   list across accounts merges.
8. **The UI and the MCP server** (section 8, U1 to U5): the vocabulary
   of the marks in `mailbox-common`, and the operations an account
   offers its caller, read from the API. Done. `operations` names the
   operations of the catalogue of rights. Which parts of a change of
   messages the UI offers still follows the capabilities, since one
   operation, `update_message`, holds them all.
9. **Setting up an account, described by the domain** (section 8, U6).
   Done. Each kind of account describes its connection beside its
   adapter (`data/providers/connections.py`): the settings with their
   words, hints and choices, the secret, where a person signs in
   instead, and what its page sums up. The connect page offers one form
   per kind to set up by hand, and no template names a kind.

All nine steps shipped in 0.5.0. Steps 5 and 6 changed the contract
and are marked as breaking in the changelog.

## 7. What belongs to it

- **One test suite for all adapters.** Every adapter, through its fake,
  runs the same expectations: each operation either does what the
  neutral model says, or answers `501` and lacks the capability. Without
  such a suite the adapters drift apart again. It has run since step 4
  of section 5 (`tests/integration/test_conformance.py`), so the
  capability work was guarded from its start.
- **The client package.** Its capability enum has the new values and
  lost `flags`, `stable_ids`, `delta` and `server_search`. An older
  client that checks the values strictly fails on the new ones. The
  client is pinned to the service's version, but a client of another
  language is not. The changelog says so.
- **The MCP server.** It names what an account lacks from the
  operations the API answers (`list_accounts`), and its tool
  descriptions name no provider, no "on IMAP" and no Gmail way to
  archive.
- **The UI.** Each action follows the operation that guards it, such
  as the keyword form and the mark buttons.
- **The contract and the concept.** The descriptions in
  `docs/openapi.json` that admitted differences per provider were
  rewritten: the list without a folder, `has_attachments`, keywords,
  the sent copy. The provider sections of CONCEPT.md (5.2 to 5.6) keep
  how each adapter works, and say what the account lacks rather than
  how its answers differ.
- **The live checks.** The checks of Gmail, JMAP and POP3 hold the
  account to the capabilities it names: what it announces works, what
  it lacks answers `501`. The checks of IMAP and Microsoft do not
  compare them. Gmail's check
  sends a reply and reads it in the original's thread. Microsoft's check
  marks a reply and, with `--large`, sends a large mail.
