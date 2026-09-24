"""Wire protocols, one library each: ``imap`` (IMAPClient), ``smtp``
(smtplib), later ``pop3`` (poplib).

Each module speaks its protocol and nothing else: no ids, no folders of the
API, no decisions. Library errors leave it as ``MailboxApiError``. The
adapters in ``providers/`` build on them.
"""
