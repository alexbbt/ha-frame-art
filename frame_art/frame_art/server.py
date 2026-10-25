"""Album page for pictures on a Samsung Frame."""

from __future__ import annotations

import json
import os
import re
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .images import prepare_image
from .library import Library
from .tv import TVError, open_tv

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 80 * 1024 * 1024


class App:
    def __init__(self, library: Library, connect) -> None:
        self.library = library
        self.connect = connect
        self.lock = threading.Lock()
        self.thumbs: dict[str, bytes] = {}

    def view(self) -> dict:
        self.library.ensure_album()
        payload = self.library.status()
        payload["configured"] = bool(_host())
        return payload


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
    encoded = re.search(r"filename\*=([^']*)''([^;\r\n]+)", header, re.IGNORECASE)
    if encoded is not None:
        name = unquote(encoded.group(2).strip())
        if name:
            return name
    match = re.search(r'filename="([^"]*)"', header, re.IGNORECASE)
    if match is None:
        match = re.search(r"filename=([^;\r\n]+)", header, re.IGNORECASE)
    if match is None:
        return None
    name = unquote(match.group(1).strip().strip('"'))
    return name or None


def handler_for(app: App):
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
            if path == "/favicon.svg":
                self._static("favicon.svg", "image/svg+xml")
                return
            if path == "/favicon.ico":
                self._static("favicon.ico", "image/x-icon")
                return
            if path == "/api/status":
                self._json(200, app.view())
                return
            if path == "/api/settings":
                self._call(_read_settings, app)
                return
            if path == "/api/previews":
                album_id = parse_qs(urlparse(self.path).query).get("album", [""])[0]
                self._call(_previews, app, album_id)
                return
            if path.startswith("/thumb/"):
                content_id = unquote(path.removeprefix("/thumb/"))
                try:
                    data = _thumb(app, content_id)
                except (ValueError, TVError, OSError) as err:
                    print(f"Frame Art preview failed for {content_id}: {err}", flush=True)
                    self._json(404, {"error": "No preview"})
                    return
                kind = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
                self._bytes(200, data, kind)
                return
            self._json(404, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"error": "That request was incomplete"})
                return
            if length < 0 or length > MAX_BODY:
                self._json(400, {"error": "That picture is larger than 80 MB. Send fewer at a time."})
                return
            body = self.rfile.read(length) if length else b""
            try:
                if parsed.path == "/upload":
                    album_id = parse_qs(parsed.query).get("album", [""])[0]
                    self._json(200, _upload(app, album_id, self.headers.get("Content-Type", ""), body))
                    return
                payload = json.loads(body.decode("utf-8") or "{}")
                result = _action(app, parsed.path, payload)
            except (ValueError, TVError, json.JSONDecodeError, OSError) as err:
                message = str(err).strip() if isinstance(err, (ValueError, TVError)) else "Could not save that picture"
                print(f"Frame Art request failed: {err}", flush=True)
                self._json(400, {"error": message or "Could not save that picture"})
                return
            self._json(200, result)

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

        def _call(self, func, *args) -> None:
            try:
                self._json(200, func(*args))
            except (ValueError, TVError, OSError) as err:
                message = str(err).strip() if isinstance(err, (ValueError, TVError)) else "Could not reach the TV"
                self._json(400, {"error": message or "Could not reach the TV"})

        def _bytes(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "private, max-age=3600")
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _read_settings(app: App) -> dict:
    with app.lock:
        with app.connect() as tv:
            return tv.read_controls()


def _apply_settings(app: App, payload: dict) -> dict:
    with app.lock:
        with app.connect() as tv:
            current = tv.read_controls()
            slide = current["slideshow"]
            if "minutes" in payload or "shuffle" in payload:
                minutes = int(payload.get("minutes", slide["minutes"]))
                shuffle = payload.get("shuffle", slide["shuffle"])
                if isinstance(shuffle, str):
                    shuffle = shuffle.lower() == "true"
                category = str(payload.get("category_id") or slide["category_id"])
                content_ids = None
                playing = app.library.status()
                if playing.get("playing") == "album" and playing.get("playing_album_id"):
                    content_ids = app.library.album_content_ids(str(playing["playing_album_id"]))
                tv.apply_slideshow(category, minutes, bool(shuffle), content_ids)
            item = str(payload.get("item") or "")
            if item:
                tv.apply_art(item, str(payload.get("value", "")))
            return tv.read_controls()


