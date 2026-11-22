# Concept: the agent `inquiries`

Part of the [concept](../CONCEPT.md).

**Question:** is this a project inquiry, and what does it say?

| | |
|---|---|
| Triggers | `message.created` in the inbox |
| Baseline | phrases of an inquiry, patterns for dates and rates, and the sender domains and phrases of `INQUIRIES_PATTERNS_FILE` (JSON, optional) taken from the gold set |
| Model | label `inquiry` or `other`, then the fields below |
| Actions | `add_keyword` |

An inquiry gets the keyword `agent-inquiry`. The rules call a message an
inquiry when its sender's domain is known, when it carries two phrases of
an inquiry, or one together with a date or a rate.

Fields, each optional: role, start, end, duration, workload, location,
remote share, contract form, intermediary, end client, rate, required
skills, desired skills, deadline to apply.

Every field comes with a quote from the message ([safety](safety.md)). What a
message does not say stays empty. The fields come in the same call as the
label, with the prompt `prompts/system.v3.md`, version `v3`, each either
null or a value with its quote, in the schema as
`role`, `start`, `end`, `duration`, `workload`, `location`,
`remote_share`, `contract_form`, `intermediary`, `end_client`, `rate`,
`required_skills`, `desired_skills` and `deadline`. A field is null as a
whole, not its value and quote each: the Claude API compiles a schema with
at most 16 parameters whose type is a union, and refused the 28 of `v2`.
A test holds every agent's schema to that limit.
A quote or a value holds at most 300 characters, and a whole answer at
most 2000 in all its quotes and values (2026-11-20): 29 strings of 300
would hold more than the model was given. A longer answer is refused as
not fitting the schema, which is sent to the model unchanged.
A message labelled `other` keeps none. The evaluation counts each field
right, wrong, missing, invented or rightly empty.

The model is given the sender, the subject and the first 8000 characters
of the text. The sender's name and the subject, which a stranger chooses,
are cut at 300 characters each (2026-11-19), the sender's address at 320
(2026-11-20), as much as the mail standards allow. The evidence check
looks a quote up in the same cut text.

Recognising an inquiry seen before, and anything that writes a reply, come
later ([roadmap](../../ROADMAP.md)).
