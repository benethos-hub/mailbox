# UI: the pages

Part of [UI.md](../UI.md): sections 3 to 5.

## 3. Navigation and the click budget

The sidebar has three groups, named by what a person looks for:

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
place for what is the person's own: the overview does not repeat its
links, and the own page's Access tab links them beside the facts they
belong to.

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
Detail pages carry a **breadcrumb** in that line: Mail search ›
name@example.org › Inbox. A person always sees a way back without the
browser.

The click budget, counted from the overview after signing in:

| Task | Clicks | Path |
|---|---|---|
| Read a mail of one account | 2 | Mail on its row of the overview or of Accounts, the message |
| Read the newest mail of every account | 2 | Mail search, the message |
| Reply to a mail | 5 | Mail search, the message, Reply, Send, Send in the dialog |
| Connect an account | 4 | Accounts, Connect, Look up, Connect (or Sign in with the provider) |
| Change an account's password | 3 | Accounts, the account, Save |
| Create a user with rights | 3 | Users, New user, Create |
| Give a user a token | 4, 5 once it has one | Users, the user, Access, (New token), Create token |
| Revoke a token | 5 | Users, the user, Access, Revoke, Revoke in the dialog |
| Add a webhook | 3 | Webhooks, New webhook, Create |
| Change a webhook | 3 | Webhooks, the webhook, Save |
| See why a webhook fails | 1 | Webhooks |
| See which account is not syncing | 1 | Overview, or Accounts (its dot shows on every page) |
| Show the recovery key | 3 | Recovery key, Show, Show in the dialog |
| Read the service log | 1 | Log |
| See who changed a user | 1 | Audit, or 4: Users, the user, Activity, What was done to it |

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

A batch of what the service keeps, users, tokens and devices, is all or
nothing: it changes every ticked entry or none. Where one entry is
refused, nothing changes, and the message names each refused entry
with the reason. A batch of messages acts on the mail server, which
cannot take back a part: it names the messages it could not change.

Lists: Accounts, Users, Roles, Sends, Webhooks, Mail, Drafts, Audit,
Log, and Changes if it is built (6.7).

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

Detail pages: Account, User, Role, Webhook, Message, Conversation.

### 4.3 Editor

A page of one form that creates a record needing more than a line:
Connect an account, New user, New role, New webhook, Compose. It has
**Create** (or
**Send**) as the primary button and **Cancel** back to the list. A record
that needs one or two fields (a token, a folder) is created
from the card it belongs to, not from an editor page. A stored draft
opens in Compose, its **Delete draft** among the form's buttons.

### 4.4 Reader

The mail page of an account: folders on the left, the list beside
them. A message opens on a page of its own, the breadcrumb the way back
to its folder. Not a three-pane client. It has
the filter bar and the pager of every other list. The batch bar above the list asks for a folder only
while "move to" is chosen, and the head of the list ticks every row.

The header of a message holds what can be done with it, each as far as
the caller may: **Reply** with its word, then as icons Reply to all,
Forward, Download original, Mark read or unread, Star, Move (the dialog
asks the folder), Move to the trash and Delete for good (the dialog
asks first).

Where the account keeps threads and the caller may read them, the list
of a folder switches between its messages and its conversations, each
conversation where its newest message in the folder is. The
conversations have no search and no batch. A conversation opens its own
page: its facts, then its messages in every folder, oldest first, each
with its folder. Below the text of a message a card names the others of
its conversation and opens the conversation's page.

Beside the sender a message shows the receiving server's check of its
domain (CONCEPT 6.3) as a tag: `checked: example.com`, `check failed`
or `not checked`, the reason as its title. A list shows only
`check failed`. The account page names `sender check` among what the
account can do, and the **Change** card of an IMAP, POP3 or JMAP
account takes the server's name.

A message shows its keywords in a card of their own, as chips, and the
list shows them as tags. Whoever may change the message removes one
with the x on its chip and adds one with the field beside them.
Keywords starting with `$`, such as `$answered`, belong to the mail
protocol: they show beside the flags, in words where they have one
(answered, forwarded, draft, junk, phishing), and are not changed in
the UI. Those a server notes for itself, such as `$hasnoattachment` or
`$notjunk`, do not show.

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
by name, name them **First** and **Next**. The page size is one
constant, `PAGE_SIZE` of `web/pages/templates.py`. The conversations of
a folder and the Activity tab have one of their own in their route
module. A paged card shows no count in its header, since there is no
total. Roles, tokens and webhooks list everything.

### 4.7 Messages and errors

A form that goes through answers with a redirect and one message, shown
once at the top of the next page (Post/Redirect/Get, CONCEPT 1.1).
Success in green, a refusal in the page's own words in red, never a
status code. An editor that is refused is shown again at once, with
what was typed and the reason at the top, and answers `400`, or the
status of the domain's refusal where a provider or a right refused (the
connect page and the mail form). A password
is never shown again. An action without fields, such as a delete, goes
back to its page with the reason. A page that cannot be shown at all is
the error page with a way back.

Where the browser goes afterwards, the `back` a form carries or the
`next` of the sign-in, is a path of this UI, never another site. A value
with a scheme, a host or a dot segment, also written as `%2e%2e`, lands
on the route's own fallback instead, the list the form belongs to or the
start of the UI. So does a path outside `/ui`, and a value whose host
cannot be read, such as `//[`.

## 5. The overview

The first page after signing in. Its cards, in order:

1. **You**: name, roles, what the rights add up to, the last sign-in
   (stored with the password). The account menu has the links. The
   card says at a glance whether this user may read mail and send it
   anywhere, the warning the API and the MCP server also give.
2. **Your accounts**: one row per account with its address, status
   and what you may do there. Its Mail button opens the account's mail,
   the address opens the account.
3. **Service**: only for those with `accounts.read`: accounts that need
   attention (needs_reauth, unreachable, sync failing), webhooks failing.
   Each line links to the page that fixes it. When all is well, it says
   so in one line. Under it the sync worker: running and its interval,
   or switched off and why, push with how many accounts it watches of
   how many it may, its last pass.
