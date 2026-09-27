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

## 3. Navigation and the click budget

The sidebar keeps its three groups, renamed by what a person looks for:

| Group | Pages | Who sees it |
|---|---|---|
| (top) | Overview, Mail | everyone |
| Mailboxes | Accounts, Sends, Webhooks | with a right on at least one account, Webhooks with `webhooks.manage` |
| Service | Users, Roles, Status, Recovery key | with `users.manage`, Status with `accounts.read`, Recovery key for the admin |

The foot of the sidebar names the signed-in user and links to their own
page, Password and Sign out. Changes, if built, is a tab of the account
page and of Status, not a sidebar entry.

Every page has a **top bar** with its heading, one line under it that
says where the person is, and the page's **primary action** at the right.
Detail pages carry a **breadcrumb** in that line: Accounts › name@example.org
› Mail. A person always sees a way back without the browser.

The click budget, counted from the overview after signing in:

| Task | Clicks | Path |
|---|---|---|
| Read a mail of one account | 3 | account on the overview, Mail, the message |
| Read the newest mail of every account | 2 | Mail, the message |
| Reply to a mail | 4 | Mail, the message, Reply, Send |
| Connect an account | 4 | Accounts, Connect, Look up, Connect (or Sign in with the provider) |
| Change an account's password | 3 | Accounts, the account, Save |
| Create a user with rights | 3 | Users, New user, Create |
| Give a user a token | 3, 4 once it has one | Users, the user, (New token), Create token |
| Revoke a token | 3 | Users, the user, Revoke |
| Add a webhook | 3 | Webhooks, New webhook, Create |
| See why a webhook fails | 1 | Webhooks |
| See which account is not syncing | 1 | Overview, or Status |
| Show the recovery key | 2 | Recovery key, Show |

A task that needs more than five clicks is a bug of the navigation, not
of the person.

## 4. Page types

Every page is one of four types. A type fixes where things sit, so a
person who knows one page knows the next.

### 4.1 List

A table of records with a heading, the count, the filter bar (4.5), the
rows and the pager (4.6). The primary action at the top right creates a
record: **New user**, **Connect an account**, **New webhook**. A row
opens its detail page by its name. A row carries no delete button and no
form. The one exception is the tick box for a batch on mail lists, whose
actions sit in one toolbar above the table.

Lists: Accounts, Users, Roles, Sends, Webhooks, Mail, Drafts, Changes.

### 4.2 Detail

One record. Cards from top to bottom, always in this order:

1. **Facts**: what the record is. Read-only, with tags for its state.
2. **Related lists**: tokens of a user, folders of an account, deliveries
   of a webhook. Each with its own **New** form as the last row of the
   card, folded until opened.
3. **Change**: the form that edits the record, saved with one **Save**
   button. Fields the caller may not change are not shown.
4. **Danger**: the last card, always. One button, red, with a question
   before it: **Remove account**, **Delete user**, **Delete role**,
   **Remove webhook**. It says what happens and what stays.

A person finds the delete button in the same place on every detail
page, and never anywhere else.

Detail pages: Account, User, Role, Webhook, Message, Draft.

### 4.3 Editor

A page of one form that creates a record needing more than a line:
Connect an account, New user, New role, Compose. It has **Create** (or
**Send**) as the primary button and **Cancel** back to the list. A record
that needs one or two fields (a token, a folder, a webhook) is created
from the card it belongs to, not from an editor page.

### 4.4 Reader

The mail page of an account: folders on the left, the list in the
middle, the message where the list was when one is opened, with **Back
to the list** at the top. Not a three-pane client. The rework keeps this
layout and gives it the filter bar and the pager of every other list.

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
| Changes | – | account, event, from day |

Mail's filters are the API's query parameters, a test holds them
together (`test_openapi.py`). The others need no new API: the domain's
list methods narrow what they give. Drafts have no filter bar: no
provider searches its drafts. The drafts folder in Mail can be searched.

Sends are one list for every account the caller may audit, the account
one of its filters, paged with one cursor across the accounts.

### 4.6 Paging

Every list that can grow beyond one page pages with the cursor of the
domain and shows one pager under the table: **Newest** back to the first
page, **Older** for the next. Page sizes are constants of the page
module. Accounts, Users and Roles page too, once the tables have a
cursor. Until then they list everything and the pager stays hidden, so
the layout does not change when paging arrives.

### 4.7 Messages and errors

A form answers with a redirect and one message, shown once at the top of
the next page (Post/Redirect/Get, CONCEPT 1.1). Success in green, a
refusal in the page's own words in red, never a status code. A field that
was wrong is shown again with its value and the reason under it. A page
that cannot be shown at all is the error page with a way back.

## 5. The overview

The first page after signing in. Its cards, in order:

1. **You**: name, roles, what the rights add up to, the last sign-in
   (stored with the password),
   links to your page, Password and, for the admin, Recovery key. The
   card says at a glance whether this user may read mail and send it
   anywhere, the warning the API and the MCP server also give.
