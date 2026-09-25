"""Domain layer: what the service does, without HTTP.

Connects accounts to their adapters, and later checks rights, keeps message
ids stable and runs the background sync. Nothing here raises an HTTP
exception or knows a status code: it raises ``errors`` and the web layer
turns them into responses. Imports ``data``, never ``web``.
"""
