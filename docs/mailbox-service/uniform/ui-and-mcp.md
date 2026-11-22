# Uniform: the UI and the MCP server

Part of [UNIFORM.md](../UNIFORM.md): section 8.

## 8. The UI and the MCP server without provider knowledge

**Decided 2026-10-12: U1 to U5, and U6 after the rest.** The UI and the
MCP server know nothing about providers. What they show and offer
follows from the API's answers alone. A new adapter, or a capability
that changes, needs no change in either.

### 8.2 The rules

**U1. One table, and the API answers it.** The domain holds the one
table of which capability each operation needs, the same one R3 checks
(`domain/accounts/abilities.py`). The API answers, per account, the
operations the caller can run there: the capabilities and the caller's
rights together, as a list of operation names such as `update_message`
or `create_draft`. It goes on the account in `GET /v1/me` and
`GET /v1/accounts/{id}`. The UI and the MCP server ask whether an
operation is in that list. One operation, `update_message`, holds
several changes, so the UI asks the account's capabilities for which of
them to offer. The MCP server names what an account lacks from its
capabilities in the same answer.

**U2. Templates never ask a capability or a provider**, only what the
page was handed (`can.<operation>`). A rule in `test_code_rules.py`
holds it: no template names a capability or a kind of provider, apart
from setting up an account. The tool descriptions of the MCP server
name no provider either.

**U3. Values come from one vocabulary.** The marks and their words live
in `mailbox-common` (`mail/marks.py`). The UI picks their icons itself.
The UI and the MCP server never spell a `$` keyword.

**U4. Ids come from the answer.** The UI and the MCP server never assume
an id stays: after a change they take the one the answer brings.

**U5. UI tests by capability, not by provider.** The memory adapter
takes the capabilities a test gives it, so the pages are checked once
for every set of offered operations: an account without `move`, without
`keywords`, with marks read only. The provider's own adapter is then
tested at the API, not in the UI.

**U6. Setting up an account, described by the domain.** Each kind of
account describes its connection beside its adapter
(`data/providers/connections.py`): the fields, their defaults and
hints, the ways to sign in. The UI draws the form from it. A new adapter
needs no new template.
