# Authentication: devices and recovery codes

Part of [AUTHENTICATION.md](../AUTHENTICATION.md): sections 5 and 6.

## 5. Devices: adding, renaming, removing

Everything is on the person's own page **Second factor**, reached from
the sidebar beside **Password** and from the person's user page. Its
card **Authenticator app (TOTP)** lists the devices with their name,
when each was added and when it last signed in.

**Adding a device:**

1. **Add a device** asks for its name and the password again, as the
   recovery key does. With a second factor already on, it asks for the
   second factor as well: a code, a passkey or a recovery code. Whoever holds the
   password and an open session alone cannot slip a device of its own
   in.
2. The service makes the secret and shows it as a **QR code** to scan
   with the app, and as text to type in where the camera cannot reach.
   The secret is not active yet. It is held in the session, for
   **15 minutes**, and never stored before it is confirmed.
3. The first code from the new device confirms it. Now it is stored
   encrypted, and its codes sign in.
4. The first device of the first method turns the second factor on
   and brings ten **recovery codes**, shown once (section 6). A
   further device brings none.
5. Adding a device ends the user's other sessions, as a password
   change does. The session that added it carries on.

A name has 1 to 60 characters and is unique among the user's TOTP
devices, regardless of case. A user holds at most **10 TOTP devices**.

**Renaming** takes the new name alone: a name hands out nothing.

**Removing a device** asks for the password and a code: of any device,
the one removed among them, or a recovery code. So a device the person
does not know is removed with the code of its own. The last device of
the last method turns the second factor off, and the recovery codes go
with it.

**Passkeys** have the card **Passkeys** on the same page, with the
same columns. **Add a passkey** asks for its name and the password,
and with a second factor on already a code or a passkey. Then the
browser makes it: it asks where to keep it and for the PIN, the
fingerprint or the face. The service keeps the challenge for 15
minutes. The first device of any method turns the second factor on and
brings the recovery codes, and adding one ends the user's other
sessions, as for TOTP. A browser refuses a second passkey of the user
on the same authenticator, and the service stores a credential once
across all users. Names and the limit are those of a TOTP device:
1 to 60 characters, unique among the user's passkeys, at most **10
passkeys**. Renaming and removing are as for a TOTP device. A passkey
may confirm its own removal. The service cannot reach the device: a
removed passkey stays there until the person deletes it.

**A passkey in place of a code.** Wherever a step asks for the
second factor, it offers the same methods as the code page, one at a
time with **Try another way**: adding or removing a device, new
recovery codes, the recovery key, changing the own password, and the
code page after the password. Where the passkey shows, sending the form asks the browser
for it.

The QR code holds the `otpauth://` URI: issuer `Mailbox`, and the user
name with the host of the service as the account, so two deployments
show apart in the app. It is drawn by `segno`, pure Python without
dependencies under the BSD licence, behind `web/pages/qr.py`. The page
shows it as an image, an SVG in a data URI, which the content security
policy admits as an image (`img-src data:`). No inline markup reaches
the page.

**Removing for another user:**

- A user with `users.manage`, for a user whose rights it covers, as for
  a password: one TOTP device, one passkey, or the whole second factor,
  every method and the recovery codes. It sees the list of devices, never a
  secret. It never adds one: the secret belongs to the person who
  scans it. Not for itself.
- On the host, `users reset-second-factor <name>` removes the whole
  second factor, for the last administrator who lost every device and
  the recovery codes.

A device removed, or the whole second factor, ends the user's
sessions, all but the one of a person removing its own. A user
deleted, or one whose UI sign-in is switched off, loses its second
factor with its password. A disabled user keeps both, as it keeps its
password.

**Decided 2026-10-09:** setting up is done in the UI only. A QR code
and its confirmation are for a person. The API reads the state and
removes.

**Decided 2026-10-09**, the devices: a list per user, named, each with
a secret of its own. A further device needs the password and a code.
One set of recovery codes per user. An administrator removes one
device or all, never adds one. Devices can be renamed, at most 10.

## 6. Recovery codes

Ten codes, each fifteen characters from a base32 alphabet without the
letters easily mistaken, shown as `ABCDE-FGHJK-MNPQR`. They belong to the
second factor, not to a method or a device: they help whichever is
lost. They are made with the first device and shown once, with a link
to download them as a text file. The page holds the file as a data
URI, so the service keeps nothing of them after showing them. Each
holds 75 bits and works once.

- Stored as HMAC-SHA256 under a key derived from the data key, with
  the user's id in what is hashed, and with the id of that data key.
  Whoever steals the database without the master key cannot try a
  single guess, and a guess made with it fits one user only. The check
  is as fast as a plain hash. Case, spaces and dashes do not count.
- The key is derived with HKDF from the data key, for this purpose
  alone, and comes from the vault, never from the database. The
  domain only gets a hash function handed in. Each row keeps the id of
  the data key, so a rotation of the data key, should one come, can
  still check old codes or void them.
- After a restore on another machine the codes count only with the
  same master key, as every other secret of the backup does.
- A code of digits alone is tried as a code of the app first, then as a
  recovery code.
- The page shows how many are left. **Make new codes** asks for the
  password and a code, of any device or an old recovery code, as adding
  a device does, and replaces the whole set. Whoever holds the password
  and an open session alone cannot make a set of its own.
- A recovery code used at the sign-in is written to the audit as
  `auth.recovery_code_used`, a warning: it means a device is gone or
  out of reach.
- A recovery code also confirms adding or removing a device, making
  new codes, showing the recovery key and changing the own password,
  and is used up by it. Whoever lost every device and every
  recovery code needs an administrator (section 5).

**Decided 2026-10-09:** recovery codes and the host command, both. The
codes let a person back in alone. The command is the last way for the
last administrator. A user with `users.manage` removing the second
factor is the third.
