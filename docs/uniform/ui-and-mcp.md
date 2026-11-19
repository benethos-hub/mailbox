# Uniform: the UI and the MCP server

Part of [UNIFORM.md](../UNIFORM.md): section 8.

## 8. The UI and the MCP server without provider knowledge

**Decided 2026-10-12: U1 to U5, and U6 after the rest.** The rules
above make the API the same for every account. The UI and the MCP
server then know nothing about providers either: what they show and offer follows from the API's
answers alone. A new adapter, or a capability that changes, then needs
no change in either.

### 8.1 Where they knew providers before 0.5.0

- **Three tables of what an operation needs.** The domain checked
  protocols (`domain/accounts/abilities.py`, which now holds the one
  table of U1), the UI mapped capabilities
  to its actions (`web/pages/rights.py`), and the MCP server mapped them
  to what it names as lacking (`mailbox-mcp/render.py`). The three could
  disagree. The UI's table sent the trash with `folders` and the keyword
  form with `flags`, which Gmail announced and refused.
- **Templates read capabilities themselves**, beside the table:
  `"flags" in account.capabilities` in `pages/message.html`.
- **Mark names were spelled in the UI.** `"$answered"` in
  `partials/message_list.html`, the words for the marks in
  `web/pages/templates.py`. The MCP server showed them raw.
- **Tool descriptions of the MCP server spoke per provider**: "on IMAP
  it follows the name", Gmail's way to archive, "such as a POP3
  mailbox".
- **Setting up an account** knew each kind: the connection fields of
  IMAP, POP3 and JMAP, ports, the OAuth sign-ins
  (`components/connection.html`, `routes/accounts.py`). That lies in
  its nature, since a connection is what differs.

Steps 8 and 9 of section 5 put the rules of 8.2 in their place. The
message page now asks
`can.shows_flags`, the tool descriptions name no provider, and rule U2
stands in `test_code_rules.py`.

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
is a lookup, and the MCP server names what is lacking from the same
answer.

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
new adapter needs no new template. It was the one place the UI still
knew providers, and the change was the largest of the six, so it came
last.

U1 to U5 were built in step 8 of section 5, U6 in step 9.
