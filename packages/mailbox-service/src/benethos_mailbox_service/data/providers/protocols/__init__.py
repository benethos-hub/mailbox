"""Wire protocols, one library each: ``imap`` (IMAPClient), ``smtp``
(smtplib), ``oauth`` (OAuth 2.0 over ``data.http``), later ``pop3``
(poplib).

Each module speaks its protocol and nothing else: no ids, no folders of the
API, no decisions. Library errors leave it as ``MailboxServiceError``. The
adapters in ``providers/`` build on them.
"""
