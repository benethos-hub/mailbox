"""What the live checks share, one module per subject.

Not a test and not part of a package of the project. Each script under
``live/`` imports from here, so a script runs from the repository root
with ``uv run python live/<name>.py``:

- ``run``: the outcome of a run, and waiting for something to happen.
- ``accounts``: the test accounts of ``live/.env``, and adding them to a
  service.
- ``test_server``: the test mail server of our own, its accounts, and
  the steps ``imap.py``, ``jmap.py`` and ``pop3.py`` share.
- ``capabilities``: what an account names it can do, per kind of
  server, and the check that it does.
- ``processes``: the service as a process of the script's own.
- ``admin``: its first user, the way an operator makes it, and users
  with narrower rights.
- ``service``: a service that is gone at the end, in a process or in
  this one.
- ``own_service``: a service with a database of its own that keeps a
  sign-in between runs, for ``gmail.py`` and ``microsoft.py``.
- ``mail``: finding a test mail through the API, its change feed and its
  thread, and deleting test mail for good.
- ``microsoft_mail``: the mail of ``microsoft.py``, sent, read, answered
  and labelled.
- ``imap``: a plain IMAP connection, standing in for another mail client.
- ``receiver``: a webhook receiver on 127.0.0.1.
- ``changes_trip`` and ``changes_stages``: one run of ``changes.py``, and
  its stages that change the test mail.
- ``ui_users``, ``ui_mail`` and ``ui_factor``: the users, the mail and
  the second factor of ``ui.py``.
- ``mcp_session`` and ``mcp_sending``: the MCP server over stdio as a
  session, and the sending checks of ``mcp_stdio.py``.
- ``mcp_writing``, ``mcp_links`` and ``mcp_rights``: writing, a link to
  an attachment and the rights of its token, through the MCP server of
  ``mcp_stdio.py``.
- ``mcp_status``: the MCP server's ``server_status``, for
  ``mcp_stdio.py`` and ``mcp_http.py``.

What a check does with mail on the way, it does through the Python
client, ``benethos_mailbox_client``. What a check asks of the API itself,
a status code or an error code, it asks with httpx, since the client
turns those into exceptions on purpose.
"""
