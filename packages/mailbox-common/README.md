# <img src="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/brand/icon.svg" alt="" height="36" align="absmiddle"> mailbox-common

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/benethos-hub/mailbox/badges/coverage.json&logo=githubactions&logoColor=white)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/benethos-hub/mailbox?logo=opensourceinitiative&logoColor=white)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-common?logo=python&logoColor=white)](https://pypi.org/project/benethos-mailbox-common/)

[![PyPI benethos-mailbox-common](https://img.shields.io/pypi/v/benethos-mailbox-common?label=PyPI%20benethos-mailbox-common&logo=pypi&logoColor=white)](https://pypi.org/project/benethos-mailbox-common/)

[![Sponsor](https://raw.githubusercontent.com/benethos-hub/.github/main/profile/badges/sponsor.svg)](https://github.com/sponsors/BeneODev)
[![PayPal](https://raw.githubusercontent.com/benethos-hub/.github/main/profile/badges/paypal.svg)](https://paypal.me/BeneODev)

> **Beta, version 0.5.2.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

What
[`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service)
and
[`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp)
of [Mailbox](https://github.com/benethos-hub/mailbox) both need, held
once, on PyPI as `benethos-mailbox-common`. The MCP server cannot see
the service, so what both use lives here.

It is installed with them and is not meant to be used on its own. It
is built for the packages of this repository, and its modules, groups
and extras may change between versions without notice. It carries the
version of the other packages, and the service and the MCP server pin
it to their own.

Its modules are in five groups, one per concern: `mail` (addresses,
the plain text of an HTML body and the marks a person sees on a
message), `log` (the log line and the
masking of secrets), `paths` (the folders of the operating system),
`settings` (a program's settings from the environment and a file)
and `values` (secrets, sizes, text and canonical JSON).

It needs the standard library alone. The extra `paths` brings
platformdirs for the folders of the operating system, `settings`
pydantic-settings for a program's settings, and `all` brings every
extra.

It sees neither the service, nor the MCP server, nor the client.
