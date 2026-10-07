"""What the live checks share, one module per subject.

Not a test and not part of a package of the project. Each script under
``live/`` imports from here, so a script runs from the repository root
with ``uv run python live/<name>.py``:

- ``run``: the outcome of a run, and waiting for something to happen.
- ``accounts``: the test accounts of ``live/.env``, and adding them to a
  service.
- ``processes``: the service as a process of the script's own.
- ``admin``: its first user, the way an operator makes it, and users
  with narrower rights.
- ``service``: a service that is gone at the end, in a process or in
  this one.
- ``mail``: finding a test mail through the API, and deleting it for good.
- ``imap``: a plain IMAP connection, standing in for another mail client.
- ``receiver``: a webhook receiver on 127.0.0.1.

What a check does with mail on the way, it does through the Python
client, ``benethos_mailbox_client``. What a check asks of the API itself,
a status code or an error code, it asks with httpx, since the client
turns those into exceptions on purpose.
"""
