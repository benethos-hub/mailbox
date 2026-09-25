# Security

Mailbox Service holds access to people's mailboxes: their credentials, their
mail and the right to send in their name. Reports of weaknesses are very
welcome.

## Reporting a vulnerability

Please do **not** open a public issue. Report it privately through
GitHub: on this repository, **Security → Report a vulnerability**
(<https://github.com/benethos-hub/mailbox/security/advisories/new>).

Helpful in a report:

- what an attacker can reach or do, and from where (the network, a token
  with which rights, a mail that arrives, the configuration UI)
- the steps or a request that shows it, and the version or commit
- no real credentials, tokens or mail content: redact them.

Please give time for a fix before publishing details. The advisory can
name you, if you like.

## Versions

The project is pre-alpha. Fixes go into the latest release and `main`
only. Older versions do not get them.

## What counts

For example: reading or changing mail beyond a token's rights, getting
at stored credentials or the master key, secrets in logs or responses,
sending in someone's name, bypassing the send limits, cross-site attacks
on the configuration UI, a mail that makes the MCP server act against
its user (prompt injection) beyond what CONCEPT 7.7 already describes,
and anything that reaches other hosts through autodiscovery.

The design of these protections is in
[docs/CONCEPT.md](docs/CONCEPT.md), section 7.
