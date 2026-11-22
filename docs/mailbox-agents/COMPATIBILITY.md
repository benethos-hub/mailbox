# Compatibility

Which releases of the [mailbox service](https://github.com/benethos-hub/mailbox)
each release of Mailbox Agents works with. An agent asks the service for
its version before every pass and every backfill and refuses one outside
these lines. Why, and how a new line is taken up:
[concept/mailbox-service.md](concept/mailbox-service.md), "The version of
the service".

A line is the minor version of the service while its major is 0, such as
0.8, and the major version from 1 on. It starts at the lowest release that
was tested, and every later release of the same line works as well. The
pin of `benethos-mailbox-client` follows the newest line of each release.

| Mailbox Agents | Mailbox service | `benethos-mailbox-client` |
|---|---|---|
| 0.10.0 (not released yet) | 0.8 from 0.8.0 and 0.9 from 0.9.0 and 0.10 from 0.10.0 | `==0.10.0` |
| 0.2.0 | 0.8 from 0.8.0 and 0.9 from 0.9.0 | `~=0.9.0` |
| 0.1.0 | 0.8 from 0.8.0 | `~=0.8.0` |

The newest release stands on top. A release that holds two lines, so
that the agents can be updated before the service, names both.
