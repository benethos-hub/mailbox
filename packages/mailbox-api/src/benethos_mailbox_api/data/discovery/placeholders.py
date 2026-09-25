"""The placeholders of the autoconfig format: what a file writes where the
address goes, in a host name or a login name. Presets use them too."""

from __future__ import annotations

ADDRESS = "%EMAILADDRESS%"
LOCAL_PART = "%EMAILLOCALPART%"
DOMAIN = "%EMAILDOMAIN%"


def fill(template: str, email: str) -> str:
    """``template`` with the address filled in."""
    local, _, domain = email.rpartition("@")
    return (
        template.replace(ADDRESS, email)
        .replace(LOCAL_PART, local)
        .replace(DOMAIN, domain)
    )


def fill_domain(template: str, domain: str) -> str:
    """``template`` with the domain filled in, where only that is known."""
    return template.replace(DOMAIN, domain)
