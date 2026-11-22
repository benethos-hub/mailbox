# Concept: the model gateway

Part of the [concept](../CONCEPT.md).

The agents speak the OpenAI chat completions API to a gateway, with
httpx, and the embeddings API once recognising a repeated inquiry needs
it ([roadmap](../../roadmap/agents.md#next)). No model SDK and no agent framework is a dependency:
a call with a schema, a validation and a retry are little code, and every
request stays visible, storable and mockable.

- **One key per agent.** The key names the models the agent may use and a
  budget. An agent whose key lists only local models cannot send mail
  content to a hosted one through a configuration mistake.
- **A model is named by an alias.** The setting `MAILBOX_AGENTS_MODEL` holds
  an alias the gateway resolves. Changing the model behind it is a change at
  the gateway followed by an evaluation run. The model the gateway reports
  in its answer is stored with every step.
- **The answer is forced into a schema** with `response_format` and a JSON
  schema, and validated again with pydantic. The gateway hands the schema
  to a local backend, which builds a grammar from it: measured 2026-11-17
  with LiteLLM v1.108.10 in front of llama.cpp build 12464, a schema
  allowing one value only got that value against a prompt asking for prose.
- **No fallback** from one model to another inside the agent. A fallback at
  the gateway from a local to a hosted model must not be configured for a
  key that reads customer mail.
- **The schema is sent in its strict form:** every object closed, every
  property required, a value that may be empty typed with `null`. A quote
  or a free value longer than 300 characters does not fit, checked after
  parsing so the schema sent stays plain, and no answer copies the mail
  into the state file. No tools
  are sent, and no sampling setting: some hosted models refuse one, so the
  gateway sets it per model, such as a temperature of 0 for a local one.
- **A gateway that is away** (no connection, a timeout, a 5xx, a 408 or a
  429) leaves the message `pending`, and the loop waits twice as long
  before it tries again, up to `BACKOFF_CEILING_SECONDS`. Nothing counts
  against the message.
- **An answer outside the schema, or a request the gateway refuses** with
  another 4xx, counts as an attempt of that message. Its next attempt waits
  twice as long, and after `MAX_ATTEMPTS` it is `failed`.
- **A key or an alias the gateway refuses** (401, 403, 404) is a
  configuration error. The pass stops and nothing is decided.
- **A redirect** (3xx), such as for http where the gateway answers
  https, is a configuration error as well: redirects are not followed,
  and `MAILBOX_AGENTS_GATEWAY_URL` is the one to correct (2026-11-20).