2. **Your accounts**: one row per account with its address, status,
   unread count where cheap, and what you may do there. A row opens the
   account's mail, the address opens the account.
3. **Service**: only for those with `accounts.read`: accounts that need
   attention (needs_reauth, unreachable, sync failing), webhooks failing,
   the worker's last pass. Each line links to the page that fixes it.
   Empty when all is well, then it says so in one line.

## 6. Workflows

### 6.1 Connecting an account

Starts with the address and nothing else. One page, three steps, the
next step appears under the last one:

1. **Address.** One field, **Look up**. The lookup asks the discovery
   sources (CONCEPT 5.8) and, from the domain, which OAuth providers this
   deployment offers.
2. **How to connect.** One card per way, the recommended one first:
   - a provider the deployment signs in with (Microsoft, later Google):
     **Sign in with Microsoft**, the address as the login hint, no
     password field
   - a provider found with servers: the password field, the servers
     folded under **Servers**, with the source and whether it is trusted
   - nothing found: **Set up by hand** open at once, with the server
     fields
   **Set up by hand** is always there, folded when something was found.
   Where no source names a provider the deployment signs in with, its
   **Sign in with** stays offered: a custom domain can be at Microsoft.
3. **Connect.** The domain tries the servers before storing anything.
   Success lands on the account page with **connected**. A refusal comes
   back to this page with the fields kept and the reason under the
   password.

After connecting, the account page's **Change** card edits the servers,
the display name and the password, for IMAP accounts. OAuth accounts have
**Sign in again** instead of a password. Nothing of this needs a new
domain call: `discover`, `create` and `update` exist.

### 6.2 Creating, changing, removing

The same three places on every record, from 4.2: create from the list's
primary action or from the card the record belongs to, change in the
Change card, remove in the Danger card. The same words everywhere:
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
offers a one-time password. New role is an editor page too. It takes the path
`/ui/roles/new`, so the UI cannot open a role named `new`. The user page shows the effective rights as
today, then tokens, then Change, then Danger. Roles the same without
tokens. A token is created in the Tokens card and shown once.

### 6.4 Webhooks

The list shows the URL, the events, the accounts, the last delivery and
the last error as a red tag with the reason. New webhook from the list:
URL, events as tick boxes, accounts as tick boxes or "every account I may
read". The secret is shown once on the detail page after creating, as a
token is. The detail page has the facts, the last deliveries, and Remove.
The service keeps the last 20 attempts of each webhook: when, the events,
the receiver's status code and the error.
A webhook has no Change card: the API has none, a person removes and
recreates it.

### 6.5 Status and the recovery key

Status is one page of three cards: accounts with status, last sync and
last error, the worker with its interval and last pass, the webhooks
with their last delivery. Each row links where it can be fixed. Nothing
is polled for the page. The worker keeps its last pass and each
account's last sync and last error in memory, so they are empty after a
restart until the first pass.

The recovery key page shows the key once after **Show**, with the
warning of the CLI, and only to a user with the `admin` grant on every
account. **Show** asks for the user's password again. The key is never
stored or logged, the log only says that it was shown and to whom.

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
  `test_ui.py` computes it from the stylesheet.

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
- **Sidebar**: light, not dark, with the accent on the active entry.
  Collapses to a top bar under 860 px as today.
- **Components**: everything a page uses is a macro in
  `components/ui.html`, the grant editor in `components/grants.html`, the
  connection fields in `components/connection.html`. A page has no
  markup of its own for a button, a tag, a field, a card header, a pager
  or a filter bar. The rework adds `filter_bar`, `chips`, `facts`,
  `related` and `breadcrumb` and makes the pages use them.
- **No inline style or script**: the content security policy stays.
  htmx for confirmations, the modal and partial refreshes of a list.

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
   API uses in `x-permission`.
4. **A page has the context it needs, nothing more.** `page` names the
   sidebar entry, `me` the user, `csrf` the token. A template does not
   compute what a route can pass.
5. **Every form is Post/Redirect/Get** with one message. Every
   destructive form asks first. Every list with a filter is a `GET`.
6. **Words**: the button names of 6.2, tags in lower case, headings in
   sentence case, the record's name in the heading of its detail page.
7. **Tests**: a page has at least one test in `tests/test_ui_*.py` that
   opens it as a user with the right, one that shows it hidden without
   the right, and one per form. `live/ui.py` walks every workflow of
   section 6 against the test accounts.
8. **Checklist for a new page**: route module or a route in one; the
   template of its type; the sidebar entry with its right; the tests of
   rule 7; a line in this file's section 3 table and, if it changes a
   workflow, in section 6; the roadmap item; a CHANGELOG entry only when
   a person using the API notices.

## 9. Order of work

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

The Service card of the overview shows to everyone with `accounts.read`,
and Accounts, Users and Roles list everything with the pager hidden,
until a need shows otherwise.
