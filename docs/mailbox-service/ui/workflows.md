# UI: the workflows

Part of [UI.md](../UI.md): section 6.

## 6. Workflows

### 6.1 Connecting an account

Starts with the address and nothing else. One page, three steps, the
next step appears under the last one:

1. **Address.** One field, **Look up**. The lookup asks the discovery
   sources (CONCEPT 5.8) and, from the domain, which OAuth providers this
   deployment offers. It answers the page itself, no redirect: it
   changes nothing, and the address stays out of the access log.
2. **How to connect.** One card per way, the recommended one first:
   - a provider the deployment signs in with (Microsoft, Google):
     **Sign in with Microsoft**, the address as the login hint, no
     password field, and beside it **Sign in with a code**. That one
     opens a page with the code and the provider's link, which asks
     every few seconds by htmx and goes on to the account once the
     person signed in. **Check now** asks without script. Where the
     provider cannot send the browser back, as with the project's app
     away from localhost, only the code is offered. Google offers no
     code for Gmail: **Sign in with Google** stands alone
   - a provider found with servers: the password field, the servers
     folded under **Servers**, with the source and whether it is trusted
   - nothing found: the first card to set up by hand open at once, with
     the server fields
   One card per kind set up by hand is always there: **Set up IMAP by
   hand**, **Set up POP3 by hand** and **Set up JMAP by hand**, each
   with what to know of its kind. They are folded unless nothing was
   found. A kind of account the deployment does not offer is not shown
   at all.
   Where no source names a provider the deployment signs in with, its
   **Sign in with** stays offered: a custom domain can be at Microsoft.
3. **Connect.** The domain tries the servers before storing anything.
   Success lands on the account page with **connected**. A refusal comes
   back to this page with the fields kept and the reason under the
   password.

After connecting, the account page's **Change** card edits the servers,
the display name, the password and the name of the receiving server,
for IMAP, POP3 and JMAP accounts.
There **Look in the mailbox** reloads the page with the names receiving
servers wrote into the newest ten mails, each with a copy button, how
many mails carry it and in how many it is on top, for the field of the
receiving server's name.
The page reads nothing from the mailbox without it.
OAuth accounts have
**Sign in again** and, where the provider offers codes, **Sign in again
with a code** instead of a password. **Look in the
mailbox** reads through `server_names`, as
`GET /v1/accounts/{account_id}/server-names` does.

### 6.2 Creating, changing, removing

The same places on every record, from 4.2: create from the list's
primary action or from the plus of the card the entry belongs to,
change in the Change card or with the pencil on the entry's row, remove
in the Danger card or with the bin on the entry's row. A folder's
pencil sits at the folder shown: a new name saves at once, another
place inside asks first. Folders with a role (inbox, sent, ...) have
neither. The same words everywhere:
**New**, **Create**, **Save**, **Cancel**, **Remove** for things that
exist elsewhere (an account, a webhook), **Delete** for things that
exist only here (a user, a role, a folder), **Revoke** for a token.

### 6.3 Users, roles, tokens

New user: name, where it signs in, roles as tick boxes, grants in the
grant editor. **Signs in to** is "the API only" by default, or "the UI
and the API" (CONCEPT 7.5, the UI sign-in switch). With the UI, a
tick box, set at first, has the service make a one-time password and
show it once, as a token. The box shows for a caller with
`set_password`.

A user that signs in to the API only has the tag **API only** in the
list and on its page, and the list filters by it. Its page has no
Password card. The Change card switches the UI sign-in on and off, but
not for the signed-in user itself. Switched on, the Password card
offers a one-time password. The Users list ticks users and disables,
enables, gives or takes a role of all of them at once: each change goes
through the domain as one change of that user would, recorded per
user. All or nothing (4.1): where the caller may not change one of
them, none changes and those are named with the reason. Nobody
disables itself that way either. New role is an editor page too. It takes the path
`/ui/roles/new`, so the UI cannot open a role named `new`. It offers four
templates that fill the form, Reader, Agent, Sender and Operator
([PERMISSIONS.md](../PERMISSIONS.md) 8.7). Nothing is stored until the role
is created, and Sender wants the recipients named.

