# Connecting Gmail accounts

> **Beta, version 0.3.1.** Usable with real accounts. A breaking change
> of the API or the configuration is announced in the changelog. Stored
> data is carried forward by migrations.

Gmail and Google Workspace accounts connect in one of two ways:

- **Sign in with Google**, over the Gmail API. The person signs in at
  Google. The service keeps an encrypted refresh token, never a
  password. This needs a Google client of your own, set up once as
  below. Folders are Gmail's labels, and the change feed follows Gmail's
  history.
- **IMAP and SMTP with an app password**, with nothing to set up. Google
  hands out app passwords only to accounts with 2-step verification. In
  Google Workspace the administrator may turn them off.

The design is in [CONCEPT.md](CONCEPT.md), sections 5.3 and 5.5.

## Why a client of your own

The project ships no Google app, unlike the one for Microsoft
([MICROSOFT.md](MICROSOFT.md)). The scope the Gmail API needs is one
Google calls restricted. An app that anyone may use needs Google's
verification and a security assessment every year. A self-hosted project
cannot carry that. It does not have to:

- A client in your own Google Cloud project, used by you and people you
  know, needs no verification. Google allows such a client up to 100
  users.
- In Google Workspace, a client set to **Internal** needs none either,
  for the accounts of that organisation.

Google also offers no sign-in with a code for Gmail. The browser is the
only way: Google sends it back to the service, to the address the client
names.

## 1. A Google Cloud project

Sign in at <https://console.cloud.google.com> with the Google account
that should own the client. It need not be one of the accounts you
connect. Create a project, e.g. "Mailbox".

## 2. The Gmail API

**APIs & Services → Library**, search for **Gmail API**, then
**Enable**.

## 3. The consent screen

**Google Auth Platform → Get started**:

- **App name**: e.g. "Mailbox", and a support address.
- **Audience**: **External** for Gmail accounts. **Internal** only for
  the accounts of your own Google Workspace organisation.
- A contact address, then agree and **Create**.

Then **Data Access → Add or remove scopes**. At the bottom, under
manually added scopes, enter `https://mail.google.com/`, then **Add to
table** and **Save**.

The service asks for this scope alone. It covers every operation of the
API, deleting for good among them. Google lists it as restricted.

## 4. The client

**Clients → Create client**:

- **Application type**: **Web application**.
- **Name**: anything, e.g. "Mailbox".
- **Authorized redirect URIs**: the address of the service with
  `/ui/oauth/gmail/callback`, e.g.
  `http://localhost:8080/ui/oauth/gmail/callback`. Add one for each
  address the UI is reached under, e.g. `http://127.0.0.1:8080/...` and
  `https://mail.example.org/ui/oauth/gmail/callback` behind a proxy.
  Google allows `http` for `localhost` and `127.0.0.1` only.

**Create**. Google shows the **Client ID** and the **Client secret**.
Download them as JSON or copy the secret at once: Google may not show it
again. Treat the secret like a password.

## 5. Publish the app

**Audience → Publish app**, so that the status is **In production**.

This is no review. It matters: in the status **Testing** Google lets
refresh tokens expire after 7 days, and every Gmail account would have
to sign in again each week. In production an app that is not verified
shows a warning when a person signs in. They accept it once per account
(see step 7).

An app set to **Internal** has no such status and shows no warning.

## 6. Configure the service

Put the secret into a file only the account running the service may
read, e.g. `config/benethos-mailbox-service/google_client_secret`. Then
set in `config/benethos-mailbox-service/.env` or the service's
environment:

```
MAILBOX_SERVICE_PUBLIC_URL=http://localhost:8080
MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_ID=<client id>
MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_SECRET_FILE=config/benethos-mailbox-service/google_client_secret
```

- A relative path counts as for the Microsoft secret: from the
  repository root, or from the folder of a settings file named by
  `--env-file`.
- `MAILBOX_SERVICE_PUBLIC_URL` is a redirect URI of step 4 without
  `/ui/oauth/gmail/callback`.
- The secret may also be given directly as
  `MAILBOX_SERVICE_OAUTH_GOOGLE_CLIENT_SECRET`. A file keeps it out of
  the environment. In a container, mount it as a secret.
- The id and the secret go together: the service refuses to start with
  one of them alone.

Restart the service.

## 7. Connect an account

Open the UI under an address of step 4, sign in, then **Accounts →
Connect an account** and look up the Gmail address. **Sign in with
Google** comes first, IMAP with an app password below it.

Google asks the person to sign in. For an app that is not verified it
then warns: "Google hasn't verified this app". Choose **Advanced**, then
**Go to Mailbox (unsafe)**. It is your own app. Then allow the access.
The browser returns to the UI and the account is connected.

The browser is signed in to Google with one account at a time. To
connect another mailbox than the one you are signed in with, use a
private browser window.

An account's page offers **Sign in again** when Google stops accepting
the token. Google revokes it when the account's password changes, and
when access is taken back under the Google account's security settings.

## How Gmail looks through the API

- **Folders** are labels. Inbox, Sent, Drafts, Trash and Spam have their
  roles, and so do the labels a person made. A label named `Work/2026`
  sits in `Work`. Renaming `Work` renames the labels inside it too.
- **All Mail** is the folder `ALL_MAIL` with the role `all`: every
  message outside the trash and the spam. It is no label at Gmail.
- A message can be in **several folders**. A move sets its folders
  exactly: `["Label_1"]` takes the inbox off, `["ALL_MAIL"]` archives.
  Sent and Drafts are Gmail's own and cannot be a target.
- **Starred** and **unread** are flags. Important, the categories
  (Promotions, Social, ...) and the chats are left out.
- **Keywords** do not exist at Gmail: its labels are the folders.
  Setting one answers `501 not_supported`.
- **A replaced draft** gets a new id, as at Microsoft and JMAP.
- **Changes** come from Gmail's history, asked every
  `MAILBOX_SERVICE_SYNC_INTERVAL` seconds. Gmail pushes changes only
  through Cloud Pub/Sub, which this service does not use. Gmail keeps the
  history for about a week. After a longer pause the folders are read
  afresh.
- Quota: Gmail allows 250 units a second per account. A page of 50
  messages costs about 250. The service sends at most eight requests
  at once and keeps a pause Gmail asks for.

## Changing the client

A refresh token belongs to the client that issued it. With another
client id, every Gmail account goes to `needs_reauth` and signs in
again.

## Without Gmail over the API

`MAILBOX_SERVICE_PROVIDERS` names the kinds of account a deployment
offers. Without `gmail` in it, or without a Google client, the UI offers
no sign-in with Google. Gmail accounts can still connect over IMAP.

## Troubleshooting

- **"Error 400: redirect_uri_mismatch"**: the address the UI runs under,
  with `/ui/oauth/gmail/callback`, is not among the redirect URIs of
  step 4. Compare scheme, host and port exactly.
- **"Access blocked: ... has not completed the Google verification
  process"**: the app is in **Testing** and the account is not a test
  user. Publish the app (step 5).
- **The account asks to sign in again after a week**: the app is still
  in **Testing**. Publish it, then sign in once more.
- **"invalid_client"** on connecting: the client id or the secret does
  not match. A secret of another client, or one deleted in the console,
  is refused.
