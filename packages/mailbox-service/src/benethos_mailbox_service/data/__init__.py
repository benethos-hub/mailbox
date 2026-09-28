"""Data layer: our own records and the foreign mail sources.

Reads and writes, decides nothing. Imports nothing from ``domain`` or
``web``. Each package is imported through its ``__init__.py``, and
imports only the lines below its own:

- ``backup``: encrypted backups of the database, and their restore.
- ``secrets``: the cipher, the key providers, the password hashes and the
  vault of the credentials.
- ``storage``: the records this service keeps itself, in memory or SQLite.
- ``providers``: the adapters to mail services behind one protocol, and
  their registry.
- ``discovery``: the sources of autodiscovery.
- ``protocols``: the wire, one library each: IMAP, SMTP, HTTP, OAuth.
- ``mail``: messages in RFC 5322, whichever protocol carries them.
- ``files``: files for the owner alone.
- ``models``: the provider-neutral types.
- ``logbook``: the newest log lines in memory, for the log page.
"""
