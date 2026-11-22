"""What the live checks of the MCP server share, one module per subject.
What every package's checks share is in ``live/common/``.

- ``mcp_session`` and ``mcp_sending``: the MCP server over stdio as a
  session, and the sending checks of ``mcp_stdio.py``.
- ``mcp_writing``, ``mcp_links`` and ``mcp_rights``: writing, a link to
  an attachment and the rights of its token, through the MCP server of
  ``mcp_stdio.py``.
- ``mcp_status``: the MCP server's ``server_status``, for
  ``mcp_stdio.py`` and ``mcp_http.py``.
"""
