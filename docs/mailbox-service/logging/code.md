# Logging: where the activities live

Part of [LOGGING.md](../LOGGING.md): section 7.

## 7. Where the activities live

**Decided 2026-09-28:** a package of its own in the domain, the activities
as small classes, one module per area of section 5. Not one file per
activity: a file each would cost more than it says. The package is
`activity`, not `events`: an event is a change in a mailbox today, and
the word stays free for an event-driven design later (section 7.1).

```
domain/
  activity/
    __init__.py      ActivityLog and Activity, and the module of each
                       area: what the domain services use
    base.py          Activity: who, from where, when, level, audited, line()
    recorder.py      ActivityLog.record(activity): the log line, and the
                       audit record of AUDIT.md for one marked audited
    audit.py         Audit: the records of AUDIT.md kept, purged and
                       listed, and audited(), the names it keeps
    catalogue/       one module per area, the areas of section 7.2
      system.py        start, schema, stop, loops, recovery key, log
                         read, keys, backups
      auth.py          signed in, failed sign-in, token refused, lockouts
      users.py         user created, token issued, role replaced, ...
      accounts.py      account connected, needs a new sign-in, OAuth
      discovery.py     a lookup, the discovery limit
      mailbox.py       sent, refused, replayed, the send limit, links to
                         attachments shared, used, handed back, refused
      sync.py          a pass, a failed sync, IDLE
      changes.py       the change log purged
      webhooks.py      created, changed, a new secret, removed, a post
                       failed, given up
      http.py          what the web layer refuses: a body too large,
                         a caller out of requests
```

- **`Activity`** is a frozen dataclass. Every activity carries who acted and
  from where, taken from `Access` (the user, its token, `Access.source`),
  or the worker, the dispatcher, the outbox or the host, and when. The class says
  its `level` and whether the audit keeps it (`audited`, AUDIT.md
  section 2). `line()` writes the sentence of section 3.
- **An activity is one class** in the module of its area, named for what
  happened: `UiSignIn`, `TokenRevoked`, `AccountNeedsSignIn`. Its fields
  are typed: a `User`, an `Account`, a count. There is no field for a
  password, a token's value or the words of a mail, so none can reach a
  line. An activity that failed carries the error, and the recorder logs
  a traceback for what is not a `MailboxServiceError` (rule 6.5).
- **`ActivityLog`** is a service like the others: `build_services` makes it
  with the clock and the audit of AUDIT.md. The domain
  services that record get it in their constructor. `record()` logs the
  line under `activity.<area>.<name>`, at the activity's level, and
  returns the activity, for tests.
- **A change in a mailbox is no activity.** It stays with
  `domain/changes/` and its classes, for clients. The docstrings of
  both packages say the difference.

### 7.1 Three words

| Word | What | Where |
|---|---|---|
| activity | what was done in the service, and by whom | `domain/activity/`, the log, the audit |
| change | what changed in a mailbox: `message.created` and the like | `domain/changes/`, the change feed, webhooks |
| event | not used for either. Kept free for an event-driven design | |

A webhook's `events` and its five values keep their names, since they
are part of the API. The code's names around them are `ChangeKind` and
`ChangeRecord` ([REFACTORING.md](../../REFACTORING.md) section 3).

### 7.2 Names

**Decided 2026-09-28:** each activity has a name, and it logs under
`activity.<area>.<name>`.

- **The area is a package of the domain** ([REFACTORING.md](../../REFACTORING.md)
  section 4): `auth`, `users`, `accounts`, `discovery`, `mailbox`,
  `sync`, `changes`, `webhooks`, `system`. An activity belongs to the
  package whose code records it, so a reader finds the code of
  `activity.mailbox.sent` in `domain/mailbox/`. Two areas are more than
  a package of the domain: `system`
  also holds what the assembly records, the start, the schema and the
  stop, and `http` holds what the web layer refuses before the domain
  sees a request. The limits of section 5.9 are with the area that
  enforces them: the lockouts in `auth`, the send limit in `mailbox`.
- **The name is set in the class, not taken from it**: `name =
  "token_revoked"`. A class renamed in the code keeps its name in the
  log, in the filters of an operator and in the audit, which keeps it
  as the kind of a record.
- **A name says what happened**, in the past tense or as a state,
  lowercase with underscores. It is unique within its area. The area is
  not repeated: `activity.users.created`, not
  `activity.users.user_created`.
- **Short enough for a column**: `activity.<area>.<name>` has 32
  characters at most, so the console aligns every line.
- **Each has its own logger.** A level set on one name silences it
  alone, e.g. `activity.sync.synced`. A search for `activity.users` on
  the log page still finds the whole area.

A test checks that every activity has a name that follows these rules
and that each is listed here.

