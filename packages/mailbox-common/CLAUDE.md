# Working guidelines for the common package

The rules that hold for `mailbox-common` alone. The rules for the whole
repository, the golden rules among them, are in the
[CLAUDE.md of the root](../../CLAUDE.md): read it first.

## Its interface

`docs/mailbox-common/common-interface.json` holds the public interface
of the common package (golden rule 4). After any change to a name, a
signature, a field or a default there, regenerate it with
`uv run python tests/interface.py benethos_mailbox_common >
docs/mailbox-common/common-interface.json` and review the diff like
code: a removed or changed name breaks whoever imports it.
