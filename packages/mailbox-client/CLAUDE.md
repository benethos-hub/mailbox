# Working guidelines for the client

The rules that hold for `mailbox-client` alone. The rules for the whole
repository, the golden rules among them, are in the
[CLAUDE.md of the root](../../CLAUDE.md): read it first.

## Its interface

`docs/mailbox-client/client-interface.json` holds the public interface
of the client (golden rule 4). After any change to a name, a signature,
a field or a default there, regenerate it with
`uv run python tests/interface.py benethos_mailbox_client >
docs/mailbox-client/client-interface.json` and review the diff like
code: a removed or changed name breaks whoever imports it.

The client's requests are held to `docs/mailbox-service/openapi.json`,
their paths, parameters and bodies.
