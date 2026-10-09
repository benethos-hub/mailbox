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

- **Each code once.** The step of the last code taken is stored. A
  code of that step or an earlier one is refused, so a code read over
  a shoulder does not work a second time.
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

## 4. Setting up and removing

Setting up is on the person's own page **Second factor**, reached from
the sidebar beside **Password** and from the person's user page.

1. **Set up** asks for the password again, as the recovery key does.
2. The service makes the secret and shows it as a **QR code** to scan
   with the app, and as text to type in where the camera cannot reach.
   The secret is not active yet. It is held in the session, for
   **15 minutes**, and never stored before it is confirmed.
3. The first code from the app confirms it. Now the factor is on, and
   stored encrypted.
4. Then ten **recovery codes**, shown once.
5. Setting up ends the user's other sessions, as a password change
   does. The session that set it up carries on.

The QR code holds the `otpauth://` URI: issuer `Mailbox`, and the user
name with the host of the service as the account, so two deployments
show apart in the app. It is drawn by `segno`, pure Python without
dependencies under the BSD licence, behind `web/pages/qr.py`. The page
embeds it as SVG, so the content security policy keeps out inline
scripts and styles.

**Removing:**

- The person on its own page, with its password and a code.
- A user with `users.manage`, for a user whose rights it covers, as for
  a password. It removes a factor, it never sets one up: the secret
  belongs to the person who scans it. Not for itself.
- On the host, `users reset-totp <name>`, for the last administrator
  who lost the phone and the recovery codes.

Each removal ends the user's sessions, all but the one of a person
removing its own. A user deleted, or one whose UI sign-in is switched
off, loses its factor with its password. A disabled user keeps both,
as it keeps its password.

**Decided 2026-10-09:** setting up is done in the UI only. A QR code
and its confirmation are for a person. The API reads the state and
removes.

## 5. Recovery codes

Ten codes, each ten characters from a base32 alphabet without the
letters easily mistaken, shown as `ABCDE-FGHJK`. They are made at
setup and shown once. Each holds 50 bits and works once.

- Stored as SHA-256 hashes, as tokens are: a random code of that
  length needs no slow hash. Case, spaces and dashes do not count.
- The page shows how many are left. **New recovery codes** asks for the
  password and replaces the whole set.
- A recovery code used at the sign-in is written to the audit as
  `auth.recovery_code_used`, a warning: it means the app is gone or
  out of reach.

**Decided 2026-10-09:** recovery codes and the host command, both. The
codes let a person back in alone. The command is the last way for the
last administrator. A user with `users.manage` removing the factor is
the third.

## 6. Where it changes the service

**Data**, schema 18:

| Table | Columns |
|---|---|
| `totp` | `user_id` (key, references the user, deleted with it), the secret sealed with the data key (`key_id`, `nonce`, `ciphertext`), `confirmed_at`, `last_step` |
| `recovery_codes` | `user_id` (references the user, deleted with it), `hash`, `used_at` |

The secret is sealed with the data key as a webhook's secret is
(CONCEPT 7.3), bound to the user. A backup holds both tables, the
secret as encrypted as the rest.

**Sessions:** a session keeps when its user's factor was confirmed, as
it keeps when the password was set. A factor set up or removed ends
the sessions that started before.

**API:**

- `GET /v1/users` and `GET /v1/users/{user_id}` answer `second_factor`,
  true or false, beside `has_password`.
- `DELETE /v1/users/{user_id}/second-factor`, operation
  `remove_second_factor` in `users.manage`. `404` when the user has
  none, `409` for the caller itself.
- `docs/openapi.json` anew.

**UI**, with the checklist of [UI.md](UI.md) section 8:

- The code page after the password, a page outside the layout as the
  sign-in is.
- The page **Second factor** of the person: set up, new recovery codes,
  remove.
- On another user's page a card **Second factor**: its state, and
  **Remove** for whoever may.

**Audit and log** ([AUDIT.md](AUDIT.md), [LOGGING.md](LOGGING.md)):

| Activity | Name | Audited |
|---|---|---|
| signed in with a code | `auth.signed_in`, credential `password+totp` | yes |
| signed in with a recovery code | `auth.signed_in`, credential `password+recovery`, and `auth.recovery_code_used`, a warning | yes |
| a wrong code at the sign-in | `auth.code_failed`, a warning | yes |
| factor set up | `users.factor_set_up` | yes |
| factor removed, by the person, a user or the host | `users.factor_removed` | yes |
| new recovery codes | `users.codes_renewed` | yes |

Never a secret, a code or a recovery code in a line.

**Limits** ([LIMITS.md](LIMITS.md)): five codes per pending sign-in,
five minutes for it, 15 for a secret not yet confirmed. The brakes per
address and per name count wrong codes as they count wrong passwords.

## 7. Troubleshooting

- **Every code is wrong.** The server's clock is off by more than 30
  seconds, or the phone's. Set both by the network time. The service
  log names the failure, never the code.
- **The phone is lost.** A recovery code signs in. Then remove the
  factor on the page **Second factor** and set it up on the new phone.
- **No recovery code either.** Another user with `users.manage` removes
  the factor. For the last administrator:
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

Left out on purpose: remembering a device, a second factor for API
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
