# Concept: peers over A2A

Part of the [concept](../CONCEPT.md).

> **Status: built (2026-11-25), off unless a port is set. Checked
> offline and behind LiteLLM 1.110.3 on the test account of the live
> setup, never on a real mailbox.**

Another agent, a peer, may want to know how an agent classifies a
message, such as whether it is an invoice and from which partner. The
agents answer such a question over A2A, the protocol for agents to talk
to agents, so a gateway such as LiteLLM can list them beside its models
and pass a question on. The entrance runs in the process of the worker,
beside its metrics.

## What a peer may ask

One skill, `classify`. A peer sends a message with one data part that
names the account and the message:

```json
{"account_id": "acc1", "message_id": "m1"}
```

It gets a message back with one data part, the decision of the agent on
that message:

```json
{
  "agent": "categorization/bookkeeping",
  "version": "v1-list-0123456789ab-invoice-v5",
  "label": "Telco",
  "source": "model",
  "fields": {"kind": "Invoice"},
  "found": {"label": true, "kind": true},
  "refused": null
}
```

`found` says per field, the label under `label`, whether its quote was
found in the mail or code chose the value. A label without its quote is
told with `refused` set, as the worker would not act on it. A message
that could not be classified is told why, with `reason` one of
`message_gone`, `message_refused`, `limit_reached`, `answer_refused` or
`unavailable`. Anything but the two ids in one data part is refused
before anything is read.

The entrance speaks A2A 1.0 and, on the same endpoint, 0.3. A request of
1.0 names its version in the header `A2A-Version: 1.0`. Without it the
request counts as one of 0.3. The agent card lies at
`/.well-known/agent-card.json`. It names the agent and its instance, the
skill and the token it wants. It names no category of a list.

## What it never does

- **It never acts.** It reads the message through the read-only mailbox,
  as `eval` does, and never asks the agent's effect. Nothing is moved,
  marked or made. The decision is not stored, and an open item the
  agent would open is refused.
- **It tells nothing of the mail.** No subject, sender, text or quote,
  only the categories and whether a quote backs each. The categories
  are the owner's words: a peer that asks is told them, and a gateway in
  between may log them, LiteLLM among them.
- **It costs no more than the limits allow.** A decision the worker
  stored for the message, under the same prompt version and model, is
  taken as it is, without a call. Otherwise the agent decides, and its
  calls count against its limits per message and per day in its state
  file, as the worker's do. One message at a time.
- **It takes no peer unasked.** With a port set, the worker does not
  start without a token. Every request carries it as
  `Authorization: Bearer <token>`, the agent card too, compared in
  constant time. A wrong or missing token is answered `401` and reads
  nothing.

Each question is a line of the log, `messages.peer_asked`, with the id
of the message and the outcome, never a category ([LOGGING.md](../LOGGING.md)).

## Settings

| Setting | |
|---|---|
| `A2A_PORT` | the port of the entrance, `0` when unset: none is served |
| `A2A_HOST` | the address it listens on, `127.0.0.1` when unset. A container serves its network with `0.0.0.0` |
| `A2A_URL` | where a peer reaches it, as the agent card names it. Unset: `http://<host>:<port>/` |
| `A2A_TOKEN`, `A2A_TOKEN_FILE` | the token, or a file that holds it. Required with a port. Never logged |

The entrance speaks plain http. Keep it on a network of its own, such as
the network of the containers that the gateway shares, or bind it to
`127.0.0.1`. A port that cannot be opened stops the worker with a
message that names `A2A_PORT`.

## Behind LiteLLM

LiteLLM lists A2A agents beside its models and passes a question on at
`/a2a/<agent_id>`, with a key of its own. An agent is entered with
`POST /v1/agents`: its card with the URL of the entrance,
`a2a_protocol_version` `1.0`, and the token of the entrance as the
header `Authorization` in `static_headers`
([the live setup](../../../containers/live/mailbox-agents/README.md#peers-over-a2a)).

Measured 2026-11-25 with LiteLLM 1.110.3 on the test account of the live
setup (`live/mailbox-agents/peers.py`):

- A question through LiteLLM, in A2A 1.0 and in 0.3, was told what the
  entrance tells directly. LiteLLM answered both in 1.0, and its copy
  of the card names LiteLLM as the address.
- An agent entered without the token was answered with an error, and
  the classifier was not asked.
- A key of LiteLLM that reaches some model aliases only reached the
  entered agent as well. The token of the entrance keeps out who should
  not ask, whatever the keys of the gateway allow.

LiteLLM logs what passes through it, the categories it is told among
them.

## The pieces

- `runtime/classify.py`: the decision on one message for a peer, its
  limits, the line of the log.
- `peers/a2a.py`: the only module that imports a2a-sdk, Starlette and
  uvicorn. The agent card, the token, the protocol.
- `cli/commands.py`: the worker starts it beside the loop and stops it
  with the loop.
