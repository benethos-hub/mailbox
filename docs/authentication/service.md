# Authentication: where it lives in the service

Part of [AUTHENTICATION.md](../AUTHENTICATION.md): section 7.

## 7. Where it lives in the service

**Data**, schemas 18, 19 and 23:

| Table | Columns |
|---|---|
| `totp_devices` | `id` (`tfa_` and 64 hex), `user_id` (references the user, deleted with it), `name`, the secret sealed with the data key (`key_id`, `nonce`, `ciphertext`), `created_at`, `last_step`, `last_used_at` |
| `recovery_codes` | `user_id` (references the user, deleted with it), `key_id` (the data key the hash came from), `hash`, `used_at` |
| `passkeys` | `id` (`psk_` and 64 hex), `user_id` (references the user, deleted with it), `name`, `credential_id` (unique across all users), `credential` (the attested credential data with the public key), `sign_count`, `created_at`, `last_used_at` |

The hashes of the recovery codes are keyed since schema 19. Passkeys
brought a table of their own in schema 23. A passkey holds no secret
and is stored as it is. A TOTP secret is sealed with
the data key as a webhook's secret is (CONCEPT 7.3), bound to its
device. A backup holds the three tables, the secrets as encrypted as
the rest.

**Sessions:** a session keeps which devices of which methods its user
had at the sign-in, as it keeps when the password was set. A device
added or removed ends the sessions that started before. A rename does
not. A session ends after 8 hours without a request and after 24
hours however used, and a user holds 10 at most
([LIMITS.md](../LIMITS.md)).

**The recovery key** (CONCEPT 7.3, [UI.md](../UI.md) 6.5) opens every
stored secret. Its page asks an administrator with a second factor for
the second factor as well as the password: a code, a passkey or a
recovery code.
Without a second factor the password alone does.

**API:**

- `GET /v1/users` and `GET /v1/users/{user_id}` answer `second_factor`,
  true or false, beside `has_password`.
- `GET /v1/users/{user_id}/second-factor`, operation
  `get_second_factor` in `users.read`: the devices of each method,
  `totp` and `passkeys`, each with id, name, `created_at` and
  `last_used_at`, and how many recovery codes are left. Never a secret
  or a key.
- `DELETE /v1/users/{user_id}/second-factor`, operation
  `remove_second_factor` in `users.manage`: every method and the
  recovery codes. `404` when the user has none, `409` for the caller
  itself.
- `DELETE /v1/users/{user_id}/second-factor/totp/{device_id}`,
  operation `remove_totp_device` in `users.manage`: one TOTP device,
  the second factor off with the last device. `404`, `409` as above.
- `DELETE /v1/users/{user_id}/second-factor/passkeys/{passkey_id}`,
  operation `remove_passkey` in `users.manage`: one passkey, the same
  way.

**UI**, with the checklist of [UI.md](../UI.md) section 8:

- The code page after the password, a page outside the layout as the
  sign-in is.
- The page **Second factor** of the person: the cards **Authenticator
  app (TOTP)** and **Passkeys** with their devices, to add, rename and
  remove one, and the card **Recovery codes**.
- On another user's page a card **Second factor**: its devices of both
  methods, and **Remove** for one and for all, for whoever may.

**Audit and log** ([AUDIT.md](../AUDIT.md), [LOGGING.md](../LOGGING.md)):

| Activity | Name | Audited |
|---|---|---|
| signed in with a code | `auth.signed_in`, credential `password+totp`, the line names the device | yes |
| signed in with a recovery code | `auth.signed_in`, credential `password+recovery`, and `auth.recovery_code_used`, a warning | yes |
| a wrong code or passkey at the sign-in | `auth.code_failed`, a warning | yes |
| TOTP device added, the first one turns the second factor on | `users.totp_added` | yes |
| TOTP device renamed | `users.totp_renamed` | yes |
| TOTP device removed, by the person or a user | `users.totp_removed` | yes |
| signed in with a passkey | `auth.signed_in`, credential `password+passkey`, the line names the passkey | yes |
| passkey added, the first device turns the second factor on | `users.passkey_added` | yes |
| passkey renamed | `users.passkey_renamed` | yes |
| passkey removed, by the person or a user | `users.passkey_removed` | yes |
| the whole second factor removed, by a user or the host | `users.factor_removed` | yes |
| new recovery codes | `users.codes_renewed` | yes |

Never a secret, a code, a recovery code or a passkey's answer in a
line.

**Limits** ([LIMITS.md](../LIMITS.md)): five codes per pending sign-in,
five minutes for it, 15 for a secret not yet confirmed or a passkey
not yet made, 10 TOTP devices and 10 passkeys per user. The brakes per address and per name count wrong
codes as they count wrong passwords, at the sign-in and when a step
asks for the password or a code once more.
