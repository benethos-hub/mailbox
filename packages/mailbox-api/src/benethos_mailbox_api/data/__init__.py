"""Data layer: our own records and the foreign mail sources.

Reads and writes, decides nothing. ``models`` holds the provider-neutral
types, ``providers`` the adapters to mail services behind one protocol, and
``storage`` the records this service keeps itself. Imports nothing from
``domain`` or ``web``.
"""
