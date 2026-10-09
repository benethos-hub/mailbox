# Authentication

How a person proves who it is to the configuration UI, and how each
factor is set up, used and taken away. Users, rights and the credential
kinds as a whole are in [CONCEPT.md](CONCEPT.md) 7.5, how a right is
resolved in [PERMISSIONS.md](PERMISSIONS.md). This file holds the
factors of the UI sign-in: the password today, the second factor
below, passkeys later in the same place.

Proposal of 2026-10-09. **Decided 2026-10-09:** built as proposed,
with the answers of section 9.

## 1. The factors

| Factor | What it proves | Where |
|---|---|---|
| Password | something the person knows | CONCEPT 7.5, built in phase 4a |
| TOTP | something the person holds: an authenticator app with a shared secret | section 2 onwards |
| Passkey | later | section 8 |

A second factor is another credential of the same user. It is for the
UI sign-in only. API tokens, the MCP server and every right stay as
they are: a token is a long random secret already, and a machine
holds no authenticator app.

## 2. TOTP

The time-based one-time password of RFC 6238, as every authenticator
app reads it: HMAC-SHA1, six digits, a step of 30 seconds. The secret
is 20 random bytes, written in base32 for the app.

A user may hold the factor on several **devices**, each with a name of
its own, "Phone" or "Tablet 2", and a secret of its own: the codes
differ from device to device. A code of any of them signs in.

- **Each code once.** The step of the last code taken is stored per
  device. A code of that step or an earlier one is refused, so a code
  read over a shoulder does not work a second time.
- **Clock drift.** One step before and one after the current step are
  taken as well: 30 seconds either way. The server's clock must be
  right, the troubleshooting of section 7 says so.
- **The algorithm** is in `data/secrets/totp.py`, beside the password
  hashes, with the standard library alone (`hmac`, `hashlib`,
  `base64`).

## 3. Signing in

1. Name and password, as today, with the same brakes per address and
   per name (CONCEPT 7.5, [LIMITS.md](LIMITS.md)).
2. A user with a second factor gets no session yet. The service keeps
   a **pending sign-in** on the server, as it keeps a session, and the
   browser a cookie of its own for it. It reaches the code page and
   nothing else. It ends after **five minutes**.
3. The code page takes the six digits from the app, or a recovery code
   (section 5), in one field. A wrong code counts as a failed sign-in
   for the address and the name, as a wrong password does. After
   **five wrong codes** the pending sign-in ends, and the person
   starts again with the password.
4. A right code makes the session. Only then the sign-in counts:
   the last sign-in is stored, the brakes are cleared, and the audit
   writes `auth.signed_in`.
5. Then the forced password change, if one is due.

**Decided 2026-10-09:** the code comes before the forced password
change. Whoever holds a one-time password, the administrator who
made it among them, cannot change the user's password without the
user's app. Setting a password for a user leaves its second factor
as it is.

## 4. Devices: adding, renaming, removing

Everything is on the person's own page **Second factor**, reached from
the sidebar beside **Password** and from the person's user page. It
lists the devices with their name, when each was added and when it
last signed in.

**Adding a device:**

1. **Add a device** asks for its name and the password again, as the
   recovery key does. With a device already there, it asks for a code
   as well: of a device or a recovery code. Whoever holds the password
   and an open session alone cannot slip a device of its own in.
2. The service makes the secret and shows it as a **QR code** to scan
   with the app, and as text to type in where the camera cannot reach.
   The secret is not active yet. It is held in the session, for
   **15 minutes**, and never stored before it is confirmed.
3. The first code from the new device confirms it. Now it is stored
   encrypted, and its codes sign in.
4. The first device turns the factor on and brings ten **recovery
   codes**, shown once (section 5). A further device brings none.
5. Adding a device ends the user's other sessions, as a password
   change does. The session that added it carries on.

A name has 1 to 60 characters and is unique among the user's devices,
regardless of case. A user holds at most **10 devices**.

**Renaming** takes the new name alone: a name hands out nothing.

**Removing a device** asks for the password and a code: of any device,
the one removed among them, or a recovery code. The last device
removed turns the factor off, and its recovery codes go with it.

The QR code holds the `otpauth://` URI: issuer `Mailbox`, and the user
name with the host of the service as the account, so two deployments
show apart in the app. It is drawn by `segno`, pure Python without
dependencies under the BSD licence, behind `web/pages/qr.py`. The page
embeds it as SVG, so the content security policy keeps out inline
scripts and styles.

**Removing for another user:**

- A user with `users.manage`, for a user whose rights it covers, as for
  a password: one device, or the whole factor with every device and
  the recovery codes. It sees the list of devices, never a secret. It
  never adds one: the secret belongs to the person who scans it. Not
  for itself.
- On the host, `users reset-totp <name>` removes the whole factor, for
  the last administrator who lost every device and the recovery codes.

A device removed, or the whole factor, ends the user's sessions, all
but the one of a person removing its own. A user deleted, or one whose
UI sign-in is switched off, loses its factor with its password. A
disabled user keeps both, as it keeps its password.

**Decided 2026-10-09:** setting up is done in the UI only. A QR code
and its confirmation are for a person. The API reads the state and
removes.

**Decided 2026-10-09**, the devices: a list per user, named, each with
a secret of its own. A further device needs the password and a code.
One set of recovery codes per user. An administrator removes one
device or all, never adds one. Devices can be renamed, at most 10.

## 5. Recovery codes

