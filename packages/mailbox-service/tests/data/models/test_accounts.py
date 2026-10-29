"""The records of an account."""

from __future__ import annotations

from benethos_mailbox_common.mail import marks
from benethos_mailbox_service.data.models import Mark


def test_the_marks_are_those_the_ui_and_the_mcp_server_show() -> None:
    """``Mark`` is the API's contract, ``marks.MARKS`` what the UI and the
    MCP server show: the same six keywords in both packages."""
    assert {m.value for m in Mark} == {m.keyword for m in marks.MARKS}
