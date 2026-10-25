"""Folders and the Favorites set sent to the TV."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from frame_art.library import Library, favorite_plan
from frame_art.server import App, handler_for
from frame_art.tv import FrameTV, art_message, d2d_header
from frame_art.ws import FrameBuffer, encode_frame
from http.server import ThreadingHTTPServer


JPEG = b"\xff\xd8\xff\x00tiny"


class PlanTests(unittest.TestCase):
    def test_only_the_folder_stays_favorite(self) -> None:
        turn_on, turn_off = favorite_plan({"MY_F0009"}, {"MY_F0001", "SAM_1"})
        self.assertEqual(turn_on, ["MY_F0009"])
        self.assertEqual(turn_off, ["MY_F0001", "SAM_1"])


class LibraryTests(unittest.TestCase):
    def test_delete_folder_keeps_the_pictures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Library(Path(tmp) / "library.json")
            first = library.add_album("Kitchen")
            second = library.add_album("Winter")
            library.add_photo(first["id"], "a.jpg", "MY_F0001")
            library.delete_album(first["id"])
            status = library.status()
            self.assertEqual([album["name"] for album in status["albums"]], ["Winter"])
            self.assertEqual(status["photos"][0]["album_id"], second["id"])
            self.assertEqual(status["photos"][0]["content_id"], "MY_F0001")


class ProtocolTests(unittest.TestCase):
    def test_frame_round_trip(self) -> None:
        encoded = encode_frame(1, b'{"ok":true}', b"abcd")
        frames = FrameBuffer()
        frames.feed(encoded)
        opcode, payload = frames.pop()
        self.assertEqual(opcode, 1)
        self.assertEqual(payload, b'{"ok":true}')

    def test_upload_header_prefixes_the_length(self) -> None:
        header = d2d_header(12, "secret")
        length = int.from_bytes(header[:4], "big")
        body = json.loads(header[4 : 4 + length])
        self.assertEqual(body["fileLength"], 12)
        self.assertEqual(body["secKey"], "secret")

    def test_play_folder_updates_favorites(self) -> None:
        script = Scripted(
            [
                _d2d(content_list=json.dumps([{"content_id": "MY_F0001"}, {"content_id": "SAM_1"}])),
                _d2d(event="favorite_changed"),
                _d2d(event="favorite_changed"),
                _d2d(event="favorite_changed"),
                _d2d(event="set"),
                _d2d(event="selected"),
            ]
        )
        tv = FrameTV(script, d2d_send=lambda *_args: None)
        self.assertTrue(tv.play_folder(["MY_F0009"], 60))
        sent = [json.loads(json.loads(item)["params"]["data"])["request"] for item in script.sent]
        self.assertEqual(
            sent,
            [
                "get_content_list",
                "change_favorite",
                "change_favorite",
                "change_favorite",
                "set_slideshow_status",
                "select_image",
            ],
        )
        message = json.loads(art_message({"request": "get_content_list"}))
        self.assertEqual(message["method"], "ms.channel.emit")


class PageTests(unittest.TestCase):
    def test_upload_remove_and_play(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeTV()
            app = App(Library(Path(tmp) / "library.json"), lambda: _connect(fake))
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                self.assertEqual(_get(port, "/api/status")["albums"][0]["name"], "My photos")
                created = _post(port, "/api/albums", {"name": "Winter"})
                album_id = created["album"]["id"]
                body, content_type = _multipart("room.jpg", JPEG)
                import frame_art.server as server

                server.prepare_image = lambda filename, data: ("room.jpg", JPEG)
                saved = _raw(port, f"/upload?album={album_id}", body, content_type)
                self.assertEqual(saved["saved"], ["room.jpg"])
                self.assertEqual(fake.uploaded, [JPEG])
                status = _get(port, "/api/status")
                photo_id = status["photos"][0]["id"]
                _post(port, "/api/play", {"album_id": album_id})
                self.assertEqual(fake.played[0], "folder")
                _post(port, "/api/remove", {"id": photo_id})
                self.assertEqual(fake.deleted, ["MY_F0002"])
                self.assertEqual(_get(port, "/api/status")["photos"], [])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)

    def test_one_bad_picture_does_not_drop_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeTV()
            app = App(Library(Path(tmp) / "library.json"), lambda: _connect(fake))
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app))
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            port = httpd.server_address[1]
            try:
                import frame_art.server as server

                def prepare(filename, data):
                    if filename.startswith("bad"):
                        raise ValueError("Could not read that picture")
                    return ("ok.jpg", JPEG)

                server.prepare_image = prepare
                body, content_type = _multipart_many([("bad.jpg", b"nope"), ("ok.jpg", JPEG)])
                result = _raw(port, "/upload?album=", body, content_type)
                self.assertEqual(result["saved"], ["ok.jpg"])
                self.assertEqual(result["failed"][0]["name"], "bad.jpg")
                self.assertIn("Could not read", result["failed"][0]["error"])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)


class FakeTV:
    def __init__(self) -> None:
        self.uploaded: list[bytes] = []
        self.deleted: list[str] = []
        self.played = None

    def upload(self, jpeg: bytes, matte: str = "none") -> str:
        self.uploaded.append(jpeg)
        return "MY_F0002"

    def delete(self, content_ids: list[str]) -> None:
        self.deleted.extend(content_ids)

    def set_favorite(self, content_id: str, on: bool) -> None:
        return None

    def play_folder(self, content_ids: list[str], minutes: int) -> bool:
        self.played = ("folder", content_ids, minutes)
        return True

    def play_all(self, minutes: int) -> None:
        self.played = ("all", minutes)

    def my_photos(self) -> list[tuple[str, str]]:
        return []

    def close(self) -> None:
        return None


class Scripted:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.sent: list[str] = []

    def send_text(self, text: str) -> None:
        self.sent.append(text)

    def send_binary(self, payload: bytes) -> None:
        return None

    def recv(self) -> str:
        return self.replies.pop(0)

    def close(self) -> None:
        return None


def _d2d(**data) -> str:
    data.setdefault("event", "content_list")
    return json.dumps({"event": "d2d_service_message", "data": json.dumps(data)})


def _connect(fake: FakeTV):
    from contextlib import contextmanager

    @contextmanager
    def _open():
        yield fake

    return _open()


def _get(port: int, path: str) -> dict:
    with urlopen(f"http://127.0.0.1:{port}{path}") as response:
        return json.load(response)


def _post(port: int, path: str, payload: dict) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request) as response:
        return json.load(response)


def _raw(port: int, path: str, body: bytes, content_type: str) -> dict:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urlopen(request) as response:
        return json.load(response)


def _multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    return _multipart_many([(filename, data)])


def _multipart_many(files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    chunks = []
    for filename, data in files:
        chunks.append(
            b"--bound\r\n"
            + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
            + b"Content-Type: image/jpeg\r\n\r\n"
            + data
            + b"\r\n"
        )
    return b"".join(chunks) + b"--bound--\r\n", "multipart/form-data; boundary=bound"
