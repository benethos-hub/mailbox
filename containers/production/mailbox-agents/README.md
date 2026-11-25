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
   `agents/<name>/.env` and fill it in. `categorization` also needs
   `agents/categorization/categorization.json`, its groups, made after
   `categorization.example.json`, and `inquiries` needs
   `agents/inquiries/inquiries.json`, its sender domains and phrases, made
   after `inquiries.example.json`. `counting` asks no model and has no
   `gateway_key`. `categorization` asks one only when a group of its list has a
   topic: then it needs the gateway settings in its `.env`, as
   `agents/categorization/.env.example` shows, and a `gateway_key`.
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
   docker compose --profile invoices up -d
   ```

Every agent starts in the stage its `.env` names, `shadow` in the
template. Review what it would have done with `report` before you change
its stage.

## Update

Change `MAILBOX_VERSION` in `.env`, then:

```sh
docker compose --profile invoices pull
docker compose --profile invoices up -d
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
