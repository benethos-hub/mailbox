# Authentication: the methods and the sign-in

Part of [AUTHENTICATION.md](../AUTHENTICATION.md): sections 3 and 4.

## 3. The methods

### 3.1 TOTP, an authenticator app

The time-based one-time password of RFC 6238, as every authenticator
app reads it: HMAC-SHA1, six digits, a step of 30 seconds. The secret
is 20 random bytes, written in base32 for the app.

A user may hold TOTP on several **devices**, each with a name of its
own, "Phone" or "Tablet 2", and a secret of its own: the codes differ
from device to device. A code of any of them signs in.

- **Each code once.** The step of the last code taken is stored per
  device. A code of that step or an earlier one is refused, so a code
  read over a shoulder does not work a second time.
- **Clock drift.** One step before and one after the current step are
  taken as well: 30 seconds either way. The server's clock must be
  right, the troubleshooting of section 8 says so.
- **The algorithm** is in `data/secrets/totp.py`, beside the password
  hashes, with the standard library alone (`hmac`, `hashlib`,
  `base64`).

### 3.2 Passkeys

A passkey is a key pair of WebAuthn. The private key stays with the
person: on a laptop or a phone, on a security key, or in a password
manager that syncs it. The service keeps the public key alone, so its
database signs nobody in. A passkey is bound to the service's origin,
so a page of another site cannot use it.

A user may hold several passkeys, each with a name of its own,
"Laptop" or "Security key". Any of them signs in.

- **The ceremonies** are in `data/secrets/passkeys.py`, with `fido2`
  by Yubico, imported there alone. The browser's part is
  `static/js/passkey.js` of the UI.
- **The user verified.** Making and using a passkey both ask the
  authenticator to verify its user, by a PIN, a fingerprint or a face.
  An answer without that is refused.
- **The origin exactly.** An answer counts only from the service's own
  origin: the one of `MAILBOX_SERVICE_PUBLIC_URL`, else the one the
  request came to. A host below it does not count.
- **Each signature once.** A challenge is random, kept on the server
  and taken by the next form that answers it, right or wrong. The
  counter of a passkey must grow with each signature. A passkey that
  keeps no counter, as most synced ones, stays at zero. Once it
  counted, a lower or equal one is refused: it shows a copy of the key.
- **The user's handle** that the browser keeps with a passkey is the
  SHA-256 of the user's id, nothing a person typed.
- **No attestation.** The service does not ask which make of
  authenticator holds a passkey.
- **Where browsers make passkeys:** at a name over HTTPS, or at
  localhost. Not at an address alone, such as `192.168.1.10`, and not
  at a name over HTTP. There the page says so and offers none, and
  TOTP and the recovery codes still work.

## 4. Signing in

1. Name and password, with the brakes per address and per name (CONCEPT 7.5, [LIMITS.md](../LIMITS.md)).
2. A user with a second factor gets no session yet. The service keeps
   a **pending sign-in** on the server, as it keeps a session, and the
   browser a cookie of its own for it. It reaches the code page and
   nothing else. It ends after **five minutes**.
3. The code page takes a passkey, a code of any TOTP device, or a
   recovery code (section 6). It shows one method at a time, the first
   the user has and the browser can use, in this order: a passkey, a
   code of an app, a recovery code. **Try another way** lists the
   others. Nothing stores which one was used. After a wrong code the
   page shows the field of that code first again. A wrong code or passkey
   counts as a failed sign-in for the address and the name, as a wrong
   password does. After **five wrong tries** the pending sign-in ends,
   and the person starts again with the password.
4. A right code makes the session. Only then the sign-in counts:
   the last sign-in is stored, the brakes are cleared, and the audit
   writes `auth.signed_in`.
5. Then the forced password change, if one is due.

**Decided 2026-10-09:** the code comes before the forced password
change. Whoever holds a one-time password, the administrator who
made it among them, cannot change the user's password without the
user's device. Setting a password for a user leaves its second factor
as it is.

**Changing the own password** on the page Password asks for the
current password and, for a user with a second factor, the second
factor as well, as adding a device does: whoever holds an open session
and the password alone cannot lock the person out. The forced change
after the sign-in asks for none, as the step after the password asked
for it a moment before. The second factor is checked after the new
password passed its rules, so a refused one uses up no recovery code.
