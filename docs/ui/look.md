# UI: the look

Part of [UI.md](../UI.md): section 7.

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
  | `--border-strong` | `#c9d3e1` | `#3a4659` |
  | `--text` | `#14213d` | `#e6ebf5` |
  | `--text-muted` | `#56657e` | `#9aa8bf` |
  | `--text-faint` | `#5f6e86` | `#8391a8` |
  | `--accent` | `#2560c8` | `#6ea0ff` |
  | `--accent-soft` | `#e8f0fc` | `#1d2c4a` |
  | `--on-accent` | `#ffffff` | `#0f1420` |
  | `--ok` | `#13703f` | `#4ac98a` |
  | `--ok-soft` | `#e5f5ec` | `#173326` |
  | `--bad` | `#b5301c` | `#f0776a` |
  | `--err-soft` | `#fdefed` | `#3a1f1f` |
  | `--warn` | `#955204` | `#e0a458` |
  | `--warn-soft` | `#fdf5e8` | `#33291a` |

- **Density**: row height 40 px, card
  padding 20 px, one type size for text and one for the small line under
  a name.
- **Icon and logo**: the project's 3D icon from `assets/brand/` heads
  the sidebar and is the favicon. The 3D logo with its word mark
  stands above the card of the sign-in page and of the page a
  provider sends the browser back to (`bare.html`), in dark mode
  with a light word mark. `assets/build.py` makes the copies in
  `static/img/`.
- **Sidebar**: light, not dark, with the accent on the active entry.
  Collapses to a top bar under 860 px.
- **Components**: the parts pages share are macros in
  `components/ui.html`, the grant editor in `components/grants.html`, the
  connection fields in `components/connection.html`, the rows of the
  audit in `components/audit.html`, the fields of a webhook in
  `components/webhook.html`, the step of the second factor in
  `components/factor.html`. The filter bar, the pager, the related
  list, the Danger card, the secret card and every icon are macros. A
  tag, a field and a plain button may be written in the page with the
  classes of `app.css`. `filter_bar` with its chips, `facts`, `related`
  and `breadcrumb` are among them.
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
  Download original, Mark read, Delete for good) gets its word back
  there and in a narrow window. Pencil, bin, plus and envelope stand
  alone.
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
- **Times in lists**: tokens, devices, sends, webhooks, deliveries
  and the last sync of an account show a time under a day ago as "3 minutes ago", older ones as date
  and time, the full stamp always as the tooltip (macro `ago`). Audit,
  log, the facts of a record and the message keep the full stamp.
- **Keys**: `/` puts the cursor in the page's search field, Escape
  closes the dialog.
- **No inline style or script**: the content security policy stays.
  htmx only where a page asks the service again by itself, the
  sign-in with a code. Every other form is a plain post, and a
  destructive one asks first through `data-confirm`. A redirect
  answered to htmx is `204` with `HX-Redirect`, which htmx follows as
  a whole page. `web/pages/templates.py` alone reads and writes the
  headers of htmx, so another version of htmx touches one module of
  Python (`test_code_rules.py`).
- **Nothing from elsewhere**: no CDN. Every script, style, font and
  image the UI loads is kept under `static/`, as htmx and the icons
  are. A test checks the templates and the stylesheet for it.
  `assets/vendor/package-lock.json` records the version of each, for
  the freshness report, and a test holds it to what the UI ships. A
  new version of htmx moves the file, its note with the digest of the
  file in its npm package, and the lockfile together. The browser
  suite (section 8, rule 7) is the one check that runs its JavaScript:
  it runs outside the default test run, and the CI job `browser` runs
  it.
