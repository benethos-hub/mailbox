# The configuration UI

How the configuration UI looks and behaves, and the rules every page
follows. The rework it began with was decided on 2026-09-27 and is
built ([roadmap](../ROADMAP.md), phase 4b).

The UI is the part of the service a person uses in the browser
([CONCEPT 1.1](concept/purpose-and-model.md#11-inside-the-service)). It runs in the same
process as the API, calls the same domain services and is not part of the
OpenAPI document. This file says how it looks and behaves. CONCEPT says
what it must do and how it is secured.

This file is the overview. It holds the goals, the rules for
building and extending with the checklist for a new page, and what was
decided. The rest is in [ui/](ui/), under the
same section numbers.

## The topics

| Topic | Sections | In short |
|---|---|---|
| [The pages](ui/pages.md) | 3 to 5 | The navigation and the click budget, the four page types with their filter bar, paging, messages and errors, and the overview. |
| [The workflows](ui/workflows.md) | 6 | Connecting an account, creating, changing and removing, users, roles and tokens, webhooks, the state of the service and the recovery key, writing mail. |
| [The look](ui/look.md) | 7 | The palette, the density, the sidebar, the components and icons, and what the pages never load from elsewhere. |

## Every section

- [1. Goals](#1-goals)
- [3. Navigation and the click budget](ui/pages.md#3-navigation-and-the-click-budget)
- [4. Page types](ui/pages.md#4-page-types): [4.1 List](ui/pages.md#41-list) · [4.2 Detail](ui/pages.md#42-detail) · [4.3 Editor](ui/pages.md#43-editor) · [4.4 Reader](ui/pages.md#44-reader) · [4.5 The filter bar](ui/pages.md#45-the-filter-bar) · [4.6 Paging](ui/pages.md#46-paging) · [4.7 Messages and errors](ui/pages.md#47-messages-and-errors)
- [5. The overview](ui/pages.md#5-the-overview)
- [6. Workflows](ui/workflows.md#6-workflows): [6.1 Connecting an account](ui/workflows.md#61-connecting-an-account) · [6.2 Creating, changing, removing](ui/workflows.md#62-creating-changing-removing) · [6.3 Users, roles, tokens](ui/workflows.md#63-users-roles-tokens) · [6.4 Webhooks](ui/workflows.md#64-webhooks) · [6.5 The state of the service and the recovery key](ui/workflows.md#65-the-state-of-the-service-and-the-recovery-key) · [6.6 Writing mail](ui/workflows.md#66-writing-mail) · [6.7 Changes, optional](ui/workflows.md#67-changes-optional)
- [7. Look](ui/look.md#7-look)
- [8. Rules for building and extending](#8-rules-for-building-and-extending)
- [10. Decided](#10-decided)

## 1. Goals

1. **Simple to use.** Every task a person comes for is reached in three
   to five clicks from the overview, counting a page open, a button and a
   form submit as one click each, and the question of a dialog as one
   more. Section 3 has the budget.
2. **A light look.** One palette in section 7, with a dark mode.
3. **Workflows from what the person knows.** Connecting an account
   starts with the address and leads from there to a sign-in at the
   provider or to a password. Setting servers by hand is possible
   before and after connecting. Section 6.
4. **Paging on every long list**, the same control everywhere.
5. **Filters that look and work alike** on every list that has them.
6. **Creating, changing and removing** look and sit alike on every
   page, whatever the record.
7. **The overview starts with the signed-in user**: who they are, what
   they may do, their accounts.
8. **Rules for growth.** A new page follows a page type, a checklist and a
   test. Section 8.

## 8. Rules for building and extending

These rules bind every page.

1. **One page, one type** of section 4. A page that fits none needs a
   new type in this file first.
2. **Routes** live in one module per area under `web/pages/routes/`,
   templates under `templates/pages/`, one template per page, named as
   the page. Partials are pieces of a page that pages include as they
   are, components are macros.
3. **The route decides nothing.** It reads the form, calls one domain
   method and renders or redirects. The mail form is the one route that
   saves and sends in two steps, and follows the id a replaced draft
   gets. Rights are the domain's. The page
   only hides what `caller.allows(...)` denies, with the same names the
   API uses in `x-permission`. The mail pages offer what the account's
   `operations` name, the caller's rights and what the account can do
   together (`web/pages/rights.py`, UNIFORM U1). Which parts of a change
   they offer and what a message shows follow its `capabilities`. A
   template asks `can` alone, never a capability or a kind of account
   (U2, held by `test_code_rules.py`). The forms that connect an account
   are drawn from the description of its kind (U6,
   `components/connection.html`).
   Marks show in the words of `mailbox-common` (`mail/marks.py`), and no
   template spells a `$` keyword (U3). After a change a page takes the
   id the answer brings, never the one it had (U4). A page is tested by
   the capabilities an account has, not by its kind (U5,
   `test_ui_by_capability.py`).
4. **A page has the context it needs, nothing more.** `page` names the
   sidebar entry, `me` the user, `csrf` the token. A template does not
   compute what a route can pass.
5. **Every form that goes through is Post/Redirect/Get** with one
   message. A refused editor is shown again as 4.7 says. Every
   destructive form asks first. Every list with a filter is a `GET`.
6. **Words**: the button names of 6.2, tags in lower case but for an
   acronym (`API only`), headings in
   sentence case, the record's name in the heading of its detail page.
7. **Tests**: a page has at least one test in `tests/web/pages/test_ui_*.py` that
   opens it as a user with the right, one that shows it hidden without
   the right, and one per form. `live/ui.py` walks every workflow of
   section 6 against the test accounts. The browser suite,
   `tests/browser/`, opens every page reached by links from the
   overview in Chrome, Firefox and WebKit and fails on a violation of
   the content security policy or a missing file. A page linked from
   nowhere needs a link or a test of its own there.
8. **Checklist for a new page**: route module or a route in one. The
   template of its type. The sidebar entry with its right and its icon.
   Icons only from the sprite, a new one added in `assets/mailbox-service/icons.py`.
   Nothing loaded from elsewhere, no CDN. The tests of rule 7. A line
   in the table of section 3 and, if it changes a workflow, in
   section 6. The roadmap item. A CHANGELOG entry only when a person
   using the API notices.

## 10. Decided

- 2026-09-27: the rework as this file describes it.
- 2026-09-27: the recovery key only for `admin`, after the
  password once more (6.5).
- 2026-09-27: the sync state in the worker's memory, the last sign-in
  stored (5, 6.5).
- 2026-09-27: a delivery log for webhooks (6.4).
- 2026-09-27: the Changes page not in phase 4b (6.7).
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
  entries without a detail page. A batch for devices, tokens and
  users, none for accounts, roles and webhooks (4.1, 4.2, 6.2).
- 2026-10-09: the user page in tabs Rights, Access, Activity, the grant
  editor in lines, a batch of the Users list (6.3).
- 2026-10-09: a batch of users, tokens or devices is all or nothing
  (4.1).
- 2026-10-09: Mail and Sends on each row of the Accounts list, Verify on
  the account page alone. The message's actions in its header, its
  keywords as chips (4.1, 4.4).
- 2026-10-09: webhooks changeable, a Change card and a new signing
  secret on their page, with the API's `update_webhook` and
  `renew_webhook_secret` (6.4).
- 2026-10-09: the page's own dialog in place of the browser's
  question, copy buttons beside every secret shown once, relative
  times in lists (7).
- 2026-10-09: the Service card of the overview to everyone with
  `accounts.read` (5).
