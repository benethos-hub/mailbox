# Concept of Mailbox

> **Status: draft, 2026-09-24. The software is beta, version 0.10.0.**
> Describes the target design. What is built today is marked in
> [ROADMAP.md](../ROADMAP.md). Facts about third-party products were taken
> from their public documentation on 2026-09-24. Items marked
> **(to verify)** could not be confirmed there.

This file is the overview. Each topic has a file of its own in
[concept/](concept/). The sections keep their numbers: "CONCEPT 7.5" in
the code or in another document names section 7.5, and the list below
leads to it.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [Purpose and model](concept/purpose-and-model.md) | 1 to 4 | One REST API in front of many mail accounts, and an MCP server on top of it. What is in scope, the principles of the API, the resources, and how a message keeps its id. |
| [Providers](concept/providers.md) | 5 to 5.7 | One adapter per protocol: IMAP, POP3, Microsoft Graph, the Gmail API and JMAP. What each provider offers, which library speaks to it, and the dates to watch. |
| [Connecting an account](concept/connecting.md) | 5.8 to 5.11 | How a server is found from an address, how the service behaves as a good client, encodings and other traps, and the rules that make every mailbox work the same way. |
| [The API for accounts, folders and messages](concept/api-mail.md) | 6 to 6.3 | The routes that read and change mail. |
| [The API for sending, changes and lists](concept/api-sending-and-changes.md) | 6.4 to 6.8 | Sending and drafts, the change feed and webhooks, lists with search and paging, the error envelope and the OpenAPI document. |
| [Security](concept/security.md) | 7 to 7.4, 7.6 to 7.8 | What is stored and how it is encrypted, the threat model, the rules for secrets, mail content as untrusted input, backup and restore. |
| [Users, permissions and authentication](concept/users.md) | 7.5 | Users, roles, grants and tokens, and how a caller proves who it is. |
| [The MCP server](../mailbox-mcp/CONCEPT.md) | 8, 8.1 | The MCP server as a client of the API, and how it is operated. In the folder of its package. |
| [The Python client](../mailbox-client/CONCEPT.md) | 8.2 | The client between the API and the MCP server. In the folder of its package. |

Sections 9 to 12 follow below: the technology, the tests, the roadmap
and the open questions.

## Every section