Ten codes, each ten characters from a base32 alphabet without the
letters easily mistaken, shown as `ABCDE-FGHJK`. They are made with
the first device and shown once, with a link to download them as a
text file. The page holds the file as a data URI, so the service keeps
nothing of them after showing them. Each holds 50 bits and works once.
They belong to the user, not to a device: they help whichever device
is lost.

- Stored as SHA-256 hashes, as tokens are: a random code of that
  length needs no slow hash. Case, spaces and dashes do not count.
- The page shows how many are left. **New recovery codes** asks for the
  password and a code, of any device or an old recovery code, as adding
  a device does, and replaces the whole set. Whoever holds the password
  and an open session alone cannot make a set of its own.
- A recovery code used at the sign-in is written to the audit as
  `auth.recovery_code_used`, a warning: it means the app is gone or
  out of reach.
- A recovery code also confirms adding or removing a device and making
  new codes, and is used up by it. Whoever lost every device and every
  recovery code needs an administrator (section 4).

**Decided 2026-10-09:** recovery codes and the host command, both. The
codes let a person back in alone. The command is the last way for the
last administrator. A user with `users.manage` removing the factor is
the third.

## 6. Where it changes the service

**Data**, schema 18:

| Table | Columns |
|---|---|
| `totp_devices` | `id` (`tfa_` and 64 hex), `user_id` (references the user, deleted with it), `name`, the secret sealed with the data key (`key_id`, `nonce`, `ciphertext`), `created_at`, `last_step`, `last_used_at` |
| `recovery_codes` | `user_id` (references the user, deleted with it), `hash`, `used_at` |

The secret is sealed with the data key as a webhook's secret is
(CONCEPT 7.3), bound to its device. A backup holds both tables, the
secrets as encrypted as the rest.

**Sessions:** a session keeps which devices its user had at the
sign-in, as it keeps when the password was set. A device added or
removed ends the sessions that started before. A rename does not.

**API:**

- `GET /v1/users` and `GET /v1/users/{user_id}` answer `second_factor`,
  true or false, beside `has_password`.
- `GET /v1/users/{user_id}/second-factor`, operation
  `get_second_factor` in `users.read`: the devices with id, name,
  `created_at` and `last_used_at`, and how many recovery codes are
  left. Never a secret.
- `DELETE /v1/users/{user_id}/second-factor`, operation
  `remove_second_factor` in `users.manage`: every device and the
  recovery codes. `404` when the user has none, `409` for the caller
  itself.
- `DELETE /v1/users/{user_id}/second-factor/devices/{device_id}`,
  operation `remove_factor_device` in `users.manage`: one device, the
  factor off with the last one. `404`, `409` as above.
- `docs/openapi.json` anew.

**UI**, with the checklist of [UI.md](UI.md) section 8:

- The code page after the password, a page outside the layout as the
  sign-in is.
- The page **Second factor** of the person: the list of devices, add,
  rename and remove one, new recovery codes.
- On another user's page a card **Second factor**: its devices, and
  **Remove** for one and for all, for whoever may.

**Audit and log** ([AUDIT.md](AUDIT.md), [LOGGING.md](LOGGING.md)):

| Activity | Name | Audited |
|---|---|---|
| signed in with a code | `auth.signed_in`, credential `password+totp`, the line names the device | yes |
| signed in with a recovery code | `auth.signed_in`, credential `password+recovery`, and `auth.recovery_code_used`, a warning | yes |
| a wrong code at the sign-in | `auth.code_failed`, a warning | yes |
| device added, the first one turns the factor on | `users.device_added` | yes |
| device renamed | `users.device_renamed` | yes |
| device removed, by the person or a user | `users.device_removed` | yes |
| every device removed at once, by a user or the host | `users.factor_removed` | yes |
| new recovery codes | `users.codes_renewed` | yes |

Never a secret, a code or a recovery code in a line.

**Limits** ([LIMITS.md](LIMITS.md)): five codes per pending sign-in,
five minutes for it, 15 for a secret not yet confirmed, 10 devices
per user. The brakes per
address and per name count wrong codes as they count wrong passwords.

## 7. Troubleshooting

- **Every code is wrong.** The server's clock is off by more than 30
  seconds, or the phone's. Set both by the network time. The service
  log names the failure, never the code.
- **A device is lost.** Another device or a recovery code signs in.
  Then remove the lost one on the page **Second factor** and add the
  new one. The lost device's codes work no more.
- **No device and no recovery code.** Another user with
  `users.manage` removes the factor. For the last administrator:
  `benethos-mailbox-service users reset-totp <name>` on the host.

## 8. Later

- **Passkeys** (WebAuthn) as a second factor of their own, or in place
  of the password. They need no shared secret.
- **A switch for the operator** that requires a second factor, for
  everyone or for users with `users.manage`
  ([IDEAS.md](IDEAS.md)). The way stays open: the sign-in has its steps
  after the password in one place, the code and the forced password
  change. A required setup would be one more step there, before the
  rest of the UI opens.

Left out on purpose: remembering a browser, a second factor for API
tokens, a setup forced at the first sign-in, and anything to do with
the mail accounts. A second factor there is the provider's.

## 9. The decisions

**Decided 2026-10-09:**

- A choice per user. The way to a switch for the operator stays open
  (section 8).
- Recovery codes and the host command, both (section 5).
- Set up in the UI only. The API reads the state and removes (section
  4).
- The code before the forced password change (section 3).
- The QR code to scan, with `segno` (section 4).
- Several named devices per user, each with codes of its own. A
  further device after the password and a code, one set of recovery
  codes per user, an administrator removes one device or all, renaming,
  at most 10 (section 4).
- New recovery codes after the password and a code, as a further
  device (section 5).
