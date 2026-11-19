# Refactoring: the data layer and common

Part of [REFACTORING.md](../REFACTORING.md): section 8.

## 8. The data layer and `common`

Concept of 2026-09-28, the second part. `data/` is in packages by kind
already, so it does not move as a whole. This part applies the rules of
section 2 to it, takes two modules of a global nature out of it into
`common/`, and names what else is out of place. Nothing changes in
behaviour.

### 8.1 Today

```
data/
  files.py       files for the owner alone (0600), the lock file
  logbook.py     the newest log lines in memory, for the log page
  models/        provider-neutral types, one module per subject
  mail/          messages in RFC 5322: compose, parse, convert, text, fields
  http/          httpx: base, safe (the SSRF guard), api, post
  storage/       the repository protocols, in memory, sqlite/ (migrations/)
  secrets/       cipher, keys, passwords, vault, redact, backup
  providers/     base, rules, guard, ratelimit, sender, protocols/,
                 imap/, memory/, microsoft/
  discovery/     base, presets, isp, ispdb, mx, autoconfig, dns, suffix,
                 placeholders
common/
  clock.py, ids.py, opaque.py
```

What each package of `data` imports of the others, from the modules'
imports today:

| Package | Imports |
|---|---|
| `models`, `files`, `http` | nothing |
| `mail` | `models` |
| `storage` | `models`, `files` |
| `secrets` | `models`, `files`, `storage` (the vault's repositories, the backup) |
| `logbook` | `secrets` (`redact` alone) |
| `providers` | `models`, `mail`, `http`, `secrets` (`redact` alone) |
| `discovery` | `models`, `http` |

No cycle. Three things stand out:

- **`redact` is read by every layer.** `logs.py`, the web layer in three
  places, the domain in two, and inside `data` the logbook, the vault
  and the OAuth wrapper. It is a helper of the whole service that sits in
  `data/secrets/` by its history. Worse, `from ...secrets import redact`
  imports the package, and with it the vault, the storage protocols and
  SQLite: the providers depend on the database for a masking function.
- **`ratelimit` is read by the domain.** The worker takes `backoff`
  through `data.providers`. A token bucket and a backoff are pacing
  helpers on the standard library, not data access.
- **`backup` sits in `secrets`.** It encrypts, but it is the one module
  of `secrets` that reads the database file, and half of why `secrets`
  imports `storage`.

Seven imports reach inside a package instead of its `__init__.py`:
`data.secrets.redact` four times, `data.models.messages` for
`SEARCH_TEXT_PATTERN`, `data.models.webhooks` for `CHANGE_KINDS`,
`data.mail.text` for `from_html`. Inside `data`, `storage` reaches
`models.changes` and `models.webhooks`, `providers` reaches `mail.parse`
and `mail.fields`. And three `__init__.py` do more than export:
`storage/__init__.py` (217 lines) holds `Store`, `Repositories` and
`open_repositories`, `providers/__init__.py` (193 lines) the registry
with `build_provider`, `sign_in`, `probe_server` and the settings
helpers, `discovery/__init__.py` `default_sources` and `preset_hosts`.

### 8.2 To `common`

| Module | From | Why |
|---|---|---|
| `common/redact.py` | `data/secrets/redact.py` | read by every layer, standard library only |
| `common/ratelimit.py` | `data/providers/ratelimit.py` | read by `data` (the guard, IMAP) and the domain (the worker), standard library only |

Considered and left where they are: `data/logbook.py` is a store of log
lines the domain reads like a repository, and needs nothing but
`redact`. `data/files.py` is I/O for `data` alone. `data/mail/text.py`
is the text of a mail, and the web layer reads it through `data.mail`
(moved after all, as `common/plaintext.py`, by 9.1 A1: the web reads
it for a page too). `data/http/safe.py` is the network.

The rule of `common` says "stateless helpers". `redact` keeps the noted
secrets in the module, process-wide by design, and a `TokenBucket` has
state per instance. Proposed wording, for CLAUDE.md and
[ARCHITECTURE.md](../ARCHITECTURE.md): `common` holds what more than one
layer needs, on the standard library, with no I/O and no state beyond
what a caller holds. `redact` is the one module with state of its own,
and its docstring says why. No other package is needed: nothing found is
of a third kind, neither data nor a helper.

Not part of the move: `common/clock.py` could take the types `Clock`
and `Sleep`. Today `ratelimit.py` declares them on `time.monotonic`, the
domain's services take a clock of `datetime`, and `delivery.py` declares
an async `Sleep` of its own. That waits for a third user (8.6).

### 8.3 Inside `data`

- **`backup` becomes `data/backup.py`**, beside `files.py`. `secrets`
  then holds cipher, keys, passwords and vault: what makes and keeps
  secrets. `backup` imports `secrets` for the cipher and `storage` for
  the file, and nothing imports `backup` but the command line.
- **An `__init__.py` exports, it does not implement.** `Store`,
  `Repositories` and `open_repositories` go to
  `storage/repositories.py`, the registry to `providers/registry.py`,
  `default_sources` and `preset_hosts` to `discovery/sources.py`. Each
  `__init__.py` then imports, and lists `__all__`, as the domain's do.
- **`mail/__init__.py` offers its modules**, `compose`, `parse`,
  `convert`, `text` (until A1) and `fields`, as `activity` offers its
  areas, since
  `compose.build(...)` reads better than a flat list of functions. So
  `from ...mail import compose` goes through the `__init__.py`, and
  `ParsedMessage`, `from_html` and the field helpers are reached that
  way.
- **`models/__init__.py` adds `SEARCH_TEXT_PATTERN` and
  `CHANGE_KINDS`.** The seven imports of 8.1 are fixed.
- **Docstrings**: `data/__init__.py` names every package, not three.
- **The protocols leave the providers. Decided 2026-09-28:**
  `providers/protocols/` and `http/` become one package
  `data/protocols/`, the wire, one library each, in our types:

      data/
        protocols/
          transport.py   TLS, timeouts, the failures below every library
          imap.py        IMAPClient
          smtp.py        smtplib
          http/          httpx: base, safe (the SSRF guard), api, post
          oauth.py       OAuth 2.0 over http: PKCE, refresh, the token source
        providers/       the adapters: base, rules, guard, sender, registry,
                         imap/, memory/, microsoft/

  The protocol modules import nothing of `providers` today, and the
  providers use them: `imap/provider.py`, `sender.py`,
  `microsoft/signin.py` and, through `ApiClient`, `microsoft/provider.py`.
  So the path says what the docstrings say: a protocol module wraps a
  library and translates into our types, a provider composes an adapter
  from them and keeps to `rules` and `guard`. A library is then swapped
  in one module of one package, and a POP3 or JMAP wrapper has its place
  before it is needed. `sender.py` stays with the providers, since it
  uses `Guard` and `rules`. `oauth` is a flow over HTTP rather than a
  wire protocol, but it knows no provider, only the endpoints
  `microsoft/signin.py` hands it, and stays where it is. `discovery`
  reads `protocols` for HTTP, the domain only the type `HostCheck`, and
  `main.py` wires `SafeFetcher` and `WebhookPoster` as today. The three
  homes in `LIBRARY_HOMES` of the architecture test follow.

The direction after the moves, each package importing only lines
below:

```
 backup
 secrets
 storage · providers · discovery
 protocols
 mail · files
 models · logbook
```

`providers` no longer imports `secrets`, and `secrets` no longer holds
what the providers need.

### 8.4 The rules, as for the domain

The rules of sections 2 and 5 apply to `data` as they do to the domain:
a package is imported through its `__init__.py`, from the names in its
`__all__`, no cycle between packages, and the lines of 8.3. Like
`activity`, `mail` exports modules. Tests may import a module inside a
package, since they test it. `test_architecture.py` gets the three
checks for `data` by running the domain's checks over both layers.

The tests follow their modules: `test_ratelimit.py` to `tests/common/`,
and `integration/test_redact.py` too, if it tests the module alone.
`tests/data/mail/` and `tests/data/secrets/` are empty today, while
`test_html_mail.py`, `test_secrets.py`, `test_passwords.py` and
`test_backup.py` sit in `integration/`: each is checked for whether it
tests one layer, and moves if so. Built: `test_ratelimit.py` is in
`tests/common/`, and `test_redact.py` was. Since the package
`mailbox-common` it is in its `tests/log/` (15.2). The four in `integration/`
reach the command line, the domain or a provider beside the module
they are named for, and stay.

### 8.5 Order of work

1. This section and ARCHITECTURE.md, one pull request of documentation.
2. `redact` and `ratelimit` to `common`, with their tests. The imports
   fixed, `data.providers` stops exporting `backoff`, the docstrings of
   `common/__init__.py` and CLAUDE.md say the new rule.
3. `backup` to `data/backup.py`.
4. `data/protocols/`: the four protocol modules and `http/` moved,
   the imports in `providers`, `discovery`, the domain and `main.py`
   fixed, `LIBRARY_HOMES` updated, the tests to `tests/data/protocols/`.
5. The three `__init__.py` to modules, the exports of `mail` and
   `models`, the seven imports fixed.
6. The architecture checks for `data`, CLAUDE.md's layout and
   CONCEPT.md 1.1 with the lines of 8.3.

Steps 2 to 6 are one commit each, in the branch of 9.4, each passing all
checks. The live checks run once at the end. A backup and its restore
are covered by `test_backup.py` and `test_cli.py`, not by a live check,
so step 3 is checked by hand once: `backup` to a file, `restore` into a
fresh folder.

### 8.6 Questions answered

**Decided 2026-09-28:**

- The pacing helper keeps its name: `common/ratelimit.py`.
- `logbook` stays in `data`.
- The `Clock` and `Sleep` types stay where they are. They are merged
  into `common/clock.py` when a third user of them appears, not as part
  of this refactoring.
- CLAUDE.md points to [ARCHITECTURE.md](../ARCHITECTURE.md) for the
  architecture, and ARCHITECTURE.md takes over the whole content of
  CLAUDE.md's sections "Layers of the service" and "Encapsulation and
  replaceable parts", together with what section 8 adds. That is the
  last step of the refactoring.
