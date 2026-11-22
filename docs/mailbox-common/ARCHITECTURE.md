# Architecture of the common package

The modules of `mailbox-common`: section 3.4 of the
[architecture](../mailbox-service/ARCHITECTURE.md). The shape, the
layers of the service and the rules for every package (sections 5
to 17) are there.

## 3.4 What the service, the MCP server and the agents share

What the service and the MCP server both need is a package of its own,
`mailbox-common`, since the MCP server cannot see the service. It sees
neither of them, nor the client. It is made of groups, one per concern,
so a group can be cut out as a package of its own later.

```
packages/mailbox-common/
  src/benethos_mailbox_common/
    __init__.py         # __version__, no group imported
    mail/               # mail itself, nothing of Mailbox
      plaintext.py      # the visible text of an HTML body, and the text
                        #   of a mail: the mail page shows it, the
                        #   model of the MCP server reads it
      addresses.py      # readable: Name <email>, quoted for a form
      marks.py          # the marks of RFC 8621 and their words, as
                        #   the UI and the MCP server show them
    log/                # the lines of a log and the secrets kept out
      lines.py          # format, levels, log_time, plain or in colour
                        #   on a terminal, a program's own lines through
                        #   line_of, the stderr handler
      redact.py         # secrets noted once, masked in every text,
                        #   forget for tests
    paths/              # where a program keeps its files (platformdirs)
      folders.py        # named_file, system_folders: SystemFolders
    settings/           # a program's settings (pydantic-settings)
      files.py          # FileSettings, the base of a program's
                        #   Settings, and load: the command line, the
                        #   environment, the file, the defaults
    values/             # values written one way
      canonical.py      # JSON: compact to send, canonical to hash
      sizes.py          # MIB, and a size in megabytes for a message
      secret.py         # new_id, token, digest, hmac_hex, same. Every
                        #   length with its reason
      text.py           # text on one line: escaped for the log, joined
                        #   for a header, has_break and ends_line for
                        #   the wire, plural
```

- **What goes in.** What at least two packages need. A guide, not a
  rule, as for `common/` in section 2: what only the service needs
  stays in its `common/`, and a helper may move once a second package
  wants it. No test enforces it.
- **A group stands alone.** A module imports only inside its group. A
  group offers its modules in `__all__` (section 5, rules 3 and 4), and
  a caller imports a module from its group, never deeper:
  `from benethos_mailbox_common.log import lines`, then
  `lines.stderr_handler(...)`. Where the module's name is taken in the
  caller, it is imported under another, with a comment.
- **Libraries.** The standard library alone, but for a group that names
  a library. That library is an extra named after the group, never
  after the library: `paths` brings platformdirs, `settings`
  pydantic-settings. A group's module
  that misses its extra says which one. `all` names every extra. An
  extra is worth it when a user of the package does not need the group,
  or the library is heavy. Tests and CI install every extra, and CI
  runs the package once without any.
- **The pin is exact.** The service and the MCP server depend on
  `benethos-mailbox-common[paths,settings]==X.Y.Z`, the version of
  the release.
  So groups, paths and extras may change inside a release, and an
  operator never types an extra.
- **A new module** goes into the group of its concern, with its test in
  the same folder under `tests/`. It returns a record and takes plain
  values (section 9).

`tests/test_architecture.py` of the package checks the libraries and the
groups. `tests/test_common_use.py` at the root of the repository checks
the imports of its callers, and that no module of the service, the
MCP server or the agents defines one of its functions again.
