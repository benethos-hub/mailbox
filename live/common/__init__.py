"""What the live checks of every package share, one module per subject.

Not a test and not part of a package of the project. ``live/`` is
installed into the development environment as an editable project of
its own (``live/pyproject.toml``), so a script in a package's folder
imports from here, and from the folder of shared code beside it, with
``uv run python live/<package>/<name>.py`` from the repository root:

- ``run``: the outcome of a run, and waiting for something to happen.
- ``accounts``: the test accounts of ``live/.env``, and adding them to a
  service.
- ``processes``: the service as a process of the script's own.
- ``admin``: its first user, the way an operator makes it, and users
  with narrower rights.
- ``service``: a service that is gone at the end, in a process or in
  this one.
- ``mail``: finding a test mail through the API, its change feed and its
  thread, and deleting test mail for good.
- ``test_database``: the test database of containers/test-database/,
  its administrator, the command of Docker, and its container stopped.

What a check does with mail on the way, it does through the Python
client, ``benethos_mailbox_client``. What a check asks of the API itself,
a status code or an error code, it asks with httpx, since the client
turns those into exceptions on purpose.
"""
