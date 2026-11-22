# Roadmap

> **Beta, version 0.10.0.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

The phases in which Mailbox is built. What each item means is designed
in [CONCEPT.md](mailbox-service/CONCEPT.md). The section numbers below point there.

| Phase | Topic | State |
|---|---|---|
| [0](roadmap/phases-0-4.md#phase-0--skeleton) | Skeleton | **done** |
| [1a](roadmap/phases-0-4.md#phase-1a--users-rights-storage-backup) | Users, rights, storage, backup | **done** |
| [1b](roadmap/phases-0-4.md#phase-1b--imap-reading-and-autodiscovery) | IMAP reading and autodiscovery | **done** |
| [1c](roadmap/phases-0-4.md#phase-1c--stable-ids-and-sync-worker) | Stable ids and sync worker | **done** |
| [2](roadmap/phases-0-4.md#phase-2--writing-and-sending) | Writing and sending | **done** |
| [3](roadmap/phases-0-4.md#phase-3--mcp-server-and-container) | MCP server and container | **done** |
| [4](roadmap/phases-0-4.md#phase-4--change-feed-and-webhooks) | Change feed and webhooks | **done** |
| [4a](roadmap/phases-0-4.md#phase-4a--password-sign-in) | Password sign-in | **done** |
| [4b](roadmap/phases-0-4.md#phase-4b--ui-rework) | UI rework | **done** |
| [4c](roadmap/phases-0-4.md#phase-4c--api-users) | API users | **done** |
| [5](roadmap/phase-5.md#phase-5--more-providers-and-the-configuration-ui) | More providers and the configuration UI | **in progress** |
| [5a](roadmap/phase-5.md#phase-5a--one-way-to-operate-every-mailbox) | One way to operate every mailbox | **done** |

Undecided ideas wait in [IDEAS.md](IDEAS.md) until they are designed.

The MCP server came before Gmail and Microsoft on purpose: with IMAP it
already covered most providers through app passwords, and it proved the
API design early.

The phases themselves are in [roadmap/](roadmap/):
[phases 0 to 4c](roadmap/phases-0-4.md), all done, and
[phases 5 and 5a](roadmap/phase-5.md), where phase 5 lists what is
done first and what is open at its end.

## Keeping this file current

Change the state column when a phase starts or ends, and tick a phase off
in the same commit that finishes it. A new item goes into the phase it
belongs to, with the CONCEPT section that designs it. An item without a
design goes into CONCEPT.md first.
