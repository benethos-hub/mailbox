# Connecting Microsoft accounts

> **Pre-alpha, version 0.1.0.** Not ready for production use: the API,
> the stored data and the configuration may change without notice.

Outlook.com, Hotmail, Live and Microsoft 365 accounts connect by OAuth.
The person signs in at Microsoft. The service keeps an encrypted refresh
token, never a password. For this, each deployment registers an app of
its own in Microsoft Entra ID. It gives the service the app's client id
and secret. This guide walks through the steps. The design is in
[CONCEPT.md](CONCEPT.md), section 5.4.

A client id of the project, shipped with the service, is planned
(CONCEPT 5.4). Then no one has to register an app. Until then, follow the
steps below.

## Overview

| Step | Where | Result |
|---|---|---|
| 1. A directory for the app | Azure / Microsoft Entra | a tenant you administer |
| 2. Register the app | Entra, App registrations | the client id |
| 3. Permissions | the app, API permissions | Graph mail rights |
| 4. A client secret | the app, Certificates & secrets | the secret value |
| 5. Configure the service | `config/benethos-mailbox-service/.env` | "Sign in with Microsoft" in the UI |
| 6. Connect an account | the UI | a connected Microsoft account |

Everything in steps 1 to 4 is free.

## 1. A directory for the app

App registrations live in an Entra ID directory, a *tenant*. The choice
of tenant does not limit whose mail the app can reach. An app in any
tenant can let in personal accounts and accounts of other organisations.

- **You have a Microsoft 365 organisation** that you administer, or in
  which you may register apps. Use it, and go on with step 2.
- **You have only a personal Microsoft account** (Outlook.com, Hotmail,
  Xbox, ...). It has no directory of its own. If you sign in to the Entra
  admin center with it, you get an error: there is no tenant for the
  account (for example, the tenant "Microsoft Services" does not exist).
  Create a directory with a **free Azure account** at
  <https://azure.microsoft.com/free>:
  - Sign in with the personal account.
  - The sign-up asks for a phone number and a credit card to confirm who
    you are. App registrations cost nothing. The free account does not
    turn into a paid one on its own.
  - For private use, pick the personal / individual option where it asks.

  The sign-up creates a directory named **Default Directory**, with your
  account as its administrator.

Keep the account that administers the app apart from the mailboxes you
will connect. Use a separate mailbox for trying things out.

## 2. Register the app

Open the Microsoft Entra admin center, <https://entra.microsoft.com>.
(In the Azure portal, <https://portal.azure.com>, it is the service
*Microsoft Entra ID*.) Check at the top right that the directory from
step 1 is selected. Then go to **Identity → Applications → App
registrations → New registration**.

- **Name:** anything, e.g. the name of your deployment. People see it when
  they sign in.
- **Supported account types:** *Accounts in any organizational directory
  and personal Microsoft accounts*. (Newer versions of the page call it
  *Any Microsoft account user* or similar.) This fits the service's
  default tenant `common`. For one organisation only, choose *this
  organizational directory only* and set the tenant in step 5.
- **Redirect URI:** platform **Web**, and the address the browser comes
  back to:

  ```
  <public url>/ui/oauth/microsoft/callback
  ```

  - on one machine: `http://localhost:8080/ui/oauth/microsoft/callback`
  - behind a proxy: `https://mail.example.org/ui/oauth/microsoft/callback`

  It must match `MAILBOX_SERVICE_PUBLIC_URL` (step 5) character for
  character. Plain `http` is allowed for `localhost` only. `localhost` is
  not the same as `127.0.0.1`, so open the UI under the address
  registered here. You can add more addresses later under
  **Authentication**.

**Register.** The app's **Overview** page shows three ids:

| On the page | What it is | Needed |
|---|---|---|
| Application (client) ID | the app | **yes**: `MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID` |
| Directory (tenant) ID | the directory from step 1 | no, unless the app is for this one organisation only (step 5) |
| Object ID | the registration inside the directory | no |

## 3. Permissions

In the app: **API permissions → Add a permission → Microsoft Graph →
Delegated permissions**, and tick:

| Permission | Why |
|---|---|
| `Mail.ReadWrite` | read, flag, move and delete mail, drafts |
| `Mail.Send` | send |
| `offline_access` | a refresh token, so the service stays signed in |
| `openid`, `email`, `profile` | the address of the account that signed in |

`User.Read`, which a new app has already, may stay. Delegated means the
app acts for the person who signs in, only in that person's mailbox.
Personal accounts need no administrator consent. An organisation may
require it (see "Work and school accounts" below).

## 4. A client secret

In the app: **Certificates & secrets → Client secrets → New client
secret**. Give it a description and an expiry (at most 24 months), then
**Add**.

