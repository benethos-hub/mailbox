# Concept: evaluation

Part of the [concept](../CONCEPT.md).

A **gold set** is mail a person labelled by hand: for a classifying agent
the right label, for an extracting agent the right value of each field. The
agent runs over it and the scoring counts where it agrees.

- **Format:** one JSON object per line: `account_id`, `message_id`, the
  expected `label`, the expected `fields` with `null` for a field the
  message does not fill, and an optional `note`. A line starting with `#`
  is a comment. A message named twice is refused. The mail itself is
  fetched by id at run time.
- **Where it lives:** outside version control, such as under `data/` or
  the `secrets/` of the live setup, because it points at real mail. The repository holds the format, the scoring and a small set of
  invented messages the tests use.
- **What is reported:** for a label, precision and recall. For each field,
  how often the value is right, wrong, missing or invented, and how often
  it is rightly empty. Values are compared with case and whitespace made
  uniform. A decision the evidence check refused counts as no answer.
  Tokens and time per message. A field is not counted apart by who chose
  it, a rule or the model: no agent records that.
- **Always against the baseline.** Every report shows the rules alone
  beside the model, so what the model adds is a number.
- **The judgement, not the filter.** The evaluation runs the baseline and
  the model on every message of the gold set and does not ask the agent's
  `admit` first, which in operation skips a message, such as one outside
  the inbox. So the numbers measure what rules and model decide. A gold
  set holds only mail that `admit` lets through (decided 2026-11-18).
- **A run is manual.** `benethos-mailbox-agents eval --agent <name> --gold <file>` needs a
  mailbox service and a model, which a public CI has not. It is a live
  check, outside `testpaths`, and never a gate. It asks the service for
  its version first and refuses one of another version with exit
  code 2, as a pass does, since it reads mail and writes a report that is
  kept (decided 2026-11-20).
- **A report is versioned.** Each run writes one file,
  `<agent>/<date>-v<agent version>-<prompt version>-<model alias>.json`
  below the folder `--reports` names. Without it, the report goes to
  `reports/mailbox-agents/` in the layout of the repository, where it is
  kept, and else to `reports/` in the data folder. The file names the agent version, prompt version, model alias, the models the
  gateway reported and the date, with numbers only: no id, no label of a
  single message and no content of any mail. A change to a prompt or a
  model is merged with its report.
- **A report names only the agent's own labels and fields** (decided
  2026-11-19). An agent declares its fixed labels and field names
  (`report_labels`, `report_fields`). Any other name in the gold set or a
  decision, such as the name of a group of `sorting`, which is the owner's
  own text and often a person's name, becomes `label-<n>` or `field-<n>`,
  numbered in the sorted order of the names within the report. The
  numbers stay.
- **A run never touches the agent's state file.** It counts its model
  calls on a state file of its own and applies the evidence check as in
  operation. A gateway that is away ends the run.

Size to start with: about 200 labelled messages for `invoices`, about 150
sent messages for `awaiting_reply`, 80 to 150 inquiries for `inquiries`.
