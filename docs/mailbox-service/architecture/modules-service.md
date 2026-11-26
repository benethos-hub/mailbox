# Architecture: the modules of the service

Part of the [architecture](../ARCHITECTURE.md): sections 3 and 3.1.

## 3. The code, module by module

What each package and module of the service holds. A new module gets
its line here in the same commit. `tests/test_module_tree.py` at the
root of the repository checks that every path named here is there, that every package
is named, and that a folder which lists some of its modules as lines
lists all of them.

### 3.1 The service

```
packages/mailbox-service/
  src/benethos_mailbox_service/
    __main__.py         # python -m, calls cli/
    cli/                # the command line, one module per command
      __init__.py       # main(), the parser built from the commands
      common.py         # --env-file, the errors a command reports, the
                        #   master key from the key provider or a
                        #   recovery key
      serve.py          # the REST API and the UI, the log first
      openapi.py        # the OpenAPI document on stdout
      alert_rules.py    # the alerts on the metrics on stdout
      paths.py          # where the settings and the data are
      users.py          # create-admin, set-password, reset-second-factor
      keys.py           # init, import, generate
      backup.py         # write a backup, verify one
      restore.py        # replace the database with a backup
      storage.py        # move the records between SQLite and
                        #   PostgreSQL, or check that they fit
    assembly/           # builds the service, picks implementations,
                        #   decides nothing else
      storage.py        # the repositories, the audit, the activity log
      secrets.py        # the key provider, the vault
      providers.py      # the guard of every connection, the adapters'
                        #   factory, OAuth apps, kinds offered, discovery
      domain.py         # build_services: the domain services wired
      services.py       # Services, as web/ and cli/ reach them
      lifecycle.py      # opened() for a command, serving() for the app
      web.py            # create_app, openapi_json
    logs.py             # assembly: the log of serve, its dictConfig for
                        #   uvicorn, the access line, the lines of
                        #   mailbox-common
    config.py           # cross-cutting: Settings (MAILBOX_SERVICE_* env and
                        #   the .env, on the base of mailbox-common), the
                        #   folders that apply: named, the repository's,
                        #   the system's (mailbox-common)
    errors.py           # cross-cutting: MailboxServiceError hierarchy, no HTTP
    common/             # cross-cutting: helpers several layers share,
                        #   standard library, anyio, idna and
                        #   mailbox-common only
      opaque.py         # opaque ids and cursors: prefix + base64 JSON,
                        #   and base64 without padding, for passwords and
                        #   OAuth too
      clock.py          # utc_now, the default clock of the services,
                        #   iso and parse_iso: a time as text, in UTC,
                        #   start_of_day and parse_day: a day as the
                        #   UI shows it, local
      ratelimit.py      # pacing: a token bucket and a backoff
      hosts.py          # host names in one form: ASCII, Unicode, syntax
      urls.py           # URLs read one way: host_of, is_loopback,
                        #   path_and_query
      retention.py      # Retention: how long records are kept, when the
                        #   old ones are due to go
      bounded.py        # trim: tables in memory with a cap
      locks.py          # KeyedLocks: one lock per key, for the services
      chunks.py         # batched: a sequence in slices
    web/                # PRESENTATION: HTTP only, FastAPI lives here
      __init__.py       # install: both front ends, errors to the right one
      services.py       # the domain services as dependencies, for both
      state.py          # what the app keeps on app.state, read typed
      urls.py           # this service's public address, OAuth callback,
                        #   a link's URL, a path as the log names it
      limits.py         # the size of a request body, the requests a
                        #   minute, for both
      errors.py         # error class -> status code, for both
      responses.py      # download: bytes to save as a file, for both
      search.py         # the search of a message list by its query names
      api/              # the JSON API: /health open, the rest under /v1
        deps.py         # bearer authentication, services per request
        schemas/        # shapes that exist only at the HTTP boundary,
                        #   one module per subject: accounts, oauth,
                        #   mail, users, tokens, status, errors,
                        #   outbox
        errors.py       # the error envelope, the errors routes document
        exposition.py   # the figures of GET /v1/metrics in the text
                        #   format of Prometheus (prometheus_client),
                        #   and alert_rules.yml, the alerts on them
        alert_rules.yml # five alerts for Prometheus, printed by
                        #   the command alert-rules
        routes/         # one router per resource. One account's mail:
                        #   folders.py, mailbox.py (its messages, in
                        #   two routers that keep the order of the
                        #   OpenAPI document), sending.py, outbox.py,
                        #   changes.py, drafts.py. messages.py across accounts,
                        #   links.py a link to an attachment used,
                        #   the one route under /v1 without a token
      pages/            # the configuration UI under /ui, not in OpenAPI
        deps.py         # who is signed in, the CSRF check, if_allowed
        navigation.py   # the sidebar entries a caller may open and their
                        #   dots, breadcrumbs
        filters.py      # the filter bar of a list: its fields and chips,
                        #   user_names and records_filter for the lists
                        #   of records
        session.py      # sign-in with a password, server-side sessions,
                        #   the pending sign-in before the code
        qr.py           # QR codes as SVG data URIs (segno)
        passkeys.py     # the second step of a page: the ways it offers
                        #   (Ways, ways, offered, first_way), a
                        #   passkey's challenge where a code is asked,
                        #   the browser's answer taken from a form, the
                        #   service as passkeys see it (passkey_party,
                        #   passkeys_work)
        templates.py    # Jinja2: filters, render, Post/Redirect/Get,
                        #   and what htmx sends and follows (is_htmx,
                        #   leave, redirect_to)
        grants.py       # the grant editor's rows, read back into grants
        editor.py       # the editor of rights on a user's or a role's page
        mailform.py     # the mail form: fields to a message, shown again
        forms.py        # form errors, failing: back with the message,
                        #   model_of and text_of: what a form holds
        rights.py       # what the mail pages offer, by the rights on an account
        sender.py       # the tag of a message's sender check, in words
        effective.py    # a user's effective rights, grouped for reading
        errors.py       # errors as a page
        security.py     # the security headers of every answer under
                        #   /ui, the content security policy
        handlers.py     # what the UI answers to the sign-in required,
                        #   a password to change, a failed form, CSRF
        routes/         # one module per area
        templates/      # base and bare, partials, components (macros), pages
        static/         # app.css, app.js, early.js (read before the page
                        #   is drawn), passkey.js (asks the browser for
                        #   a passkey), vendored htmx, img/ (the icon
                        #   and the logo, made by assets/build.py, the
                        #   sprite of Bootstrap Icons with its licence,
                        #   made by assets/mailbox-service/icons.py)
    domain/             # BUSINESS LOGIC: decides, knows no HTTP
                        # one package per area (docs/REFACTORING.md),
                        #   the service of a package in service.py,
                        #   several services in one module each
      rights/           # who may do what: permissions (the catalogue of
                        #   rights and groups), Access (one caller)
      auth/             # proving who calls: AuthService, Passwords,
                        #   SignInThrottle, Lockouts (lockouts.py: the
                        #   brakes on an address and a name, logged),
                        #   SecondFactors (the frame of
                        #   the second factor), Totp, Passkeys and
                        #   RecoveryCodes, the names of devices
                        #   (devices.py),
                        #   ApiTokens (tokens.py: issued, revoked, the
                        #   one presented), what a sign-in to the UI
                        #   answers (signin.py)
      users/            # UserService, RoleService, TokenService,
                        #   PasswordService, SecondFactorService,
                        #   TotpService, PasskeyService, one
                        #   module each, the
                        #   rules they share in rules.py, effective
                        #   rights in effective.py
      accounts/         # AccountService, Adapters (the live adapter per
                        #   account), OAuthService, abilities: what each
                        #   operation needs of an account, 501 for a lack or
                        #   what an adapter does not implement, checks:
                        #   what settings and credentials must pass
                        #   before they are stored. OAuthService signs
                        #   in in the browser (oauth.py), with a code
                        #   in device.py, what both ways share in
                        #   signin.py. connections: how each kind of
                        #   account is connected, as the UI draws its
                        #   forms
      discovery/        # DiscoveryService: trust, ranking, cache, limits,
                        #   candidates.py: an address read, candidates
                        #   merged and filled in, what can be connected
      mailbox/          # MailboxService, the facade for mail: calls under
                        #   our ids, an account's folders and their
                        #   roles (folders), the folders a grant
                        #   reaches (reach), the checks of a message's
                        #   folders against them (guards),
                        #   lists across accounts (across, merge),
                        #   the threads of one account and a folder
                        #   by threads (threads),
                        #   the fingerprint of a request
                        #   (fingerprint), links to attachments for
                        #   another service (links), the cursors of
                        #   the lists, sealed with an HMAC (cursors)
        outgoing/       # Outgoing: replies, sending and drafts
                        #   (service, with composing, delivering and
                        #   checks, replies), grant limits and the send
                        #   audit (sending), the Idempotency-Key
                        #   (idempotency), a send put into the drafts
                        #   folder to go out later (outbox), how a job
                        #   of it is sent (queued) and the rounds that
                        #   send what is due (runner, OutboxRunner).
                        #   Reads through ..calls and ..reach
      sync/             # SyncService (stable message ids), the sync pass
                        #   and how the passes went (runner, SyncRunner),
                        #   what a pass finds (passes), the threads the
                        #   index keeps (threads), our own changes a pass
                        #   must not overwrite (writes), a message
                        #   looked up in vain followed by one pass
                        #   (follow), SyncWorker (polling and IDLE)
      changes/          # what changed in a mailbox, for clients:
                        #   MailboxChange, one class per kind, ChangeFeed
      webhooks/         # WebhookService, WebhookDispatcher (signed posts,
                        #   retries)
      system/           # the service at a glance: StatusService, and to
                        #   admin RecoveryKey and ServiceLog
      activity/         # what was done, and by whom: the service log.
                        #   Activity (base.py), ActivityLog (recorder.py),
                        #   catalogue/ one module per area of the domain,
                        #   and http for what the web layer refuses:
                        #   activity.<area>.<name> (docs/mailbox-service/LOGGING.md 7.2),
                        #   Audit (audit.py): those marked audited kept
                        #   and read (docs/mailbox-service/AUDIT.md)
      paging.py         # the cursors this service hands out itself, the
                        #   page they continue, encode_before and
                        #   decode_before for a list newest first
      rounds.py         # rounds: the background loops of the services
    data/               # DATA: reads and writes, decides nothing. A
                        #   package is imported through its __init__.py
      models/           # provider-neutral types, one module per subject:
                        #   accounts, users, folders, messages, batch,
                        #   sending, outbox, paging, discovery, audit,
                        #   changes, webhooks, threads, connections
      mail/             # messages in RFC 5322, whatever protocol carries
                        #   them. __init__.py offers the modules
        compose.py      # outgoing messages as bytes (email)
        parse.py        # incoming bytes parsed (imap-tools' mail parser),
                        #   a block of header lines alone (email)
        convert.py      # a parsed message to Message / MessageSummary
        fields.py       # one header field: a Message-ID as one token,
                        #   an address in Unicode
        authentication.py # the receiving server's check of the sender,
                        #   read from its Authentication-Results entry
      protocols/        # the wire, one library each, in our types:
                        #   imap/ (IMAPClient, with the errors and the
                        #   quoting of imaplib: session.py, its parts
                        #   folders.py and messages.py, responses.py,
                        #   values.py), smtp.py (smtplib),
                        #   pop3.py (poplib), jmap/ (JMAP over http:
                        #   client.py, shapes.py, answers.py),
                        #   oauth/ (OAuth 2.0: values.py, client.py
                        #   with PKCE, the sign-in with a code and
                        #   refresh, answers.py what the provider
                        #   answers, tokens.py the token source),
                        #   transport.py: the Server, TLS,
                        #   timeouts, translated(): a library's errors
                        #   as this project's, the failures below
                        #   every library,
                        #   wire.py: JSON a server sends read into
                        #   shapes (pydantic)
        http/           # httpx: base.py (the client, the capped read),
                        #   safe.py (hosts users typed, SSRF guard),
                        #   api.py (JSON to a provider's known hosts),
                        #   server.py (JSON to a server an account
                        #   names, at the checked address),
                        #   post.py (posts to webhook receivers)
      providers/        # the adapters, one directory each, and what
                        #   they share
        base.py         # the contract: Reads, and one protocol for each
                        #   thing an adapter may do beyond it
        rules.py        # what every adapter answers the same way
        tokenapi.py     # TokenApi, signed: what Gmail's and Graph's
                        #   clients share, the access token renewed
                        #   once, the pause the server asked for
        registry.py     # build_provider, sign_in, probe_server: the
                        #   adapter of a kind, its settings by default
        connections.py  # how each kind of account is connected, as the
                        #   UI draws its forms
        guard.py        # pacing, retries, blocked logins, for any adapter
        settings.py     # an account's settings read once into named
                        #   values (Login, Host), server_of for
                        #   discovered servers
        sender.py       # SmtpSender: sending for IMAP, POP3, ...
        mailserver.py   # MailServerAdapter: what IMAP and POP3 share,
                        #   the server, the login, the guard, SMTP,
                        #   a probe without a login, the settings from
                        #   discovered servers
        imap/, memory/, # one directory per provider (adapter),
        microsoft/,     #   provider.py the adapter, mappers.py the
        pop3/, jmap/,   #   translation, shapes.py what the provider
        gmail/          #   sends as JSON, api.py its HTTP API on the
                        #   wire, changes.py what the sync asks, where
                        #   it has them, the rest one module per
                        #   subject.
                        #   imap: connect.py, mailbox.py (one session
                        #   and its folders), folders, messages, drafts,
                        #   changes (with IDLE), abilities (what the
                        #   server announces), everywhere (the folder
                        #   all where the server has no \All).
                        #   jmap: api.py over data/protocols/jmap/,
                        #   connect.py (its settings), folders,
                        #   messages, drafts, sending, changes.
                        #   microsoft: api.py (Graph over
                        #   data/protocols/http), signin.py its
                        #   endpoints and the scopes it needs,
                        #   folders, messages, listing.py (a folder's
                        #   messages, the search), drafts (with
                        #   sending), uploads.py (a draft too large for
                        #   one request, its files one by one), changes
                        #   (delta queries), marks.py (answered and
                        #   forwarded as Outlook keeps them).
                        #   gmail: api.py (the Gmail API over
                        #   data/protocols/http), signin.py,
                        #   reading.py (what the parts read alike),
                        #   folders (labels), messages, sending
                        #   (with the drafts), changes (history).
                        #   pop3: one inbox, a session per step,
                        #   mappers.py its ids and cursors.
                        #   memory: store.py what it holds, where
                        #   tests look, messages, folders, drafts
      storage/          # own records, one module per subject, table.py
                        #   for the in-memory ones, migrated.py what
                        #   opening did to a schema, sqlite/ the file of
                        #   the database, its connection, the steps of
                        #   its schema and the files SQLite keeps beside
                        #   it (file.py), sqlite/migrations/ the base, the registry,
                        #   versions/ one class per schema version,
                        #   sql/ what is spoken through SQLAlchemy
                        #   Core: the types and what differs between
                        #   databases (dialect.py), the tables of
                        #   schema 26 (schema.py), the database the
                        #   repositories use, an engine on the one
                        #   connection (database.py), where a database
                        #   lies (place.py), the file of SQLite as one
                        #   place (file_place.py), a schema on a
                        #   PostgreSQL server as another
                        #   (server_place.py), the tables for an
                        #   export and a view of one moment
                        #   (tables.py), the rows of a table keyed by
                        #   id (rows.py) and the repositories, one
                        #   module per subject,
                        #   sql/revisions/ the steps of the schema from
                        #   schema 26 on, as revisions of Alembic, run
                        #   in the process. repositories.py opens one
                        #   of them
      secrets/          # envelope encryption, key providers, password
                        #   hashes, the vault of the credentials, TOTP,
                        #   passkeys (fido2)
      backup/           # encrypted backups of the database: the file
                        #   of blocks and its encryption (blocks.py),
                        #   writing, reading, checking and restoring
                        #   them (backups.py)
      export.py         # the records of a store as lines of JSON and
                        #   back, the logical export
      move.py           # the move of the records between SQLite and
                        #   PostgreSQL: every value held to its column
                        #   first, then copied, compared and marked
      files.py          # files for the owner alone (0600): database, backup, key.
                        #   The lock that tells a running service
                        #   from a stopped one is paths.locks of
                        #   mailbox-common
      logbook.py        # the newest log lines in memory, for the log page
      discovery/        # autodiscovery sources and their helpers:
                        #   base.py the protocol of a source, the
                        #   sources presets.py (with presets.json),
                        #   isp.py (ISP autoconfig), jmap.py (JMAP
                        #   well-known), ispdb.py and mx.py, their
                        #   helpers autoconfig.py (the file format),
                        #   placeholders.py, dns.py and suffix.py
                        #   (where a domain ends). sources.py puts
                        #   them in order
```
