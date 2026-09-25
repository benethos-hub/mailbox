"""Messages in their own format (RFC 5322), whichever protocol carries them.

``compose`` builds an outgoing message, ``parse`` reads one, ``convert``
turns a parsed message into the neutral model. IMAP, POP3 and any adapter
that sees raw messages share them. The domain uses ``compose`` for replies.
"""