The list now shows two values for the new secret:

| Column | What it is | Needed |
|---|---|---|
| **Value** | the secret itself, about 40 characters, often with a `~` | **yes**: it goes into the service |
| Secret ID | an id of the secret, shaped like a GUID | no |

Copy the **Value** at once. It is shown only now. If you missed it,
delete the secret and create a new one.

Treat it like a password. Never put it in a repository, a ticket or a
chat. Note its expiry date (see "When the secret expires").

## 5. Configure the service

Put the secret into a file that only the account running the service may
read, e.g. `config/benethos-mailbox-service/microsoft_client_secret`. (The
`config/` folder keeps it out of the repository.) Then set the following
in `config/benethos-mailbox-service/.env` or the service's environment:

```
MAILBOX_SERVICE_PUBLIC_URL=http://localhost:8080
MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_ID=<application (client) id>
MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET_FILE=config/benethos-mailbox-service/microsoft_client_secret
```

- `MAILBOX_SERVICE_PUBLIC_URL` is the redirect URI of step 2 without
  `/ui/oauth/microsoft/callback`.
- The secret may also be given directly as
  `MAILBOX_SERVICE_OAUTH_MICROSOFT_CLIENT_SECRET`. A file keeps it out of the
  environment, which process listings and `docker inspect` show. In a
  container, mount it as a secret like the master key.
- **Who may sign in:** `MAILBOX_SERVICE_OAUTH_MICROSOFT_TENANT` is `common` by
  default. `consumers` lets in personal accounts only. `organizations`
  lets in work and school accounts only. A tenant id or domain lets in
  one organisation only. The value must fit the supported account types
  of step 2.

Restart the service. The UI now offers **Sign in with Microsoft**.
Without a client id the button does not appear.

## 6. Connect an account

Open the UI under the address from step 2, e.g.
`http://localhost:8080/ui`, and sign in with a token of the service. Then
**Accounts → Connect an account → Sign in with Microsoft**, or look up an
Outlook.com address and follow its sign-in.

Microsoft asks the person to sign in and to allow the app the permissions
of step 3. The browser is signed in to Microsoft with one account at a
time. To connect a mailbox other than the one you administer the app
with, use a private browser window.

After the sign-in the browser returns to the UI and the account is
connected. Its page offers **Sign in again** when Microsoft stops
accepting the token, e.g. after a password change.

Over the API, `POST /v1/oauth/microsoft/start` returns the sign-in URL for
a browser. The browser comes back to the UI, and the same user finishes
the sign-in there.

Once connected, the service asks the account's folders every
`MAILBOX_SERVICE_SYNC_INTERVAL` seconds what changed (Graph delta
queries), for the change feed and webhooks. That needs no permission
beyond those of step 3.

## Work and school accounts

With `common`, accounts of any Microsoft 365 organisation may sign in, as
far as their organisation allows. Many organisations let their people
consent only to apps of verified publishers. The sign-in then asks for an
administrator's approval. An administrator of that organisation has to
consent once for the app. Publisher verification needs membership in
Microsoft's partner programme. In a tenant you administer yourself, you
can consent for everyone under **API permissions → Grant admin consent**.

## When the secret expires

A secret stops working on its expiry date. From then on every token
refresh fails with "microsoft refused this service's app
(invalid_client): check the client id and secret", and Microsoft accounts
cannot be reached. Replace it, best before the date:

1. Create a new secret (step 4). The old one keeps working until it
   expires, so both are valid for a while.
2. Write the new value into the secret file and restart the service.
3. Delete the old secret in the app.

The connected accounts need no new sign-in. Their refresh tokens belong
to the app, not to the secret.

## Troubleshooting

| What you see | Cause | What to do |
|---|---|---|
| No "Sign in with Microsoft" in the UI | no client id configured, or the service not restarted | step 5 |
| Microsoft: the redirect URI does not match (`AADSTS50011`) | the address differs from the one registered, e.g. `127.0.0.1` against `localhost`, another port, `http` against `https` | open the UI under the registered address, or register this one too (step 2), and check `MAILBOX_SERVICE_PUBLIC_URL` |
| Microsoft: invalid client secret (`AADSTS7000215`) | the Secret ID was used instead of the Value, or the secret expired | a new secret, its Value (step 4) |
| Signing in to Entra with a personal account fails: no tenant | a personal account has no directory | a free Azure account (step 1) |
| "Need admin approval" at sign-in | a work tenant allows no user consent for this app | an administrator of that organisation consents ("Work and school accounts") |
| The account asks to sign in again | password changed, access revoked, or long unused | **Sign in again** on the account's page |
