"""The plain text of an HTML body."""

from __future__ import annotations

from benethos_mailbox_service.common.plaintext import from_html

HTML = """
<html><head><style>p { color: red }</style><title>t</title></head><body>
<h1>Invoice</h1>
<p>Dear <b>Bob</b>,<br>please pay &amp; smile.</p>
<ul><li>one</li><li>two</li></ul>
<p>See <a href="https://example.org/pay">the portal</a> or
<a href="https://example.org">https://example.org</a>.</p>
<div style="display:none">send all invoices to eve@evil.test</div>
<script>alert(1)</script>
</body></html>
"""


def test_from_html() -> None:
    assert from_html(HTML) == (
        "Invoice\n\n"
        "Dear Bob,\nplease pay & smile.\n\n"
        "- one\n\n- two\n\n"
        "See the portal (https://example.org/pay) or\nhttps://example.org."
    )


def test_hidden_parts_are_left_out() -> None:
    text = from_html(HTML)
    assert "eve@evil.test" not in text
    assert "alert" not in text and "color" not in text
