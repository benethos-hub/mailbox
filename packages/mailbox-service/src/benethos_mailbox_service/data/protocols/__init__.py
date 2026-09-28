"""The wire, one library each: ``imap`` (IMAPClient), ``smtp`` (smtplib),
``http`` (httpx), ``oauth`` (OAuth 2.0 over ``http``), later ``pop3``
(poplib). ``transport`` holds TLS, the timeouts and the failures below
every library.

Each module speaks its protocol and nothing else: no ids, no folders of the
API, no decisions. Library errors leave it as ``MailboxServiceError``. It
imports nothing of ``providers``: the adapters there build on it, and
``discovery`` reads HTTP through it.
"""
