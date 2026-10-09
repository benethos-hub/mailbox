# <img src="https://raw.githubusercontent.com/benethos-hub/mailbox/main/assets/logo/icon-3d.svg" alt="" height="36" align="absmiddle"> mailbox-common

[![CI](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml/badge.svg)](https://github.com/benethos-hub/mailbox/actions/workflows/ci.yml)
[![PyPI benethos-mailbox-common](https://img.shields.io/pypi/v/benethos-mailbox-common?label=PyPI%20benethos-mailbox-common)](https://pypi.org/project/benethos-mailbox-common/)
[![Python](https://img.shields.io/pypi/pyversions/benethos-mailbox-common)](https://pypi.org/project/benethos-mailbox-common/)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/benethos-hub/mailbox/blob/main/LICENSE)

> **Beta, version 0.3.1.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

What
[`mailbox-service`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-service)
and
[`mailbox-mcp`](https://github.com/benethos-hub/mailbox/tree/main/packages/mailbox-mcp)
of [Mailbox](https://github.com/benethos-hub/mailbox) both need, held
once, on PyPI as `benethos-mailbox-common`. The MCP server cannot see
the service, so what both use lives here.

It is installed with them and is not meant to be used on its own. Its
Python interface has no stability promise. It carries the version of
the other packages, and the service and the MCP server pin it to their
own.

It sees neither the service, nor the MCP server, nor the client.
