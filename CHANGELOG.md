# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Without `MAILBOX_API_KEY` and without any user, `/v1` answers
  `503 setup_required`.

### Added

- Users with roles and grants per account and per operation:
  `/v1/users`, `/v1/roles`.
- API tokens per user: `/v1/users/{user_id}/tokens`. A token is shown once on
  creation and can expire and be revoked.
- `/v1/me` returns the caller and its effective rights, `/v1/permissions`
  the catalogue of rights and groups.
- A caller can only grant rights it holds, and only manage users whose rights
  it holds.
- Rights are checked on every `/v1` request, per account and per operation.
  An account without a grant answers `404`, a missing right `403 forbidden`.
  `list_accounts` returns only the accounts the caller may read.
- Every `/v1` operation carries its required right as `x-permission` in the
  OpenAPI document.
- Two distributions in one uv workspace: `benethos-mailbox-api` (the service)
  and `benethos-mailbox-mcp` (the MCP server, a REST client only).
- MCP server skeleton over stdio or streamable HTTP with a first tool,
  `list_accounts`. Configured by `MAILBOX_API_URL` and `MAILBOX_API_TOKEN`.
- REST skeleton on FastAPI: `/health`, account CRUD, folder list, message list
  with cursor pagination and filters, single message.
- Bearer authentication on every `/v1` route. Without `MAILBOX_API_KEY` the
  API refuses every request.
- In-memory provider for tests and local development.
- OpenAPI 3.1 document with stable `operationId`s, the `bearerAuth` scheme
  and documented error responses. `benethos-mailbox-api openapi` prints it,
  and `docs/openapi.json` holds the current version.
- One error envelope `{"error": {"code", "message"}}`, authentication errors
  included.
