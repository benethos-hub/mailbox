"""What the live checks of the service share, one module per subject.
What every package's checks share is in ``live/common/``.

- ``test_server``: the test mail server of our own, its accounts, and
  the steps ``imap.py``, ``jmap.py`` and ``pop3.py`` share.
- ``capabilities``: what an account names it can do, per kind of
  server, and the check that it does.
- ``own_service``: a service with a database of its own that keeps a
  sign-in between runs, for ``gmail.py`` and ``microsoft.py``.
- ``microsoft_mail``: the mail of ``microsoft.py``, sent, read, answered
  and labelled.
- ``imap``: a plain IMAP connection, standing in for another mail client.
- ``receiver``: a webhook receiver on 127.0.0.1.
- ``changes_trip`` and ``changes_stages``: one run of ``changes.py``, and
  its stages that change the test mail.
- ``ui_users``, ``ui_mail`` and ``ui_factor``: the users, the mail and
  the second factor of ``ui.py``.
"""
