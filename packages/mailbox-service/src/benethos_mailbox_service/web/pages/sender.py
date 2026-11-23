"""How a page shows the sender check of a message: a tag beside the
sender, and the sentence behind it as its title.

The words live here, not in a template, so each reason has one sentence
and a test reads them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...data.models import SenderCheck


@dataclass(frozen=True)
class SenderTag:
    """The tag's words, its class (``ok``, ``bad`` or none) and the
    sentence a pointer shows."""

    text: str
    cls: str
    title: str


# Why the check is unknown, one sentence per reason.
_UNKNOWN = {
    "account": "This account does not name its receiving server, so the "
    "check cannot be read.",
    "no_entry": "The receiving server wrote no check into this mail.",
    "several_entries": "The mail carries several checks under the "
    "receiving server's name that disagree, so none counts.",
    "unreadable": "The receiving server's check cannot be read.",
    "error": "The receiving server could not finish its check.",
    "no_proof": "The receiving server's check does not confirm the domain in From.",
}


def sender_tag(check: SenderCheck) -> SenderTag:
    """``checked: example.com``, ``check failed`` or ``not checked``."""
    if check.result == "pass":
        how = f" by {check.method}" if check.method else ""
        return SenderTag(
            f"checked: {check.domain}",
            "ok",
            f"The receiving server confirmed the domain in From{how}.",
        )
    if check.result == "fail":
        return SenderTag(
            "check failed",
            "bad",
            "The receiving server's check of the domain in From failed.",
        )
    if check.reason in ("other_domain", "from_differs") and check.domain:
        return SenderTag(
            "not checked", "", f"The server checked another domain: {check.domain}."
        )
    return SenderTag(
        "not checked",
        "",
        _UNKNOWN.get(check.reason or "", _UNKNOWN["no_proof"]),
    )
