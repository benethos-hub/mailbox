# Connecting Microsoft accounts

> **Pre-alpha, version 0.1.0.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

Outlook.com, Hotmail and Microsoft 365 accounts connect by OAuth: the
person signs in at Microsoft, and the service keeps a refresh token,
encrypted, never a password. For that, each deployment registers an app of
its own in Microsoft Entra ID. The design is in [CONCEPT.md](CONCEPT.md),
section 5.4.

## 1. A place for the app registration

App registrations live in an Entra ID directory (tenant). Any of these
works:

- a Microsoft 365 organisation you administer, or in which you may
  register apps;
- a free Azure account (<https://azure.microsoft.com/free>), which creates a
  directory of its own. App registrations cost nothing;
- a Microsoft 365 developer sandbox, where Microsoft still hands them out.

The app can let in accounts of other directories and personal accounts, so
where it is registered does not limit whose mail it reaches.

## 2. Register the app

In the Microsoft Entra admin center (<https://entra.microsoft.com>):
**Identity → Applications → App registrations → New registration**.

- **Name:** anything, e.g. the deployment's name.
- **Supported account types:** *Accounts in any organizational directory
  and personal Microsoft accounts*. This matches the default tenant
  `common`. For one organisation only, choose that and set the tenant
  (step 4).
- **Redirect URI:** platform *Web*,
  `<public url>/ui/oauth/microsoft/callback`, e.g.
  `http://localhost:8080/ui/oauth/microsoft/callback` on one machine or
  `https://mail.example.org/ui/oauth/microsoft/callback` behind a proxy.
  Plain `http` is allowed for `localhost` only. It must match
  `MAILBOX_API_PUBLIC_URL` exactly.

Then, in the new app:

- **API permissions → Add a permission → Microsoft Graph → Delegated
  permissions:** `Mail.ReadWrite`, `Mail.Send`, `offline_access`, `openid`,
  `email`, `profile`. No admin consent is needed for personal accounts; an
  organisation may require it.
- **Certificates & secrets → New client secret:** copy the *value* at
  once, it is shown only then. Secrets expire, after 24 months at most:
  note the date and replace the secret before it.
- **Overview:** copy the *Application (client) ID*.

## 3. Configure the service

In `config/benethos-mailbox-api/.env`, or the container's environment:

```
MAILBOX_API_PUBLIC_URL=http://localhost:8080
MAILBOX_API_OAUTH_MICROSOFT_CLIENT_ID=<application (client) id>
MAILBOX_API_OAUTH_MICROSOFT_CLIENT_SECRET_FILE=<file holding the secret>
```

The secret may also be given directly as
`MAILBOX_API_OAUTH_MICROSOFT_CLIENT_SECRET`; a file keeps it out of the
environment, which shows up in process listings. In a container, mount it
as a secret like the master key.

## 4. Optional: who may sign in

`MAILBOX_API_OAUTH_MICROSOFT_TENANT` is `common` by default. `consumers`
lets in personal accounts only, `organizations` work and school accounts
only, and a tenant id or domain one organisation only. It must fit the
supported account types chosen in step 2.

## 5. Connect an account

In the configuration UI: **Accounts → Connect an account → Sign in with
Microsoft**, or look up an Outlook.com address and follow its sign-in. The
account's page offers **Sign in again** when Microsoft stops accepting the
token, e.g. after a password change.

Over the API, `POST /v1/oauth/microsoft/start` returns the sign-in URL for
a browser; the browser comes back to the UI, where the same user finishes
the sign-in.
