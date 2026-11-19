# Uniform: the decisions

Part of [UNIFORM.md](../UNIFORM.md): section 6.

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
   of its own (`PidTagLastVerbExecuted`).
   (a) Microsoft reads and writes it, Gmail writes no marks. (b) Neither
   writes marks.
   *Decided: (a).* Checked live on 2026-10-15: Microsoft reads and
   writes both. The send answers whether the original was marked, and
   the account's lists of marks (section 3) say so in advance.
5. **A list without a folder.** (a) The inbox, on every account. (b)
   Every folder, on every account, which IMAP would have to emulate
   folder by folder. (c) The folder becomes required.
   *Decided: (a), with the role `all`* as the explicit search
   everywhere: Gmail's All Mail, a server's own folder or mailbox of
   that role, and otherwise an emulation. Without it the MCP server
   would lose the search across all folders on Gmail. Microsoft lists
   every folder and leaves the trash and junk out after each page, so a
   page can come back short. IMAP runs one `SEARCH` in every folder but
   the trash and junk and merges the hits by date. JMAP asks one
   `Email/query` with `inMailboxOtherThan` the trash and junk. POP3
   answers `501` (R2). An account without the folder of a role answers
   `501` as well, and across accounts it is named in `incomplete`.
6. **Dates.** (a) `date` is the Date header everywhere, Microsoft
   included, and a new field `received` carries the received time, by
   which lists sort and filter. (b) `date` is the received time
   everywhere.
   *Decided: (a).* `date` is what people see in every mail program,
   `received` is reliable for order and ranges. On IMAP it is
   INTERNALDATE. On POP3 it is read from the topmost `Received` header,
   and null only where there is none or it cannot be read.
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

   What `q=rechnung` finds, by the providers' documentation (the
   Gmail and Microsoft rows are to be confirmed live):

   | In the mail | IMAP | Microsoft | Gmail | JMAP (Stalwart) |
   |---|---|---|---|---|
   | Rechnung | yes | yes | yes | yes |
   | RECHNUNG | yes | yes | yes | yes |
   | Rechnungsnummer | yes | yes, a word beginning | no | as it indexes |
   | Stromrechnung | yes | no | no | as it indexes |

   And `from=mail`: IMAP finds `max@gmail.com` and `mail@example.org`,
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
10. **`has_attachments`.** Before 0.5.0 the list, the filter and
    `get_message` could each answer differently. (a) One rule, "real
    attachments, not inline images", computed the same way everywhere,
    for the field in a list and in `get_message`. The filter stays the
    provider's own and is documented as an approximation. (b) As it
    was.
    *Decided: (a).* It has a cost on IMAP: a list then fetches
    `BODYSTRUCTURE` beside the headers, a little more per page. POP3
    reads the headers with `TOP` only, so its list keeps the header
    guess (decided 2026-10-15).
11. **Where the capabilities live.** Under R4 they depend on the server,
    so they are found when the account connects and when it is
    verified. (a) Stored with the account in the database, a new
    migration, and found again when a server's answer contradicts them,
    such as IDLE refused. (b) Held in memory only and found at every
    start.
    *Decided: (a).* The account then answers the same capabilities
    while its server cannot be reached, where (b) would answer none.
    Before 0.5.0 an account whose adapter could not be built answered
    an empty list, which read as "can do nothing" but meant "unknown".
