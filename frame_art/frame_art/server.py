"""Upload page for pictures that should go on a Samsung Frame."""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .store import delete_waiting, list_pictures, save_upload

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 80 * 1024 * 1024


def inbox_dir() -> Path:
    return Path(os.environ.get("FRAME_ART_INBOX", "/homeassistant/www/frame-art/inbox"))


def uploaded_dir() -> Path:
    return Path(
        os.environ.get("FRAME_ART_UPLOADED", "/homeassistant/www/frame-art/uploaded")
    )


def parse_files(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    """Return (filename, payload) pairs from a multipart body."""
    match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "")
    if match is None:
        raise ValueError("Upload the pictures from the page")
    boundary = (match.group(1) or match.group(2) or "").strip()
    if not boundary:
        raise ValueError("Upload the pictures from the page")
    marker = b"--" + boundary.encode("utf-8", "replace")
    found: list[tuple[str, bytes]] = []
    for part in body.split(marker):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if not part or part.startswith(b"--"):
            continue
        header_blob, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        filename = _filename(header_blob.decode("utf-8", "replace"))
        if filename:
            found.append((filename, data))
    if not found:
        raise ValueError("Choose a picture first")
    return found


def _filename(header: str) -> str | None:
    match = re.search(r'filename="([^"]*)"', header, re.IGNORECASE)
    if match is None:
        match = re.search(r"filename=([^;\r\n]+)", header, re.IGNORECASE)
    if match is None:
        return None
    name = unquote(match.group(1).strip().strip('"'))
    return name or None


class Handler(BaseHTTPRequestHandler):
    server_version = "FrameArt"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._static("index.html", "text/html; charset=utf-8")
            return
        if path == "/style.css":
            self._static("style.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._static("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/api/status":
            self._json(
                200,
                {
                    "inbox": list_pictures(inbox_dir()),
                    "uploaded": list_pictures(uploaded_dir(), limit=30),
                },
            )
            return
        self._json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Upload the pictures from the page"})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"error": "That upload is empty or larger than 80 MB"})
            return
        body = self.rfile.read(length)
        try:
            if path == "/upload":
                saved = [
                    save_upload(inbox_dir(), name, data)
                    for name, data in parse_files(self.headers.get("Content-Type", ""), body)
                ]
                self._json(200, {"saved": saved})
                return
            if path == "/delete":
                payload = json.loads(body.decode("utf-8"))
                delete_waiting(inbox_dir(), str(payload.get("name", "")))
                self._json(200, {"ok": True})
                return
        except (ValueError, json.JSONDecodeError, OSError) as err:
            message = str(err) if isinstance(err, ValueError) else "Could not save that picture"
            self._json(400, {"error": message})
            return
        self._json(404, {"error": "Not found"})

    def log_message(self, fmt: str, *args) -> None:
        return

    def _static(self, name: str, content_type: str) -> None:
        path = STATIC / name
        if not path.is_file():
            self._json(404, {"error": "Not found"})
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(os.environ.get("PORT", "8391"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    httpd.serve_forever()
