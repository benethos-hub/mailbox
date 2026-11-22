# <img src="../../../assets/mailbox-agents/brand/icon.svg" alt="" height="36" align="absmiddle"> Mailbox Agents in operation

The published image, one container per agent, each started by its profile.
This folder is all it needs, no clone of the repository.

**Contents**

- [Set it up](#set-it-up)
- [Update](#update)
- [What is where](#what-is-where)

## Set it up

1. Copy `.env.example` to `.env` and name the version, best with the
   digest of the release behind it, as `.env.example` says.
2. For each agent you run, copy `agents/<name>/.env.example` to
   `agents/<name>/.env` and fill it in. `sorting` also needs
   `agents/sorting/sorting.json`, its groups, made after
   `sorting.example.json`, and `inquiries` needs
   `agents/inquiries/inquiries.json`, its sender domains and phrases, made
   after `inquiries.example.json`. `sorting` and `counting` ask no model
   and have no `gateway_key`.
3. Put the agent's secrets into `secrets/<name>/`, one file each,
   readable by the container's user (uid 10001) and nobody else:

   ```sh
   mkdir -p secrets/invoices
   printf '%s' "<token of the agent's user>" > secrets/invoices/service_token
   printf '%s' "<the agent's gateway key>" > secrets/invoices/gateway_key
   chmod 400 secrets/invoices/* && sudo chown -R 10001 secrets/invoices
   ```

   Each agent has a user of its own in the mailbox service, with
   `mail.read` and `mail.write` on the accounts it works on and nothing
   else, `counting` with `mail.read` alone, and each that asks a model a
   key of its own at the gateway. See
   docs/mailbox-agents/concept/mailbox-service.md and docs/mailbox-agents/concept/model-gateway.md.
   The mailbox service has to run the agents' minor version: the agents
   0.10.x take the service 0.10.x. `status` names whether it matches. An
   agent refuses any other and ends with exit code 2.
4. Start the agents, first `counting`, which changes nothing, to see the
   deployment work:

   ```sh
   docker compose --profile counting up -d
   docker compose exec counting benethos-mailbox-agents report --agent counting --limit 5
   docker compose --profile invoices up -d
   ```

Every agent starts in the stage its `.env` names, `shadow` in the
template. Review what it would have done with `report` before you change
its stage.

## Update

Change `MAILBOX_AGENTS_VERSION` in `.env`, then:

```sh
docker compose --profile invoices pull
docker compose --profile invoices up -d
```

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
