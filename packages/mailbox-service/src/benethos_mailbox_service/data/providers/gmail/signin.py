"""How a Google account signs in: Google's OAuth 2.0 endpoints, the scope
this adapter needs of the Gmail API, and where Gmail says whose mailbox
a token opens.

The project ships no app of its own for Google. The Gmail scopes are
restricted: an app used by anyone would need Google's verification and
a yearly security assessment. Each deployment registers its own client
in a Google Cloud project instead (CONCEPT 5.5, docs/GOOGLE.md).
"""

from __future__ import annotations

from ...protocols import Endpoints, Profile

# Every operation of the API, deleting for good among them. gmail.modify
# would do all but that.
SCOPES = ("https://mail.google.com/",)

# The mailbox's own address. The Gmail scope covers it.
PROFILE = Profile(
    url="https://gmail.googleapis.com/gmail/v1/users/me/profile",
    email=("emailAddress",),
)


def endpoints(_tenant: str | None = None) -> Endpoints:
    """Google has no tenants: any Google account signs in here."""
    return Endpoints(
        provider="gmail",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
        profile=PROFILE,
        # A refresh token, on every sign-in: Google hands one out with
        # the first consent only, unless it is asked for again.
        authorize_params=(("access_type", "offline"), ("prompt", "consent")),
        refresh_scopes=False,
    )
