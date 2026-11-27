# <img src="../../../assets/mailbox-agents/brand/icon.svg" alt="" height="36" align="absmiddle"> Mailbox Agents in operation

The published image, one container per agent, each started by its profile.
This folder is all it needs, no clone of the repository.

**Contents**

- [Set it up](#set-it-up)
- [The cockpit](#the-cockpit)
- [Update](#update)
- [What is where](#what-is-where)

## Set it up

1. Copy `.env.example` to `.env` and name the version, best with the
   digest of the release behind it, as `.env.example` says.
2. For each agent you run, copy `agents/<name>/.env.example` to
   `agents/<name>/.env` and fill it in. `categorization` also needs
   `agents/categorization/categorization.json`, its groups, made after
   `categorization.example.json`, and `inquiries` needs
   `agents/inquiries/inquiries.json`, its sender domains and phrases, made
   after `inquiries.example.json`, and `filing` needs
   `agents/filing/filing.json`, its rules, made after
   `filing.example.json`, and `forwarding` needs
   `agents/forwarding/forwarding.json`, made after
   `forwarding.example.json`. `counting`, `filing` and `forwarding` ask
   no model and have no `gateway_key`. `categorization` asks one only when a group of its list has a
   topic: then it needs the gateway settings in its `.env`, as
   `agents/categorization/.env.example` shows, and a `gateway_key`.
3. Put the agent's secrets into `secrets/<name>/`, one file each,
   readable by the container's user (uid 10001) and nobody else:

   ```sh
   mkdir -p secrets/categorization
   printf '%s' "<token of the agent's user>" > secrets/categorization/service_token
   printf '%s' "<the agent's gateway key>" > secrets/categorization/gateway_key
   chmod 400 secrets/categorization/* && sudo chown -R 10001 secrets/categorization
   ```

   Each agent has a user of its own in the mailbox service, with
   `mail.read` and `mail.write` on the accounts it works on and nothing
   else, `counting` with `mail.read` alone, `forwarding` with `mail.read`
   and `drafts`, never `mail.write` and never send, and each that asks a model a
   key of its own at the gateway. See
   [mailbox-service.md](../../../docs/mailbox-agents/concept/mailbox-service.md)
   and [model-gateway.md](../../../docs/mailbox-agents/concept/model-gateway.md).
   The mailbox service has to fit the agents' version: before 1.0 their
   minor version, from 1.0 their major version and a minor version no
   older than theirs. `status` names whether it matches. An
   agent refuses any other and ends with exit code 2.
4. Start the agents, first `counting`, which changes nothing, to see the
   deployment work:

   ```sh
   docker compose --profile counting up -d
   docker compose exec counting benethos-mailbox-agents report --agent counting --limit 5
   docker compose --profile categorization up -d
   ```

Every agent starts in the stage its `.env` names, `shadow` in the
template. Review what it would have done with `report` before you change
its stage.

## The cockpit

A read-only page of what every agent did, read from the state files,
started by hand and never again by itself
([cockpit.md](../../../docs/mailbox-agents/concept/cockpit.md)). It
reads the volume of each agent read-only and changes nothing.

1. Copy `cockpit/.env.example` to `cockpit/.env`.
2. Put its secret into `secrets/cockpit/`. Whoever holds it signs in and
   sees everything the state files hold, quotes of mail among it:

   ```sh
   mkdir -p secrets/cockpit
   openssl rand -base64 32 | tr -d '\n' > secrets/cockpit/cockpit_secret
   chmod 400 secrets/cockpit/* && sudo chown -R 10001 secrets/cockpit
   ```

3. For subject and sender beside the ids, give it a user of its own in
   the mailbox service with `mail.read` alone, its token as
   `secrets/cockpit/service_token`, and the two lines of
   `cockpit/.env.example` for it. Without them it shows the ids.
4. Start it, open `http://127.0.0.1:9480`, and stop it when you are done:

   ```sh
   docker compose --profile cockpit up -d cockpit
   docker compose --profile cockpit stop cockpit
   ```

It may start before an agent has run: the agent still writes to its
volume (measured on 2026-11-27), and the cockpit shows no state file for
it until then. It shows an agent as `healthy`, `silent` or `stopped`. One
killed without a clean stop reads as running until the window of its
health has passed, then as `silent`.

## Update

Change `MAILBOX_VERSION` in `.env`, then:

```sh
docker compose --profile categorization pull
docker compose --profile categorization up -d
```

Update the mailbox service to the same version at the same time: before
1.0 an agent stops at a service of another minor version.

A new version may bring a new migration of the state file. It runs on the
first start and is never taken back, so keep a copy of the volume before
an update you may want to undo.

## What is where

| What | Where |
|---|---|
| the state file of an agent | the volume `<agent>-data`, `awaiting-reply-data` for `awaiting_reply`, `/data/<agent>.db` |
| its settings | `agents/<agent>/.env` |
| its token and key | `secrets/<agent>/`, mounted read-only at `/run/secrets` |
| its metrics | `127.0.0.1:947x/metrics`, the port in `.env` |
| its log | `docker compose logs <agent>`, five files of 10 MB at most |
| the cockpit | `127.0.0.1:9480`, its settings in `cockpit/.env`, its secret in `secrets/cockpit/` |