def _image(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG")


def _previews(app: App, album_id: str) -> dict:
    album_id = album_id or app.library.ensure_album()
    ids = [
        content_id
        for content_id in app.library.album_content_ids(album_id)
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", content_id or "")
    ]
    missing = [content_id for content_id in ids if content_id not in app.thumbs]
    if missing:
        with app.lock:
            with app.connect() as tv:
                try:
                    found = tv.thumbnails(missing)
                except TVError:
                    found = {}
        for content_id, data in found.items():
            if content_id in missing and _image(data):
                app.thumbs[content_id] = data
        ready_now = [content_id for content_id in missing if content_id in app.thumbs]
        if ready_now:
            print(f"Frame Art saved {len(ready_now)} previews", flush=True)
        elif missing:
            print(f"Frame Art saved no previews for {len(missing)} pictures", flush=True)
    return {"ready": [content_id for content_id in ids if content_id in app.thumbs]}


def _thumb(app: App, content_id: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", content_id or ""):
        raise ValueError("That picture is gone")
    cached = app.thumbs.get(content_id)
    if not cached:
        raise TVError("No preview")
    return cached


def _upload(app: App, album_id: str, content_type: str, body: bytes) -> dict:
    """Save every picture. One failure does not drop the rest."""
    files = parse_files(content_type, body)
    if not album_id:
        album_id = app.library.ensure_album()
    saved: list[str] = []
    failed: list[dict[str, str]] = []
    with app.lock:
        with app.connect() as tv:
            for filename, data in files:
                label = Path(filename or "picture").name or "picture"
                try:
                    display, jpeg = prepare_image(filename, data)
                    content_id = tv.upload(jpeg)
                    photo = app.library.add_photo(album_id, display, content_id)
                    saved.append(photo["name"])
                    del jpeg
                    if app.library.status().get("playing_album_id") == album_id:
                        tv.set_favorite(content_id, True)
                except Exception as err:
                    message = str(err).strip() or "Could not save that picture"
                    print(f"Frame Art could not save {label}: {message}", flush=True)
                    failed.append({"name": label, "error": message})
    return {"saved": saved, "failed": failed}


def _action(app: App, path: str, payload: dict) -> dict:
    if path == "/api/albums":
        album = app.library.add_album(str(payload.get("name", "")))
        return {"album": album}
    if path == "/api/albums/rename":
        album = app.library.rename_album(str(payload.get("id", "")), str(payload.get("name", "")))
        return {"album": album}
    if path == "/api/albums/delete":
        app.library.delete_album(str(payload.get("id", "")))
        return {"ok": True}
    if path == "/api/move":
        photo = app.library.move_photo(str(payload.get("id", "")), str(payload.get("album_id", "")))
        return {"photo": photo}
    if path == "/api/remove":
        photo_id = str(payload.get("id", ""))
        with app.lock:
            photo = next(
                (item for item in app.library.status()["photos"] if item["id"] == photo_id),
                None,
            )
            if photo is None:
                raise ValueError("That picture is gone")
            with app.connect() as tv:
                tv.delete([photo["content_id"]])
            app.thumbs.pop(photo["content_id"], None)
            app.library.remove_photo(photo_id)
        return {"ok": True}
    if path == "/api/play":
        if payload.get("stop"):
            return _stop(app)
        minutes = payload.get("minutes")
        shuffle = payload.get("shuffle", True)
        if isinstance(shuffle, str):
            shuffle = shuffle.lower() == "true"
        return _play(
            app,
            str(payload.get("album_id", "")),
            None if minutes is None else int(minutes),
            bool(shuffle),
        )
    if path == "/api/sync":
        album_id = str(payload.get("album_id", "")) or app.library.ensure_album()
        with app.lock:
            with app.connect() as tv:
                app.library.sync_tv(album_id, tv.my_photos())
        return {"ok": True}
    if path == "/api/settings":
        return _apply_settings(app, payload)
    raise ValueError("Not found")


def _stop(app: App) -> dict:
    with app.lock:
        with app.connect() as tv:
            current = tv.read_controls()["slideshow"]
            tv.apply_slideshow(current["category_id"], 0, bool(current["shuffle"]))
        app.library.mark_playing(None, None)
    return {"playing": None}


def _play(app: App, album_id: str, minutes: int | None = None, shuffle: bool = True) -> dict:
    chosen = _minutes() if minutes is None else max(0, min(1440, minutes))
    with app.lock:
        with app.connect() as tv:
            if not album_id:
                tv.play_all(chosen, shuffle=shuffle)
                app.library.mark_playing("all", None)
                return {"playing": "all", "showing": False}
            content_ids = app.library.album_content_ids(album_id)
            showing = tv.play_folder(content_ids, chosen, shuffle=shuffle)
            app.library.mark_playing("album", album_id)
    if showing:
        return {"playing": "album", "showing": True}
    return {"playing": "album", "showing": False, "note": "Saved the set. The TV will show it when Art Mode is on."}


def _host() -> str:
    return os.environ.get("FRAME_ART_HOST", "").strip()


def _port() -> int:
    try:
        return int(os.environ.get("FRAME_ART_PORT", "8001"))
    except ValueError:
        return 8001


def _minutes() -> int:
    try:
        value = int(os.environ.get("FRAME_ART_MINUTES", "60"))
    except ValueError:
        return 60
    return min(1440, max(1, value))


def _token(data_dir: Path) -> str:
    configured = os.environ.get("FRAME_ART_TOKEN", "").strip()
    if configured and configured != "null":
        return configured
    path = data_dir / "token"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


@contextmanager
def _connect(data_dir: Path):
    tv = open_tv(_host(), _port(), _token(data_dir))
    try:
        yield tv
    finally:
        tv.close()


def main() -> None:
    data_dir = Path(os.environ.get("FRAME_ART_DATA", "/data"))
    app = App(Library(data_dir / "library.json"), lambda: _connect(data_dir))
    port = int(os.environ.get("PORT", "8391"))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler_for(app))
    httpd.serve_forever()
