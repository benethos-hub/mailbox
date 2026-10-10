"""Entry point of the Claude Desktop bundle, started by uv.

The manifest runs this file with ``uv run`` in the unpacked bundle, which
first installs the MCP server from PyPI as the bundle's uv.lock pins it.
"""

from benethos_mailbox_mcp.cli import main

if __name__ == "__main__":
    main()