The user page has three tabs, each an address of its own (`?tab=`),
drawn by the service: **Rights** with the facts, the effective rights
and the Change card, **Access** with the sign-in (to the UI, the second
factor, the last sign-in, and for the person's own page the links to
Password and Second factor). The page Password asks for the current
password and the new one twice, and with a second factor that factor
too, but not at the forced change after the sign-in. The Access tab
holds as well the Password card for another user, its
devices and the tokens, and **Activity**. The Danger card stays below
the tabs, the same on each. A form that comes back refused shows its
tab. Activity is the user's newest ten activities of the audit, for
`audit` in `service`, with links to all of them and to what was done to
the user. A role's page has no tabs: facts, Change, Danger. A token is
created at the head of the Tokens list and shown once.

The grant editor, on a user's and a role's page alike, shows one line
per grant as it reads. Its pencil unfolds the grant's fields under it,
its bin marks it removed, struck through, a tick box under the icon.
The plus at the top unfolds an empty grant. Nothing is stored before
the one Save of the Change card. Service rights and grants fold alike
on both pages.

The second factor ([AUTHENTICATION.md](../AUTHENTICATION.md)) has a page of
its own, **Second factor**, reached from the foot of the sidebar and the
person's own user page. The line under its title says with a tag
whether the second factor is on or off. It has a card per method of the
second factor and one for the recovery codes. The card **Authenticator app (TOTP)**
lists the devices with their name, when each
was added and last used. **Add a device** asks in a dialog for its name
and the password, and with the second factor on already that factor,
then shows the QR
code with the key as text and a field for the first code, in two
numbered steps, Cancel beside the button. The first
device brings the ten recovery codes, shown once, with a button that
copies them all and offered as a text file to download. The pencil on
a device's row takes the new name, its bin the password and a code in
the dialog. With two devices or more they can be ticked and removed
together after one password and one code. The
Recovery codes card says how many are left, and **Make new codes** in
its head makes new ones after the password and the second factor in a
dialog. New ones show once in a card of their own, **Your new recovery
codes**. Another user's page lists its devices to a user with
`get_second_factor`, with **Remove** for one to a user with
`remove_totp_device`, as the bin on its row, and **Remove every device** to a user with
`remove_second_factor`. After the password, a user with a factor sees
the code page, **Confirm it is you**, outside the layout as the
sign-in is.

Every step that asks for the second factor shows one method at a time
(`components/factor.html`), in a group named **Confirm it is you**: a
passkey where the user has one and the browser makes them, else the
code of an authenticator app, else a recovery code. The passkey is a
framed block that says what the browser will ask, the code fields set
their text in the monospace font. **Try another way** lists the methods
of the user, each a button with a line that says what it is, and a pick
shows its field. A passkey picked there asks the browser at once when
the form lacks nothing else. Where the passkey shows, the form's own
button asks the browser for it, then sends the form. While the browser
asks, the buttons are locked and a notice says it waits. A passkey not
used says so in that notice. While the list shows, the form's buttons
are locked until a pick. Nothing stores the method used. After a wrong
code the code page, a dialog opened again and the page Password show
the field of that code first again. Without
`passkey.js` the field of the first code shows alone, and it takes a
code of the app and a recovery code alike.

A dialog of the second factor whose form is refused, a wrong code or
password, opens again on the page that follows, the message in it and
not at the top of the page. Without JavaScript the dialogs and the
forms of a row stand open in the page, and the buttons that open and
close them are hidden. On a phone the description in the head of a
card has a line of its own under the title.

