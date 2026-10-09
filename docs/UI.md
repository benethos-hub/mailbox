# The configuration UI: rework and rules

Phase 4b of the [roadmap](ROADMAP.md), decided on 2026-09-27. It sets
the scope of the rework and the rules every page follows, the existing
ones after the rework and every page added later.

The UI is the part of the service a person uses in the browser
([CONCEPT 1.1](CONCEPT.md#11-inside-the-service)). It runs in the same
process as the API, calls the same domain services and is not part of the
OpenAPI document. This file says how it looks and behaves. CONCEPT says
what it must do and how it is secured.

## 1. Goals

1. **Simple to use.** Every task a person comes for is reached in three
   to five clicks from the overview, counting a page open, a button and a
   form submit as one click each. Section 3 has the budget.
2. **A lighter look, blue instead of grey.** One palette in section 7,
   the dark mode kept.
3. **Reworked workflows.** Connecting an account starts with the address
   and leads to OAuth or IMAP from there. Setting servers by hand stays
   possible, before and after connecting. Section 6.
4. **Paging on every long list**, the same control everywhere.
5. **Filters that look and work alike** on every list that has them.
6. **Creating, changing and removing** look and sit alike on every
   page, whatever the record.
7. **The overview starts with the signed-in user**: who they are, what
   they may do, their accounts.
8. **Rules for growth.** A new page follows a page type, a checklist and a
   test. Section 8.

## 2. Today

The UI as it was on 2026-09-27, before the rework. What the rework
changed is in the roadmap's phase 4b.

Eighteen pages, one stylesheet of 400 lines, htmx for the small
interactions and 30 lines of JavaScript. The sidebar has Overview and
Mail, then Service with Accounts and Sends, then Access with Users and
Roles. What the pages do is done: accounts, users, roles, tokens, mail
reading and writing, the audit of sends, the OAuth round trip.

What differs from page to page, and what the rework aligns:

- **Creating a record** is a separate page for accounts and users, a
  form at the end of the list for roles, and a form on the detail page
  for tokens and folders.
- **Deleting** is the last card of a detail page for accounts, users and
  roles, a button in a row for tokens and folders.
- **Filters** exist only on mail. Sends narrow by account through
  buttons, users and accounts have no filter at all.
- **Paging** exists on mail, drafts and sends. Accounts, users and roles
  list everything.
- **The overview** lists the accounts and their rights, nothing about
  the person signed in.

What is missing, all on existing domain services and API routes:

- **Webhooks** (phase 4): create, list with the delivery state, remove.
- **Status** (phase 5): accounts, sync, worker, webhooks in one view.
- **Recovery key** (phase 5): show it once, as the CLI does.
- **Changes**, optional: what the change feed recorded lately.

The rework of 2026-10 changed the frame once more: the account menu,
the folding sidebar and its dots (3), the overview's Service card (5),
the Status page gone into the overview and the Accounts list (6.5),
icons, dialogs and copy buttons (7).

## 3. Navigation and the click budget

The sidebar keeps its three groups, renamed by what a person looks for:

| Group | Pages | Who sees it |
|---|---|---|
| (top) | Overview, Mail search | everyone |
| Mailboxes | Accounts, Sends, Webhooks | Accounts with `accounts.read` on at least one account or with `accounts.connect`, Sends with `audit` on at least one account, Webhooks with `webhooks.manage` |
| Service | Users, Roles, Audit, Log, Recovery key | Users and Roles with `users.read`, Audit with `audit` in `service`, Log and Recovery key for the admin |

Each entry has its icon. **Mail search** is the list across every
account the person may read: the filter bar first, the cursor in its
search field. The mail of one account is on the account's page.

The foot of the sidebar is the **account menu**: one button with the
initial in a circle, the name and the roles. It opens a menu upwards:
"Signed in as" the name, then Your page (with `users.read`), Password,
Second factor with its state (on or off), and Sign out in red, still a
form that posts. A click elsewhere or Escape closes it. It is the one
place for what is the person's own: neither the overview nor the own
user page repeats its links.

A button beside the brand **folds the sidebar** to a narrow bar of
icons, each word its tooltip, the account menu its avatar alone. The
choice is the viewer's own, kept in the browser (`localStorage`). Under
860 px the sidebar is a bar along the top: it does not fold, and the
account menu is the avatar at its end.

A **dot** beside Accounts says an account the person may see the
status of needs a new sign-in, cannot be reached or fails to sync. One
beside Webhooks says a webhook of theirs fails. The page brings them
along, nothing is polled. Changes, if built, is a tab of the account
page, not a sidebar entry.

Every page has a **top bar** with its heading, one line under it that
says where the person is, and the page's **primary action** at the right.
Detail pages carry a **breadcrumb** in that line: Accounts › name@example.org
› Mail. A person always sees a way back without the browser.

The click budget, counted from the overview after signing in:

| Task | Clicks | Path |
|---|---|---|
| Read a mail of one account | 2 | Mail on its row of the overview or of Accounts, the message |
| Read the newest mail of every account | 2 | Mail search, the message |
| Reply to a mail | 4 | Mail search, the message, Reply, Send |
| Connect an account | 4 | Accounts, Connect, Look up, Connect (or Sign in with the provider) |
| Change an account's password | 3 | Accounts, the account, Save |
| Create a user with rights | 3 | Users, New user, Create |
| Give a user a token | 3, 4 once it has one | Users, the user, (New token), Create token |
| Revoke a token | 3 | Users, the user, Revoke |
| Add a webhook | 3 | Webhooks, New webhook, Create |
| Change a webhook | 3 | Webhooks, the webhook, Save |
| See why a webhook fails | 1 | Webhooks |
| See which account is not syncing | 1 | Overview, or Accounts (its dot shows on every page) |
| Show the recovery key | 2 | Recovery key, Show |
| Read the service log | 1 | Log |
| See who changed a user | 1 | Audit, or 2: Users, the user |

A task that needs more than five clicks is a bug of the navigation, not
of the person.

## 4. Page types

Every page is one of four types. A type fixes where things sit, so a
person who knows one page knows the next.

### 4.1 List

A table of records with a heading, the count, the filter bar (4.5), the
rows and the pager (4.6). The primary action at the top right creates a
record: **New user**, **Connect an account**, **New webhook**. A row
opens its detail page by its name. A record with a detail page is
removed there alone, in its Danger card, never from the list. A row
carries only what its detail page's header offers, as icons, and the
tick box of a batch whose actions sit in one bar above the table:
mail lists have one, and Users (disable, enable, give a role, take a
role, the role chosen in the bar).

Lists: Accounts, Users, Roles, Sends, Webhooks, Mail, Drafts, Audit,
Log, and Changes if it is built (6.6).

### 4.2 Detail

One record. Cards from top to bottom, always in this order:

1. **Facts**: what the record is. Read-only, with tags for its state.
2. **Related lists**: tokens of a user, folders of an account, devices
   of the second factor, deliveries of a webhook. A related list creates
   at its head and acts on its rows. The plus in the card's header
   (with its word, e.g. **New token**) opens the form as the first row,
   open at once while the list is empty. A pencil on a row unfolds the
   form that changes it under the row, with Save and Cancel. A bin
   removes it after a question, in the page's dialog, which holds the
   fields a removal needs (a device: the password and a code). Entries
   with no detail page of their own are removed only there. Lists with
   a batch have a tick box per row, one in the head for all, and a bar
   above the table: devices and tokens remove or revoke the ticked ones.
   Without the script every form shows at once.
3. **Change**: the form that edits the record, saved with one **Save**
   button. Fields the caller may not change are not shown.
4. **Danger**: the last card, always. One button, red, with a question
   before it: **Remove account**, **Delete user**, **Delete role**,
   **Remove webhook**. It says what happens and what stays.

A person finds the delete button of a record in the same place on every
detail page, and never anywhere else. The entries of its lists have
their bin on their row.

Detail pages: Account, User, Role, Webhook, Message, Draft.

### 4.3 Editor

A page of one form that creates a record needing more than a line:
Connect an account, New user, New role, New webhook, Compose. It has
**Create** (or
**Send**) as the primary button and **Cancel** back to the list. A record
that needs one or two fields (a token, a folder) is created
from the card it belongs to, not from an editor page.

### 4.4 Reader

The mail page of an account: folders on the left, the list in the
middle, the message where the list was when one is opened, the
breadcrumb the way back to its folder. Not a three-pane client. The
rework keeps this layout and gives it the filter bar and the pager of
every other list. The batch bar above the list asks for a folder only
while "move to" is chosen, and the head of the list ticks every row.

The header of a message holds what can be done with it, each as far as
the caller may: **Reply** with its word, then as icons Reply to all,
Forward, Download original, Mark read or unread, Star, Move (the dialog
asks the folder), Move to the trash and Delete for good (the dialog
asks first).

A message shows its keywords in a card of their own, as chips, and the
list shows them as tags. Whoever may change the message removes one
with the x on its chip and adds one with the field beside them.
Keywords starting with `$`, such as `$answered`, belong to the mail
protocol: they show beside the flags and are not changed in the UI.

### 4.5 The filter bar

One component above every list that filters. Always the same shape:

- one text field **Search** with the button, first
- **More filters**, folded, with the fields of that list in a grid
- the active filters as **chips** under the bar, each removable, and
  **Clear**
- a filter is a `GET` query, so a filtered list has a URL to keep

The options per list, with the same names where the field is the same:

| List | Search | More filters |
|---|---|---|
| Mail | text | folder and accounts (the mail of every account), from, to, subject, from day, before day, unread, starred, with attachments |
| Sends | recipient | account, who, outcome, from day, before day |
| Users | name | role, disabled, API only |
| Accounts | address | provider, status |
| Webhooks | url | account, failing |
| Changes, if built | – | account, event, from day |
| Log | text in the message or source | the least level |
| Audit | record id | who, activity (an area or a name), from day, before day |

Mail's filters are the API's query parameters, a test holds them
together (`test_openapi.py`). Sends, Users, Accounts, Webhooks and Audit
have their filters at the API as well, by the same list methods of the
domain and with the same query names, held together by a test too. A
day in the UI is a time with a zone at the API. The account of Sends is
`accounts` at the API, and API only of Users is `ui_sign_in=false`
there. Drafts have no filter bar: no
provider searches its drafts. The drafts folder in Mail can be searched.

Sends are one list for every account the caller may audit, the account
one of its filters, paged with one cursor across the accounts.

### 4.6 Paging

Every list that can grow beyond one page pages with the cursor of the
domain and shows one pager under the table: **Newest** back to the first
page, **Older** for the next. Accounts and Users, sorted by address and
by name, name them **First** and **Next**. Page sizes are constants of
the page module. A paged card shows no count in its header, since there
is no total. Roles, tokens and webhooks list everything.

### 4.7 Messages and errors

A form that goes through answers with a redirect and one message, shown
once at the top of the next page (Post/Redirect/Get, CONCEPT 1.1).
Success in green, a refusal in the page's own words in red, never a
status code. An editor that is refused is shown again at once, with
what was typed and the reason at the top, and answers `400`. A password
is never shown again. An action without fields, such as a delete, goes
back to its page with the reason. A page that cannot be shown at all is
the error page with a way back.

## 5. The overview

The first page after signing in. Its cards, in order:

1. **You**: name, roles, what the rights add up to, the last sign-in
   (stored with the password). The account menu has the links. The
   card says at a glance whether this user may read mail and send it
   anywhere, the warning the API and the MCP server also give.
2. **Your accounts**: one row per account with its address, status,
   unread count where cheap, and what you may do there. A row opens the
   account's mail, the address opens the account.
3. **Service**: only for those with `accounts.read`: accounts that need
   attention (needs_reauth, unreachable, sync failing), webhooks failing.
   Each line links to the page that fixes it. When all is well, it says
   so in one line. Under it the sync worker: running and its interval,
   or switched off and why, push with how many accounts it watches of
   how many it may, its last pass.

## 6. Workflows

### 6.1 Connecting an account

Starts with the address and nothing else. One page, three steps, the
next step appears under the last one:

1. **Address.** One field, **Look up**. The lookup asks the discovery
   sources (CONCEPT 5.8) and, from the domain, which OAuth providers this
   deployment offers.
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
   - nothing found: **Set up by hand** open at once, with the server
     fields
   **Set up by hand** is always there, folded when something was found,
   unless the deployment offers neither IMAP nor POP3. The same for
   **Set up a JMAP server by hand**. A kind of account the deployment
   does not offer is not shown at all.
   Where no source names a provider the deployment signs in with, its
   **Sign in with** stays offered: a custom domain can be at Microsoft.
3. **Connect.** The domain tries the servers before storing anything.
   Success lands on the account page with **connected**. A refusal comes
   back to this page with the fields kept and the reason under the
   password.

After connecting, the account page's **Change** card edits the servers,
the display name and the password, for IMAP accounts. OAuth accounts have
**Sign in again** and, where the provider offers codes, **Sign in again
with a code** instead of a password. Nothing of this needs a new domain
call: `discover`, `create`
and `update` exist.

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
exist only here (a user, a role, a token, a folder).

### 6.3 Users, roles, tokens

New user: name, where it signs in, roles as tick boxes, grants in the
grant editor. **Signs in to** is "the API only" by default, or "the UI
and the API" (CONCEPT 7.5, the UI sign-in switch). With the UI, the
service makes a one-time password and shows it once, as a token.

A user that signs in to the API only has the tag **API only** in the
list and on its page, and the list filters by it. Its page has no
Password card. The Change card switches the UI sign-in on and off, but
not for the signed-in user itself. Switched on, the Password card
offers a one-time password. The Users list ticks users and disables,
enables, gives or takes a role of all of them at once: each change goes
through the domain as one change of that user would, recorded per
user, and those the caller may not change are named with the reason.
Nobody disables itself that way either. New role is an editor page too. It takes the path
`/ui/roles/new`, so the UI cannot open a role named `new`. It offers four
templates that fill the form, Reader, Agent, Sender and Operator
([PERMISSIONS.md](PERMISSIONS.md) 8.7). Nothing is stored until the role
is created, and Sender wants the recipients named.

The user page has three tabs, each an address of its own (`?tab=`),
drawn by the service: **Rights** with the facts, the effective rights
and the Change card, **Access** with the sign-in (to the UI, the second
factor, the last sign-in, and for the person's own page the links to
Password and Second factor), the Password card for another user, its
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

The second factor ([AUTHENTICATION.md](AUTHENTICATION.md)) has a page of
its own, **Second factor**, reached from the foot of the sidebar and the
person's own user page. It has a card per method of the second factor
and one for the recovery codes. The card **Authenticator app (TOTP)**
lists the devices with their name, when each
was added and last used. **Add a device** asks for its name and the
password, and with a device there already a code, then shows the QR
code with the key as text and a field for the first code. The first
device brings the ten recovery codes, shown once, with a button that
copies them all and offered as a text file to download. The pencil on
a device's row takes the new name, its bin the password and a code in
the dialog. With two devices or more they can be ticked and removed
together after one password and one code. The
Recovery codes card says how many are left and makes new ones after
the password and a code. Another user's page lists its devices to a user with
`get_second_factor`, with **Remove** for one to a user with
`remove_totp_device`, as the bin on its row, and **Remove every device** to a user with
`remove_second_factor`. After the password, a user with a factor sees
the code page, outside the layout as the sign-in is, which takes a code
of any device or a recovery code.

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

No page of its own any more. The Accounts list shows each account's
status, last sync and last error, the overview's Service card the
worker, the Webhooks list the webhooks with their last delivery, and
the dots of the sidebar say where to look (3). Nothing is polled for
it. The worker keeps its last pass and each account's last sync and
last error in memory, so they are empty after a restart until the
first pass. `GET /v1/status` answers the same for the API.

The recovery key page shows the key once after **Show**, with the
warning of the CLI, and only to a user with `admin`. **Show** asks for the user's password again, and for a code when the
user has a second factor ([AUTHENTICATION.md](AUTHENTICATION.md) 7). The key is never
stored or logged, the log only says that it was shown and to whom.

The Audit page lists the audit of administration of
[AUDIT.md](AUDIT.md), newest first, to a user with `audit` in
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

### 6.6 Changes, optional

A list of the change feed per account, newest first: event, message,
when. It shows what webhooks would have received, which helps when a
receiver reports nothing. Built last, if at all.

## 7. Look

- **Palette**: light and bluish. Background a cool off-white, cards
  white, borders a light blue-grey, text a dark blue-grey, the accent a
  clear blue used for links, the primary button and the active
  navigation entry. State colours stay: green ok, amber warn, red bad,
  each with a soft background for tags and notices. Dark mode keeps the
  same tokens with dark values, chosen by the system.

  The tokens of `app.css`. Every text colour keeps 4.5:1 (WCAG AA for
  small text) against every background it is used on, in both modes.
  `test_ui_frame.py` computes it from the stylesheet.

  | Token | Light | Dark |
  |---|---|---|
  | `--bg` | `#f9fbfe` | `#0f1420` |
  | `--surface` | `#ffffff` | `#171d2b` |
  | `--surface-2` | `#eef3fa` | `#1f2736` |
  | `--border` | `#dde5f0` | `#2c3648` |
  | `--text` | `#14213d` | `#e6ebf5` |
  | `--text-muted` | `#56657e` | `#9aa8bf` |
  | `--text-faint` | `#5f6e86` | `#8391a8` |
  | `--accent` | `#2560c8` | `#6ea0ff` |
  | `--accent-soft` | `#e8f0fc` | `#1d2c4a` |

- **Density**: a little more air than today. Row height 40 px, card
  padding 20 px, one type size for text and one for the small line under
  a name.
- **Icon and logo**: the project's 3D icon from `assets/logo/` heads
  the sidebar and is the favicon. The 3D logo with its word mark
  stands above the card of the sign-in page and of the page a
  provider sends the browser back to (`bare.html`), in dark mode
  with a light word mark. `assets/build.py` makes the copies in
  `static/img/`.
- **Sidebar**: light, not dark, with the accent on the active entry.
  Collapses to a top bar under 860 px as today.
- **Components**: everything a page uses is a macro in
  `components/ui.html`, the grant editor in `components/grants.html`, the
  connection fields in `components/connection.html`, the rows of the
  audit in `components/audit.html`, the fields of a webhook in
  `components/webhook.html`. A page has no
  markup of its own for a button, a tag, a field, a card header, a pager
  or a filter bar. The rework adds `filter_bar` with its chips,
  `facts`, `related` and `breadcrumb` and makes the pages use them.
- **Icons**: a hand-picked set of [Bootstrap Icons](https://icons.getbootstrap.com/)
  (MIT), one sprite `static/img/icons.svg` with the licence beside it.
  `assets/icons.py` names them and makes the sprite from the npm
  package of a pinned version, checked by its SHA-256. A new icon is a
  line there. The macro `icon(name)` draws one in the colour of the
  text around it. The primary action of a page (Create, Save, Send,
  Connect, Write, Mail) and the red button of the Danger card keep
  their word, with an icon beside it. Everything repeated per row is
  an icon alone, its word the tooltip (`title`) and, with the record's
  name, what a screen reader hears (`aria-label`). A touch screen
  shows no tooltip: an icon that is not plain on its own (Sends,
  Verify) gets its word back there and in a narrow window. Pencil,
  bin, plus and envelope stand alone.
- **The question before a form**: a form that changes much carries
  `data-confirm`, the question and in a sentence after it what happens
  and what stays. `app.js` asks it in the page's own dialog, with the
  form's button word (`data-confirm-label`) and red where it cannot be
  undone (`data-confirm-danger`). Escape and Cancel close it, nothing
  is sent. Without the dialog the browser asks.
- **Copy**: every secret shown once has a copy button beside it, the
  recovery codes one for all of them. Where the browser offers no
  clipboard, a page not on https or localhost, the button selects the
  text instead.
- **Times in lists**: tokens, devices, sends, webhooks and deliveries
  show a time under a day ago as "3 minutes ago", older ones as date
  and time, the full stamp always as the tooltip (macro `ago`). Audit,
  log, the facts of a record and the message keep the full stamp.
- **Keys**: `/` puts the cursor in the page's search field, Escape
  closes the dialog.
- **No inline style or script**: the content security policy stays.
  htmx only where a page asks the service again by itself, the
  sign-in with a code. Every other form is a plain post, and a
  destructive one asks first through `data-confirm`.
- **Nothing from elsewhere**: no CDN. Every script, style, font and
  image the UI loads is kept under `static/`, as htmx and the icons
  are. A test checks the templates and the stylesheet for it.

## 8. Rules for building and extending

These rules bind every page, the reworked ones and the ones to come.

1. **One page, one type** of section 4. A page that fits none needs a
   new type in this file first.
2. **Routes** live in one module per area under `web/pages/routes/`,
   templates under `templates/pages/`, one template per page, named as
   the page. Partials are pieces of one page, components are macros used
   by several.
3. **The route decides nothing.** It reads the form, calls one domain
   method and renders or redirects. Rights are the domain's; the page
   only hides what `caller.allows(...)` denies, with the same names the
   API uses in `x-permission`. The mail pages also hide what the account
   cannot do, by its `capabilities` (`web/pages/rights.py`): a POP3
   account shows no flags, folders, trash, filters or drafts.
4. **A page has the context it needs, nothing more.** `page` names the
   sidebar entry, `me` the user, `csrf` the token. A template does not
   compute what a route can pass.
5. **Every form that goes through is Post/Redirect/Get** with one
   message. A refused editor is shown again as 4.7 says. Every
   destructive form asks first. Every list with a filter is a `GET`.
6. **Words**: the button names of 6.2, tags in lower case, headings in
   sentence case, the record's name in the heading of its detail page.
7. **Tests**: a page has at least one test in `tests/web/pages/test_ui_*.py` that
   opens it as a user with the right, one that shows it hidden without
   the right, and one per form. `live/ui.py` walks every workflow of
   section 6 against the test accounts.
8. **Checklist for a new page**: route module or a route in one; the
   template of its type; the sidebar entry with its right and its icon;
   icons only from the sprite, a new one added in `assets/icons.py`;
   nothing loaded from elsewhere, no CDN; the tests of rule 7; a line
   in this file's section 3 table and, if it changes a workflow, in
   section 6; the roadmap item; a CHANGELOG entry only when a person
   using the API notices.

## 9. Order of work

All four steps are done, as the roadmap's phase 4b records.

1. **This file**, one pull request of documentation. CONCEPT 1.1 and the
   roadmap's phase 4b point here.
2. **The frame**: palette, sidebar, top bar with breadcrumb, the
   components of section 7, the four page types. The existing pages move
   into the frame without changing what they do. Tests and `live/ui.py`
   stay green throughout. Several pull requests, one per group of pages:
   frame and overview, accounts and the connect workflow, users and
   roles, mail and sends.
3. **The missing pages** in the new frame: webhooks, then status and the
   recovery key, then changes if wanted.
4. **Paging and filters** on the lists that lack them, once the frame
   has the components.

## 10. Decided

- 2026-09-27: the rework as this file describes it.
- 2026-09-27: the recovery key only for the `admin` grant, after the
  password once more (6.5).
- 2026-09-27: the sync state in the worker's memory, the last sign-in
  stored (5, 6.5).
- 2026-09-27: a delivery log for webhooks (6.4).
- 2026-09-27: the Changes page not in phase 4b (6.6).
- 2026-09-27: a lighter background. The other colours follow from the
  contrast rule of section 7.
- 2026-10-06: the filters of Sends, Users, Accounts and Webhooks at the
  API as well, the UI's query names those of the API (4.5).
- 2026-10-06: keywords in the UI, on one message at a time, those of
  the mail protocol not changed there (4.4).
- 2026-10-06: Accounts and Users paged like their lists in the API,
  Roles not (4.6).
- 2026-10-09: icons with tooltips in place of words on what repeats
  per row, Bootstrap Icons as an own sprite, the primary action and
  the Danger button keep their word (7).
- 2026-10-09: no CDN, everything the UI loads kept under `static/` (7).
- 2026-10-09: the account menu in the sidebar's foot, the sidebar
  folding to icons, dots for what needs a look, Mail search, the
  Status page gone into the overview and the Accounts list (3, 5, 6.5).
- 2026-10-09: a related list creates at its head and acts on its rows,
  the form at a row unfolding under it. Removing on the row only for
  entries without a detail page. A batch for devices and tokens, for
  users later, none for accounts, roles and webhooks (4.1, 4.2, 6.2).
- 2026-10-09: the user page in tabs Rights, Access, Activity, the grant
  editor in lines, a batch of the Users list (6.3).
- 2026-10-09: Mail and Sends on each row of the Accounts list, Verify on
  the account page alone; the message's actions in its header, its
  keywords as chips (4.1, 4.4).
- 2026-10-09: webhooks changeable, a Change card and a new signing
  secret on their page, with the API's `update_webhook` and
  `renew_webhook_secret` (6.4).
- 2026-10-09: the page's own dialog in place of the browser's
  question, copy buttons beside every secret shown once, relative
  times in lists (7).

The Service card of the overview shows to everyone with `accounts.read`.
