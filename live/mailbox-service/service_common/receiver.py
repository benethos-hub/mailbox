"""A webhook receiver on 127.0.0.1 that keeps what it is sent."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any


class Receiver:
    """A webhook receiver on 127.0.0.1 that keeps each post it takes."""

    def __init__(self) -> None:
        posts: list[tuple[bytes, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                posts.append(
                    (self.rfile.read(length), self.headers["X-Mailbox-Signature"])
                )
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass

        self.posts = posts
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/hook"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def signed(self, secret: str) -> bool:
        """Whether every post carries a valid signature."""
        for body, header in self.posts:
            stamp, digest = (part.split("=", 1)[1] for part in header.split(","))
            expected = hmac.new(
                secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(digest, expected):
                return False
        return bool(self.posts)

    def events(self) -> list[dict[str, Any]]:
        return [e for body, _ in self.posts for e in json.loads(body)["events"]]

    def close(self) -> None:
        self.server.shutdown()
