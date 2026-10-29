"""The headers every answer under ``/ui`` carries: the content security
policy and what keeps a page out of frames and caches."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .session import PATH


def security_headers(sign_in_hosts: list[str]) -> list[tuple[bytes, bytes]]:
    """No inline script or style, no framing, nothing loaded from elsewhere.
    Forms post here only. The one exception is the redirect of an OAuth
    sign-in to its provider's ``sign_in_hosts``."""
    form_action = " ".join(["'self'", *(f"https://{h}" for h in sign_in_hosts)])
    policy = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; "
        f"form-action {form_action}; base-uri 'none'"
    )
    return [
        (b"content-security-policy", policy.encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"same-origin"),
        (b"cache-control", b"no-store"),
    ]


class Security:
    """Security headers on every answer under ``/ui``."""

    def __init__(
        self, app: ASGIApp, headers: list[tuple[bytes, bytes]], static: str
    ) -> None:
        self.app = app
        self.headers = headers
        self.static = static

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(PATH):
            await self.app(scope, receive, send)
            return

        headers = self.headers
        if scope["path"].startswith(self.static):
            # The same for every user: kept, and asked again before use,
            # which the file's ETag answers with 304.
            headers = [
                (name, b"no-cache" if name == b"cache-control" else value)
                for name, value in headers
            ]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *headers]
            await send(message)

        await self.app(scope, receive, send_with_headers)