| Name | What |
|---|---|
| `system.started` | the service started: settings, database, schema |
| `system.migrated` | the schema was migrated or created, with its notes |
| `system.stopped` | the service stopped |
| `system.loop_ended` | a background loop ended |
| `system.round_failed` | a round of a background loop failed |
| `system.key_from_env` | the master key comes from the environment |
| `system.shared_db` | another service uses this database |
| `system.db_away` | the database server cannot be reached, said once when it goes |
| `system.db_back` | the database server answers again, after so many seconds |
| `system.db_unencrypted` | the database server is reached without TLS, as the settings say |
| `system.recovery_shown` | the recovery key was shown |
| `system.log_read` | the service log was read |
| `system.keys_created` | the host created the keys |
| `system.key_imported` | the host stored the master key from a recovery key |
| `system.backup_written` | the host wrote a backup |
| `system.backup_restored` | the host restored a backup |
| `system.audit_purged` | old records purged from the audit of administration |
| `system.not_audited` | an activity the audit could not keep |
| `auth.signed_in` | a sign-in to the UI |
| `auth.sign_in_failed` | a failed sign-in to the UI |
| `auth.code_failed` | a wrong code or passkey of the second factor at the sign-in |
| `auth.recovery_code_used` | a sign-in with a recovery code |
| `auth.session_evicted` | a sign-in that ended the user's oldest session |
| `auth.signed_out` | a sign-out of the UI |
| `auth.confirm_failed` | a wrong password or code to confirm a step |
| `auth.token_refused` | a token that is revoked, expired or of a disabled user |
| `auth.locked_out` | a client address locked out after failed sign-ins |
| `auth.lockout_ended` | its lockout ended |
| `auth.name_braked` | a user name slowed down after failed sign-ins |
| `users.created` | a user created |
| `users.changed` | a user changed |
| `users.change_refused` | a user a batch could not change |
| `users.deleted` | a user deleted |
| `users.made_api_user` | a user's UI sign-in taken |
| `users.sign_in_allowed` | the host gave a user its UI sign-in back |
| `users.password_changed` | a user changed its own password |
| `users.password_set` | a password or one-time password set for a user |
| `users.totp_added` | an authenticator app (TOTP) added to a second factor |
| `users.totp_renamed` | an authenticator app (TOTP) renamed |
| `users.totp_removed` | an authenticator app (TOTP) removed |
| `users.passkey_added` | a passkey added to a second factor |
| `users.passkey_renamed` | a passkey renamed |
| `users.passkey_removed` | a passkey removed |
| `users.factor_removed` | a whole second factor removed, every method |
| `users.codes_renewed` | new recovery codes for a second factor |
| `users.token_issued` | a token issued |
| `users.token_revoked` | a token revoked |
| `users.role_created` | a role created |
| `users.role_replaced` | a role replaced |
| `users.role_deleted` | a role deleted |
| `users.unknown_rights` | stored grants or roles name rights that do not exist |
| `accounts.connected` | an account connected |
| `accounts.connect_failed` | an account could not be connected |
| `accounts.changed` | an account changed |
| `accounts.verified` | an account verified |
| `accounts.removed` | an account removed |
| `accounts.reachable` | an account reached again |
| `accounts.needs_sign_in` | an account needs a new sign-in |
| `accounts.unreachable` | an account could not be reached |
| `accounts.capabilities` | an account's server answered other capabilities than were stored |
| `accounts.oauth_started` | an OAuth sign-in started |
| `accounts.oauth_finished` | an OAuth sign-in finished |
| `accounts.oauth_failed` | an OAuth sign-in failed |
| `accounts.token_renewed` | an account's access token refreshed |
| `discovery.looked_up` | the servers of a domain looked up |
| `discovery.limit_reached` | a user reached the discovery limit |
| `mailbox.sent` | a message sent |
| `mailbox.refused` | a send refused by the grants |
| `mailbox.send_failed` | a send the provider did not take |
| `mailbox.sent_but` | a step after a send failed |
| `mailbox.not_in_audit` | a send not recorded in the audit of sends |
| `mailbox.send_limit` | a user reached the send limit |
| `mailbox.outbox_retry` | an outbox job waits for its next attempt |
| `mailbox.outbox_ended` | an outbox job ended without a send, or sent without its copy |
| `mailbox.replayed` | a result given again for an Idempotency-Key |
| `mailbox.sends_purged` | old records purged from the audit of sends |
| `mailbox.result_not_kept` | a result not kept for its Idempotency-Key |
| `mailbox.link_shared` | a link to an attachment made |
| `mailbox.link_used` | a link to an attachment used |
| `mailbox.link_returned` | a link to an attachment used, but the mail server failed: it holds again |
| `mailbox.link_refused` | a link to an attachment refused |
| `mailbox.links_purged` | links to attachments used or ended, purged |
| `sync.worker_started` | the worker started |
| `sync.synced` | a pass over an account, with counts |
| `sync.pass_overtaken` | a pass a change of ours overtook, read again |
| `sync.pass_given_up` | a pass overtaken on every attempt, left to the next |
| `sync.failed` | a pass that failed |
| `sync.watching` | the worker watches an account |
| `sync.push_unavailable` | an account cannot push changes |
| `sync.watch_postponed` | an account is polled only: every watcher is in use |
| `sync.idle_renewed` | IDLE renewed |
| `sync.watch_failed` | watching an account failed |
| `changes.purged` | old changes purged from the change log |
| `webhooks.created` | a webhook created |
| `webhooks.changed` | a webhook's url, events or accounts changed |
| `webhooks.secret_renewed` | a webhook given a new signing secret |
| `webhooks.removed` | a webhook removed |
| `webhooks.post_failed` | a post failed, to be tried again |
| `webhooks.gave_up` | the posts of a batch given up |
| `webhooks.delivers_again` | a post went through after failures |
| `webhooks.failed` | a post failed with a bug |
| `http.body_too_large` | a request body over the limit refused |
| `http.rate_limited` | a token, a UI session or an address ran out of requests |
