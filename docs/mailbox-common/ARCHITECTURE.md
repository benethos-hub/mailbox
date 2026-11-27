# Architecture of the common package

The modules of `mailbox-common`: section 3.4 of the
[architecture](../mailbox-service/ARCHITECTURE.md). The shape, the
layers of the service and the rules for every package (sections 5
to 17) are there.

## 3.4 What the service, the MCP server and the agents share

What the service, the MCP server and the agents need alike is a package
of its own, `mailbox-common`, since the MCP server and the agents cannot
see the service. It sees none of them, nor the client. It is made of groups, one per concern,
so a group can be cut out as a package of its own later.

```
packages/mailbox-common/
  src/benethos_mailbox_common/
    __init__.py         # __version__, no group imported
    mail/               # mail itself, nothing of Mailbox
      plaintext.py      # the visible text of an HTML body, and the text
                        #   of a mail: the mail page shows it, the
                        #   model of the MCP server reads it
      addresses.py      # readable: Name <email>, quoted for a form,
                        #   and parsed from a header (Parsed)
      marks.py          # the marks of RFC 8621 and their words, as
                        #   the UI and the MCP server show them
    log/                # the lines of a log and the secrets kept out
      lines.py          # format, levels, log_time, plain, in colour
                        #   on a terminal or as JSON, a program's own lines through
                        #   line_of, the stderr handler, to_stream:
                        #   the setup of a program's log
      redact.py         # secrets noted once, masked in every text,
                        #   forget for tests
    paths/              # where a program keeps its files (platformdirs)
      folders.py        # named_file, system_folders: SystemFolders
                        #   program_folders: Folders, where a
                        #   program looks, first found first
    settings/           # a program's settings (pydantic-settings)
      files.py          # FileSettings, the base of a program's
                        #   Settings, and load: the command line, the
                        #   environment, the file, the defaults.
                        #   problems and env_name: a wrong setting
                        #   named, never what was given
                        #   secret_file: a secret from a file
                        #   Names: a list of names between commas
    storage/            # the storage of a program (SQLAlchemy, Alembic)
      shape.py          # Shape: what a program's database is, handed to
                        #   everything here; FileSteps: the steps of a
                        #   file before the revisions
      errors.py         # the errors of the storage, and Errors: which
                        #   classes a program has it raise, its own
                        #   subclasses of them
      dialect.py        # the types of the columns, and where SQLite and
                        #   PostgreSQL write differently: upserts,
                        #   greater, in_chunks, begin_at_once,
                        #   count_on_from, reading_fixed
      database.py       # Database: an engine on the one connection,
                        #   transactions, the revisions on open, purge,
                        #   the rows of an export and a fill
      place.py          # Place, where a database lies, and translated_by
      file_place.py     # the file of SQLite as a place, sqlite_engine
      sqlite_file.py    # the file on sqlite3: its PRAGMAs, its steps,
                        #   a copy, a snapshot, the lock of a running
                        #   program, inspect_file
      server_place.py   # Server, ServerPlace: a schema on PostgreSQL,
                        #   its version, its lock, away and back
      server_engine.py  # the engine on psycopg, tls_arguments
      server_rights.py  # Rights, own_schema, secure, close_database: who
                        #   reaches a program's database on a server
      server_url.py     # URL_FORM, url_problem, server_at: the address of a
                        #   server in a setting
      server_provision.py  # Instance, Provided, instance_statements,
                        #   reading_statements, make_instance: the role and
                        #   the database of an instance, made by an
                        #   administrator
      server_lock.py    # the keys of the advisory locks of a schema
      outage.py         # Availability, Outage: a server away, the pause
      tables.py         # Table, the tables of the schema for an export,
                        #   read in chunks and written back, Fixed
      rows.py           # SqlRows: the rows of a table keyed by id
      revision.py       # Revision: the base of a step of the schema
      revisions.py      # Revisions: the steps of a folder, run by
                        #   Alembic inside the process
      stored.py         # Records, Store: what holds the records
      stores.py         # the stores a tool opens on its own, and the
                        #   locks it takes: file_store, claimed
      export.py         # the records as lines of JSON and back
      move.py           # the move between SQLite and PostgreSQL, held
                        #   to the columns, compared after
      migrated.py       # Migrated: what opening did to a schema
      files.py          # create_private, free_path: files for their
                        #   owner alone (0600), never over another
      locks.py          # exclusive_lock, LockedError: one writer
                        #   at a time, the standard library alone
      clock.py          # utc_now, iso and parse_iso: a time as text,
                        #   in UTC, as a database keeps it
      names.py          # is_plain_name: a role or schema a server takes
                        #   without quoting, is_loopback_host
    values/             # values written one way
      canonical.py      # JSON: compact to send, canonical to hash
      pauses.py         # doubled: a pause that doubles up to a ceiling
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
- **The pin is exact.** The service, the MCP server and the agents
  depend on `benethos-mailbox-common[...]==X.Y.Z`, the version of the
  release, with the extras each needs: the service
  `[paths,settings,storage]`, the MCP server `[paths,settings]` and
  the agents `[paths,settings,storage]`. The extra `postgres` is the driver of PostgreSQL
  for the group `storage`, named after the database, not the library.
  So groups, paths and extras may change inside a release, and an
  operator never types an extra.
- **A new module** goes into the group of its concern, with its test in
  the same folder under `tests/`. It returns a record and takes plain
  values (section 9).

`tests/test_architecture.py` of the package checks the libraries and the
groups. `tests/test_common_use.py` at the root of the repository checks
the imports of its callers, and that no module of the service, the
MCP server or the agents defines one of its functions again.