The card **Passkeys** works as the one of the authenticator apps.
**Add a passkey** asks in a dialog for its name and the password,
and with a factor on the second factor, then shows **Make the
passkey**, which asks the browser, Cancel beside it. `passkey.js`
offers a passkey only
where the browser makes passkeys, and the page says so where it makes
none, at an address or over HTTP. Another user's page lists its
passkeys beside its devices, with **Remove** to a user with
`remove_passkey`.

### 6.4 Webhooks

The list shows the URL, the events, the accounts, the last delivery and
the last error as a red tag with the reason. New webhook from the list:
URL, events as tick boxes, accounts as tick boxes or "every account I may
read". The secret is shown once on the detail page after creating, as a
token is. The detail page has the facts, the last deliveries, the Change
card, the card **Signing secret** and Remove. The service keeps the last
20 attempts of each webhook: when, the events, the receiver's status
code and the error. The Change card holds the fields of New webhook,
filled. Saving keeps the deliveries, where the posts stand and the
secret. **New secret** asks first, since the one before stops at once,
and shows the new one once, as after creating.

### 6.5 The state of the service and the recovery key

The state of the service has no page of its own. The Accounts list shows each account's
status, last sync and last error, the overview's Service card the
worker, the Webhooks list the webhooks with their last delivery, and
the dots of the sidebar say where to look (3). Nothing is polled for
it. The worker keeps its last pass and each account's last sync and
last error in memory, so they are empty after a restart until the
first pass. `GET /v1/status` answers the same for the API.

The recovery key page shows the key once after **Show**, with the
warning of the CLI, and only to a user with `admin`. **Show** asks in a dialog for the user's password again, and for the second factor when the
user has one ([AUTHENTICATION.md](../AUTHENTICATION.md) 7). The key is never
stored or logged, the log only says that it was shown and to whom.

The Audit page lists the audit of administration of
[AUDIT.md](../AUDIT.md), newest first, to a user with `audit` in
`service`: sign-ins, failed ones and refused tokens, and who changed
users, tokens, roles, accounts and webhooks. Each row has the time, who
and how they came, the activity and what was done, and the outcome. A
record's id narrows the list to that record. Unlike the log it outlives
a restart, for `MAILBOX_SERVICE_AUDIT_DAYS` days.

The log page lists the newest lines of the service log, newest first,
to the same admin alone: they name users, client addresses and
accounts. The service keeps the last 1000 lines of its process in
memory, so the page starts empty after a restart. Each line has its
time, level, source and message, a traceback with it, and every secret
the service holds masked (CONCEPT 7.4). The filter bar searches the
message and the source and sets the least level.

### 6.6 Writing mail

A message's page offers **Reply**, **Reply to all** and **Forward**,
each opening Compose with the original named. A forward goes quoted in
the text or as an attachment. Compose takes the text, an HTML version if
wanted, and files. **Send** asks first and sends at once. **Save as
draft** stores it, and a stored draft opens in the same form to save,
send or delete. A draft is replaced as a whole and may get a new id from
the provider: the form goes on with the id the answer brings (U4). Each
time the form is shown it carries a new idempotency key, so a second
click on Send answers the first result. A refused form comes back with
what was typed, its files to be chosen again: a browser cannot be handed
files.

**Put in outbox** asks first and puts the message, or the draft, into
the account's outbox: it is kept as a draft and goes out in the
background, also while the mail server is away. **Send at** names when,
in UTC, at most 30 days ahead. The person lands on **Outbox**, reached
from Drafts too: each send with its recipients, when it is due, its
state and its tries, filtered by state. A send that waits has **Cancel
send**, for whoever queued it and whoever manages the account. A send
whose outcome is unknown says so: it is not sent again, and its draft
stays for the person to look whether it arrived. Sends lists the
outcomes of the outbox too, each with a link to it.

### 6.7 Changes, optional

A list of the change feed per account, newest first: event, message,
when. It shows what webhooks would have received, which helps when a
receiver reports nothing. Built last, if at all.
