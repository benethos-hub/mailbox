# Authentication

How a person proves who it is to the configuration UI, and how each
factor is set up, used and taken away. Users, rights and the credential
kinds as a whole are in [CONCEPT.md](CONCEPT.md) 7.5, how a right is
resolved in [PERMISSIONS.md](PERMISSIONS.md). This file holds the
factors of the UI sign-in: the password, and the second factor with
its methods. TOTP is the first method, passkeys are the second.

TOTP is built since 0.4.0, decided 2026-10-09. Passkeys joined it on
2026-11-18, decided that day. The decisions are in section 10.

This file is the overview. It holds the factors, the frame of the
second factor, the troubleshooting, what may come later and what was
decided. The rest is in [authentication/](authentication/), under the
same section numbers.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The methods and the sign-in](authentication/sign-in.md) | 3 and 4 | TOTP and passkeys, what each checks, the step after the password, the code page, and changing the own password. |
| [Devices and recovery codes](authentication/devices.md) | 5 and 6 | Adding, renaming and removing a device or a passkey, removing for another user, and the recovery codes: how they are made, stored and used. |
| [Where it lives in the service](authentication/service.md) | 7 | The tables, the sessions, the recovery key, the API, the UI, the audit and the limits. |

## Every section

- [1. The factors](#1-the-factors)
- [2. The second factor: a frame for its methods](#2-the-second-factor-a-frame-for-its-methods)
- [3. The methods](authentication/sign-in.md#3-the-methods): [3.1 TOTP, an authenticator app](authentication/sign-in.md#31-totp-an-authenticator-app) · [3.2 Passkeys](authentication/sign-in.md#32-passkeys)
- [4. Signing in](authentication/sign-in.md#4-signing-in)
- [5. Devices: adding, renaming, removing](authentication/devices.md#5-devices-adding-renaming-removing)
- [6. Recovery codes](authentication/devices.md#6-recovery-codes)
- [7. Where it lives in the service](authentication/service.md#7-where-it-lives-in-the-service)
- [8. Troubleshooting](#8-troubleshooting)
- [9. Later](#9-later)
- [10. The decisions](#10-the-decisions)

## 1. The factors

| Factor | What it proves | Where |
|---|---|---|
| Password | something the person knows | CONCEPT 7.5 |
| Second factor | something the person holds, by one of its methods | section 2 |
| ↳ TOTP, an authenticator app | a shared secret on a device | section 3 |
| ↳ Passkey | a key pair on a device, a security key or in a password manager | section 3.2 |

A second factor is another credential of the same user. It is for the
UI sign-in only. API tokens, the MCP server and every right stay as
they are: a token is a long random secret already, and a machine
holds no authenticator app.

## 2. The second factor: a frame for its methods

"Second factor" names the frame, never one method. The frame holds what
every method shares:

- **The step after the password** (section 4): a user with any method
  gets a pending sign-in and a code page.
- **The recovery codes** (section 6): one set per user, made with the
  first method, gone with the last. They stand in for any method.
- **The state of the user:** on as long as one method is there, and
  which methods and devices it has, for the session and the API.
- **Removing everything:** every method and the recovery codes, by an
  administrator or on the host (section 5).

A **method** holds its own devices and checks its own codes. TOTP is
the first, passkeys are the second (section 3). A method is named for
what it is, TOTP or passkey, in the code, the API and the audit, and
"Authenticator app (TOTP)" and "Passkeys" in the UI. Each has its own
devices, its own card on the page and its own routes under the frame.
They share the recovery codes and the step after the password.

In the code the frame is `domain/auth/factors.py` and
`domain/users/factors.py`, TOTP is `domain/auth/totp.py` and
`domain/users/totp.py`, passkeys `domain/auth/passkeys.py` and
`domain/users/passkeys.py`, the recovery codes
`domain/auth/recovery.py`. The rules for a device's name are
`domain/auth/devices.py`. Each has a repository of its own.

## 8. Troubleshooting

- **Every code is wrong.** The server's clock is off by more than 30
  seconds, or the phone's. Set both by the network time. The service
  log names the failure, never the code.
- **A device is lost.** Another device or a recovery code signs in.
  Then remove the lost one on the page **Second factor** and add the
  new one. The lost device's codes work no more.
- **No passkey offered.** Browsers make passkeys at a name over HTTPS
  or at localhost alone. Open the UI at the public address of the
  service, and behind a proxy set `MAILBOX_SERVICE_PUBLIC_URL`. A
  passkey made at one name works at that name only.
- **A passkey is lost**, or the password manager that kept it. Another
  device or a recovery code signs in, then remove it on the page
  **Second factor**.
- **No device and no recovery code.** Another user with
  `users.manage` removes the second factor. For the last
  administrator: `benethos-mailbox-service users reset-second-factor
  <name>` on the host.

## 9. Later

- **A passkey in place of the password**, a sign-in without one.
  Passkeys came as the second method of the second factor (section
  3.2), after the password.
- **A switch for the operator** that requires a second factor, for
  everyone or for users with `users.manage`
  ([IDEAS.md](../IDEAS.md)). The way stays open: the sign-in has its steps
  after the password in one place, the code and the forced password
  change. A required setup would be one more step there, before the
  rest of the UI opens.

Left out on purpose: remembering a browser, a second factor for API
tokens, a setup forced at the first sign-in, and anything to do with
the mail accounts. A second factor there is the provider's.

## 10. The decisions

**Decided 2026-10-09:**

- A choice per user. The way to a switch for the operator stays open
  (section 9).
- Recovery codes and the host command, both (section 6).
- Set up in the UI only. The API reads the state and removes (section
  5).
- The code before the forced password change (section 4).
- The QR code to scan, with `segno` (section 5).
- Several named devices per user, each with codes of its own. A
  further device after the password and a code, one set of recovery
  codes per user, an administrator removes one device or all, renaming,
  at most 10 (section 5).
- New recovery codes after the password and a code, as a further
  device (section 6).
- The recovery key after the password and a code, for an administrator
  with a second factor (section 7).
- Recovery codes of 75 bits, stored as an HMAC under a key from the
  vault and bound to the user, the most secure of the variants. The old
  codes deleted by the migration, since only the operator's own
  database held any (section 6).
- "Second factor" is the frame, TOTP one method in it, named
  "Authenticator app (TOTP)" in the UI and `totp` elsewhere. Passkeys
  may join as another method with the same recovery codes. The host
  command `users reset-second-factor` removes every method (section 2).

**Decided 2026-11-18:**

- Passkeys as the second method of the second factor, after the
  password, not in place of it (section 3.2).
- Changing the own password after the current password and the second
  factor, except the forced change after the sign-in (section 4).
- After a wrong code the code page shows the field of that code first
  again (section 4).
- The library `fido2` by Yubico, behind `data/secrets/passkeys.py`.