- [1. Purpose](concept/purpose-and-model.md#1-purpose): [1.1 Inside the service](concept/purpose-and-model.md#11-inside-the-service)
- [2. Scope](concept/purpose-and-model.md#2-scope)
- [3. Design principles of the API](concept/purpose-and-model.md#3-design-principles-of-the-api)
- [4. Resource model](concept/purpose-and-model.md#4-resource-model): [4.1 Message ids](concept/purpose-and-model.md#41-message-ids)
- [5. Provider adapters and libraries](concept/providers.md#5-provider-adapters-and-libraries): [5.1 IMAP: IMAPClient for the protocol, imap-tools for parsing](concept/providers.md#51-imap-imapclient-for-the-protocol-imap-tools-for-parsing) · [5.2 POP3: yes, but reduced](concept/providers.md#52-pop3-yes-but-reduced) · [5.3 What each provider offers](concept/providers.md#53-what-each-provider-offers) · [5.4 Microsoft: Graph only, and the deadlines](concept/providers.md#54-microsoft-graph-only-and-the-deadlines) · [5.5 Google: the verification question](concept/providers.md#55-google-the-verification-question) · [5.6 JMAP as a second generic protocol](concept/providers.md#56-jmap-as-a-second-generic-protocol) · [5.7 Dates to watch](concept/providers.md#57-dates-to-watch) · [5.8 Autodiscovery](concept/connecting.md#58-autodiscovery) · [5.9 Being a good client](concept/connecting.md#59-being-a-good-client) · [5.10 Encodings and other traps](concept/connecting.md#510-encodings-and-other-traps) · [5.11 One way to operate every mailbox](concept/connecting.md#511-one-way-to-operate-every-mailbox)
- [6. REST API](concept/api-mail.md#6-rest-api): [6.1 Accounts](concept/api-mail.md#61-accounts) · [6.2 Folders](concept/api-mail.md#62-folders) · [6.3 Messages](concept/api-mail.md#63-messages) · [6.4 Sending and drafts](concept/api-sending-and-changes.md#64-sending-and-drafts) · [6.5 Changes and webhooks](concept/api-sending-and-changes.md#65-changes-and-webhooks) · [6.6 Listing, search and pagination](concept/api-sending-and-changes.md#66-listing-search-and-pagination) · [6.7 Errors](concept/api-sending-and-changes.md#67-errors) · [6.8 OpenAPI](concept/api-sending-and-changes.md#68-openapi)
- [7. Security](concept/security.md#7-security): [7.1 What has to be stored](concept/security.md#71-what-has-to-be-stored) · [7.2 Threat model](concept/security.md#72-threat-model) · [7.3 Design: envelope encryption](concept/security.md#73-design-envelope-encryption) · [7.4 Handling rules](concept/security.md#74-handling-rules) · [7.5 Users, permissions and authentication](concept/users.md#75-users-permissions-and-authentication) · [7.6 Other rules](concept/security.md#76-other-rules) · [7.7 Mail content is untrusted: prompt injection](concept/security.md#77-mail-content-is-untrusted-prompt-injection) · [7.8 Backup and restore](concept/security.md#78-backup-and-restore)
- [8. MCP server](../mailbox-mcp/CONCEPT.md#8-mcp-server): [8.1 Operation](../mailbox-mcp/CONCEPT.md#81-operation) · [8.2 The Python client](../mailbox-client/CONCEPT.md#82-the-python-client)
- [9. Technology](#9-technology)
- [10. Testing](#10-testing)
- [11. Roadmap](#11-roadmap)
- [12. Open questions](#12-open-questions)

## 9. Technology

| Area | Choice |
|---|---|
| Python | 3.11–3.15 |
| Packaging | uv workspace with five distributions (service, client, MCP server, the agents, and what the service, the MCP server and the agents share), hatchling, `src/` layout |
| Web | FastAPI, uvicorn, pydantic v2, pydantic-settings, prometheus_client (metrics) |
| UI | Jinja2, htmx and Bootstrap Icons (kept under `static/`), segno (QR codes), fido2 (passkeys) |
| Storage | SQLite (stdlib `sqlite3`) |
| Crypto | `cryptography` (AES-256-GCM), `keyring` |
| Mail | IMAPClient, imap-tools (parser), smtplib, poplib, httpx (JMAP, Graph, Gmail), dnspython, defusedxml and publicsuffixlist (autodiscovery), idna |
| MCP | `mcp` 2.x |
| Quality | pytest, pytest-asyncio, pytest-cov (≥ 80 %), pytest-xdist, ruff, mypy, GitHub Actions, CodeQL and hadolint under Code scanning |
| Container | non-root image, compose file bound to the loopback address |

## 10. Testing

- **Offline suite is the gate.** No test reaches a mail server. It runs
  on up to eight processes at once.
- API tests run against the `memory` adapter through `TestClient`.
- IMAP adapter tests use a fake `IMAPClient` object at the library boundary.
  A Stalwart container, `containers/test-mail-server/` (since
  2026-10-06), serves the live checks of the POP3, the JMAP and the IMAP
  adapter.
  An integration job with it is not built yet (5.6).
- The JMAP adapter's tests use `httpx.MockTransport` with a JMAP server in
  memory.
- The Gmail and the Graph adapter's tests use `httpx.MockTransport` with
  a Gmail and a Graph mailbox in memory, which answer as the
  documentation of each API describes.
- `live/` holds manual checks, outside `testpaths`, against confirmed
  test accounts only (golden rule 1 in CLAUDE.md). What each one does:
  [LIVE.md](../LIVE.md).
- The traps of 5.10 (folder names in modified UTF-7, localised special
  folders, broken charsets, IDN, SMTPUTF8) get fixtures of their own.
- Contract tests: committed OpenAPI document, unique `operationId`s, bearer
  and error responses on every protected route. The tools of the MCP
  server are committed as well, in `docs/mailbox-mcp/mcp-tools.json`.
- The configuration UI runs in Chrome, Firefox and WebKit through
  Playwright, a suite of its own in
  `packages/mailbox-service/tests/browser`. The default run leaves it
  out, and the CI job `browser` runs it. It is the one check that runs
  the UI's JavaScript.

## 11. Roadmap

Moved to [ROADMAP.md](../ROADMAP.md).

## 12. Open questions

Undecided ideas are collected in [IDEAS.md](../IDEAS.md).


1. **Deployment:** decided, see section 8.1. Still open is whether the
   service later serves several people. Users and grants (7.5) already
   separate callers. What would remain is an owner on each mail account,
   so that one person's administrator cannot grant rights on another's
   mail.
2. **Name:** decided 2026-09-24 and 2026-10-05: a descriptive name rather
   than a brand. The project is named Mailbox, the repository `mailbox`,
   its packages `mailbox-service`, `mailbox-client` (since 2026-10-07),
   `mailbox-mcp` and `mailbox-common` (since 0.4.0). On PyPI they are
   `benethos-mailbox-service`, `benethos-mailbox-client`,
   `benethos-mailbox-mcp` and `benethos-mailbox-common`, on ghcr.io the
   two images as well. The environment prefix of the service is
   `MAILBOX_SERVICE_`. "Mail gateway" was ruled out because it already
   names the filtering gateway in front of a mail server.
3. **Gmail priority:** answered 2026-10-08: Gmail came after the beta,
   built in phase 5 (5.5).
4. **Sending from the MCP server:** decided 2026-09-24, both stay open,
   governed by rights (7.7).
5. **Local cache:** list and search go straight to the provider in the
   design above. A local index (SQLite FTS) would make search across all
   accounts fast, at the cost of a sync engine. Still open after phase
   3, kept in IDEAS.md.
