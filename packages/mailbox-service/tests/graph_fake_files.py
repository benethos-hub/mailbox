"""The files of the fake Graph mailbox: a file added to a draft in one
request or through an upload session, and the MIME with them, as
``graph_fake.FakeGraph`` answers them."""

from __future__ import annotations

import base64
from email import message_from_bytes
from email.policy import default
from typing import Any

import httpx

# What Graph takes in one request, and the least an upload session takes.
REQUEST_LIMIT = 4 * 1024 * 1024
SESSION_MINIMUM = 3_000_000
UPLOADS = "outlook.office.com"


def json_answer(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


class FileCalls:
    """The file calls of the fake. The mailbox holds the sources, the
    files added one by one and the open upload sessions."""

    raws: dict[str, bytes]
    files: dict[str, list[dict[str, Any]]]
    sessions: dict[str, dict[str, Any]]

    def mime(self, message_id: str) -> bytes:
        """The message's MIME, with the files added one by one."""
        files = self.files.get(message_id, [])
        if not files:
            return self.raws[message_id]
        parsed = message_from_bytes(self.raws[message_id], policy=default)
        for file in files:
            maintype, _, subtype = file["contentType"].partition("/")
            parsed.add_attachment(
                file["data"], maintype, subtype, filename=file["name"]
            )
        return parsed.as_bytes()

    def _attach(
        self, message: dict[str, Any], rest: list[str], body: dict[str, Any]
    ) -> httpx.Response:
        """A file in one request, or an upload session for a large one."""
        if not rest:
            data = base64.b64decode(body.pop("contentBytes"))
            self.files.setdefault(message["id"], []).append({**body, "data": data})
            return json_answer(201, {"id": f"file-{len(self.files[message['id']])}"})
        item = body["AttachmentItem"]
        if item["size"] < SESSION_MINIMUM:
            return json_answer(
                400,
                {
                    "error": {
                        "code": "ErrorAttachmentSizeShouldNotBeLessThanMinimumSize",
                        "message": "too small for an upload session",
                    }
                },
            )
        session = f"s{len(self.sessions) + 1}"
        self.sessions[session] = {"message": message["id"], "item": item, "data": b""}
        url = f"https://{UPLOADS}/api/v2.0/AttachmentSessions/{session}"
        return json_answer(
            201, {"uploadUrl": f"{url}?authtoken=t", "nextExpectedRanges": ["0-"]}
        )

    def _upload(self, request: httpx.Request, session: str) -> httpx.Response:
        """A range of a file, in order, without a token of the account."""
        assert "authorization" not in request.headers
        assert len(request.content) <= REQUEST_LIMIT
        open_ = self.sessions[session]
        span, _, total = (
            request.headers["content-range"].removeprefix("bytes ").partition("/")
        )
        start = int(span.split("-")[0])
        assert start == len(open_["data"]), "ranges come in order"
        open_["data"] += request.content
        if len(open_["data"]) < int(total):
            return json_answer(200, {"nextExpectedRanges": [str(len(open_["data"]))]})
        item = open_["item"]
        self.files.setdefault(open_["message"], []).append(
            {**item, "data": open_["data"]}
        )
        del self.sessions[session]
        return httpx.Response(201)
