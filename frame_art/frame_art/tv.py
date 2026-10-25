"""Talk to a Samsung Frame art channel."""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime

from .library import FAVORITES, MY_PHOTOS, favorite_plan
from .ws import WebSocket, art_path, connect

CLIENT_NAME = "Frame Art"


class TVError(Exception):
    """The TV refused a request or the connection failed."""


def art_message(body: dict) -> str:
    """WebSocket text for one art request."""
    return json.dumps(
        {
            "method": "ms.channel.emit",
            "params": {
                "event": "art_app_request",
                "to": "host",
                "data": json.dumps(body),
            },
        }
    )


def d2d_header(file_size: int, key: str) -> bytes:
    """4-byte length plus the JSON header the TV expects before the JPEG."""
    header = json.dumps(
        {
            "num": 0,
            "total": 1,
            "fileLength": file_size,
            "fileName": "image",
            "fileType": "jpg",
            "secKey": key,
            "version": "0.0.1",
        }
    ).encode("ascii")
    return len(header).to_bytes(4, "big") + header


def content_id_of(item: dict) -> str:
    value = item.get("content_id") or item.get("contentId") or ""
    return str(value)


def content_items(payload: dict) -> list[dict]:
    raw = payload.get("content_list", [])
    if isinstance(raw, str):
        raw = json.loads(raw or "[]")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


class FrameTV:
    """One short-lived connection to the TV."""

    def __init__(self, ws: WebSocket, *, d2d_send) -> None:
        self.ws = ws
        self._d2d_send = d2d_send
        self.api_version = ""

    def close(self) -> None:
        self.ws.close()

    def request(self, name: str, *, request_id: str | None = None, wait_for: str | None = None, **params):
        req_id = request_id or str(uuid.uuid4())
        body = {"request": name, "id": req_id, "request_id": req_id, **params}
        self.ws.send_text(art_message(body))
        return self._wait(req_id, wait_for)

    def _api_version(self) -> str:
        try:
            payload = self.request("api_version")
        except TVError:
            payload = self.request("get_api_version")
        version = payload.get("version") if isinstance(payload, dict) else None
        return str(version or "")

    def _wait(self, request_id: str | None, sub_event: str | None) -> dict:
        while True:
            try:
                raw = self.ws.recv()
            except (TimeoutError, ConnectionError, OSError) as err:
                raise TVError("The TV did not answer") from err
            if isinstance(raw, (bytes, bytearray)):
                if raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG"):
                    return {"binary": bytes(raw)}
                continue
            if not isinstance(raw, str):
                continue
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = frame.get("event", "")
            if event == "ms.channel.unauthorized":
                raise TVError("Accept Frame Art on the TV screen, then try again")
            if event != "d2d_service_message":
                continue
            payload = _payload(frame)
            message_id = payload.get("request_id", payload.get("id"))
            if request_id and message_id not in {None, request_id}:
                continue
            if payload.get("event") == "error":
                raise TVError("The TV refused that request")
            if sub_event is None or payload.get("event") in {None, "*", sub_event}:
                return payload

    def upload(self, jpeg: bytes, matte: str = "none") -> str:
        if not self.api_version:
            self.api_version = self._api_version()
        upload_id = str(uuid.uuid4())
        if self.api_version == "0.97":
            self.ws.send_binary(_binary_upload(upload_id, jpeg, matte))
            done = self._wait(upload_id, "image_added")
            return _required_id(done)
        ready = self.request(
            "send_image",
            request_id=upload_id,
            wait_for="ready_to_use",
            file_type="jpg",
            file_size=len(jpeg),
            image_date=datetime.now().strftime("%Y:%m:%d %H:%M:%S"),
            matte_id=matte or "none",
            portrait_matte_id=matte or "none",
            conn_info={
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                "id": upload_id,
            },
        )
        info = _conn_info(ready)
        self._d2d_send(info, d2d_header(len(jpeg), str(info.get("key", ""))) + jpeg)
        done = self._wait(None, "image_added")
        return _required_id(done)

    def delete(self, content_ids: list[str]) -> None:
        if not content_ids:
            return
        self.request(
            "delete_image_list",
            content_id_list=[{"content_id": content_id} for content_id in content_ids],
        )

    def my_photos(self) -> list[tuple[str, str]]:
        items = content_items(self.request("get_content_list", category=MY_PHOTOS))
        found = []
        for item in items:
            content_id = content_id_of(item)
            if not content_id:
                continue
            name = str(item.get("content_name") or item.get("name") or content_id)
            found.append((content_id, name))
        return found

    def favorite_ids(self) -> set[str]:
        items = content_items(self.request("get_content_list", category=FAVORITES))
        return {content_id for item in items if (content_id := content_id_of(item))}

    def set_favorite(self, content_id: str, on: bool) -> None:
        self.request(
            "change_favorite",
            wait_for="favorite_changed",
            content_id=content_id,
            status="on" if on else "off",
        )

    def slideshow(self, category_id: str, minutes: int, *, shuffle: bool = True) -> None:
        self.request(
            "set_slideshow_status",
            value="off" if minutes <= 0 else str(minutes),
            category_id=category_id,
            type="shuffleslideshow" if shuffle else "slideshow",
        )

    def show(self, content_id: str) -> None:
        self.request(
            "select_image",
            content_id=content_id,
            category_id=MY_PHOTOS,
            show=True,
        )

    def read_controls(self) -> dict:
        slideshow = slideshow_view(self.request("get_slideshow_status"))
        try:
            art = art_items(self.request("get_artmode_settings"))
        except TVError:
            art = {}
        return {"slideshow": slideshow, "art": art}

    def apply_slideshow(self, category_id: str, minutes: int, shuffle: bool) -> None:
        self.slideshow(category_id, minutes, shuffle=shuffle)

    def apply_art(self, item: str, value: str) -> None:
        if item == "brightness":
            self.request("set_brightness", value=str(value))
            return
        if item == "color_temperature":
            self.request("set_color_temperature", value=str(value))
            return
        if item == "motion_sensitivity":
            self.request("set_motion_sensitivity", value=str(value))
            return
        if item == "motion_timer":
            self.request("set_motion_timer", value=str(value))
            return
        if item == "brightness_sensor":
            self.request("set_brightness_sensor_setting", value="on" if str(value) == "on" else "off")
            return
        raise TVError("That setting is not on this TV")

    def thumbnail(self, content_id: str) -> bytes:
        request_id = str(uuid.uuid4())
        ready = self.request(
            "get_thumbnail",
            request_id=request_id,
            content_id=content_id,
            conn_info={
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                "id": request_id,
            },
        )
        return _recv_thumbnail(_conn_info(ready))

    def thumbnails(self, content_ids: list[str]) -> dict[str, bytes]:
        ids = [content_id for content_id in content_ids if content_id]
        if not ids:
            return {}
        request_id = str(uuid.uuid4())
        ready = self.request(
            "get_thumbnail_list",
            request_id=request_id,
            content_id_list=[{"content_id": content_id} for content_id in ids],
            conn_info={
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                "id": request_id,
            },
        )
        inline = ready.get("binary")
        if isinstance(inline, (bytes, bytearray)) and inline and len(ids) == 1:
            return {ids[0]: bytes(inline)}
        found = _recv_thumbnail_list(_conn_info(ready))
        mapped: dict[str, bytes] = {}
        for content_id in ids:
            if content_id in found:
                mapped[content_id] = found[content_id]
                continue
            for key, data in found.items():
                if key == content_id or key.startswith(content_id + "."):
                    mapped[content_id] = data
                    break
        if not mapped and len(found) == len(ids):
            mapped = dict(zip(ids, found.values()))
        return mapped

    def play_folder(self, content_ids: list[str], minutes: int, *, shuffle: bool = True) -> bool:
        """Make Favorites equal this set and rotate it. Returns whether one is on screen."""
        wanted = set(content_ids)
        turn_on, turn_off = favorite_plan(wanted, self.favorite_ids())
        for content_id in turn_on:
            self.set_favorite(content_id, True)
        for content_id in turn_off:
            self.set_favorite(content_id, False)
        self.slideshow(FAVORITES, minutes, shuffle=shuffle)
        if not content_ids:
            return False
        try:
            self.show(content_ids[0])
        except TVError:
            return False
        return True

    def play_all(self, minutes: int, *, shuffle: bool = True) -> None:
        self.slideshow(MY_PHOTOS, minutes, shuffle=shuffle)


def slideshow_view(payload: dict) -> dict:
    """Normalize a get_slideshow_status payload."""
    extra = payload.get("data")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra or "{}")
        except json.JSONDecodeError:
            extra = None
    if isinstance(extra, dict):
        payload = {**payload, **extra}
    raw = str(payload.get("value") or "off")
    minutes = 0
    if raw != "off":
        try:
            minutes = int(raw)
        except ValueError:
            minutes = 0
    kind = str(payload.get("type") or "")
    return {
        "minutes": minutes,
        "shuffle": "shuffle" in kind,
        "category_id": str(payload.get("category_id") or MY_PHOTOS),
    }


def art_items(payload: dict) -> dict[str, str]:
    """Map get_artmode_settings items to their values."""
    data = payload.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data or "[]")
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, list):
        return {}
    found: dict[str, str] = {}
    for item in data:
        if isinstance(item, dict) and item.get("item") is not None:
            found[str(item["item"])] = "" if item.get("value") is None else str(item.get("value"))
    return found


def open_tv(host: str, port: int, token: str, timeout: float = 25) -> FrameTV:
    if not host:
        raise TVError("Set the TV address in the app options")
    try:
        ws = connect(host, port, art_path(CLIENT_NAME, token), timeout)
    except OSError as err:
        raise TVError("Could not reach the TV") from err
    tv = FrameTV(ws, d2d_send=_send_d2d)
    try:
        _finish_handshake(tv)
    except Exception:
        tv.close()
        raise
    return tv


def _finish_handshake(tv: FrameTV) -> None:
    seen_connect = False
    for _ in range(8):
        try:
            raw = tv.ws.recv()
        except (TimeoutError, ConnectionError, OSError) as err:
            raise TVError("The TV did not answer") from err
        if not isinstance(raw, str):
            continue
        frame = json.loads(raw)
        event = frame.get("event", "")
        if event == "ms.channel.unauthorized":
            raise TVError("Accept Frame Art on the TV screen, then try again")
        if event == "ms.channel.connect":
            seen_connect = True
            continue
        if event == "ms.channel.ready" or (seen_connect and event == "d2d_service_message"):
            return
    raise TVError("The TV did not open the art connection")


def _send_d2d(info: dict, payload: bytes) -> None:
    sock = _open_d2d(info)
    try:
        sock.sendall(payload)
    finally:
        sock.close()


def _recv_thumbnail(info: dict) -> bytes:
    sock = _open_d2d(info)
    try:
        header_len = int.from_bytes(_recv_exact(sock, 4), "big")
        if header_len <= 0 or header_len > 1_000_000:
            raise TVError("The TV did not send a preview")
        header = json.loads(_recv_exact(sock, header_len))
        size = int(header.get("fileLength") or 0)
        if size <= 0 or size > 8_000_000:
            raise TVError("The TV did not send a preview")
        return _recv_exact(sock, size)
    finally:
        sock.close()


def _recv_thumbnail_list(info: dict) -> dict[str, bytes]:
    sock = _open_d2d(info)
    found: dict[str, bytes] = {}
    try:
        total = 1
        current = -1
        while current + 1 < total:
            header_len = int.from_bytes(_recv_exact(sock, 4), "big")
            if header_len <= 0 or header_len > 1_000_000:
                raise TVError("The TV did not send a preview")
            header = json.loads(_recv_exact(sock, header_len))
            size = int(header.get("fileLength") or 0)
            if size <= 0 or size > 8_000_000:
                raise TVError("The TV did not send a preview")
            data = _recv_exact(sock, size)
            name = str(header.get("fileID") or header.get("fileName") or len(found))
            found[name] = data
            current = int(header.get("num") or 0)
            total = int(header.get("total") or 1)
        return found
    finally:
        sock.close()


def _recv_exact(sock, size: int) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise TVError("The TV did not send a preview")
        buf.extend(chunk)
    return bytes(buf)


def _open_d2d(info: dict):
    import socket
    import ssl

    host = str(info.get("ip") or "")
    port = int(info.get("port") or 0)
    if not host or not port:
        raise TVError("The TV did not accept the picture")
    sock = socket.create_connection((host, port), timeout=25)
    try:
        if info.get("secured"):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock, server_hostname=host)
        return sock
    except Exception:
        sock.close()
        raise


def _binary_upload(upload_id: str, jpeg: bytes, matte: str) -> bytes:
    outer = {
        "method": "ms.channel.emit",
        "params": {
            "data": json.dumps(
                {
                    "request": "send_image",
                    "file_type": "JPEG",
                    "matte_id": matte or "none",
                    "id": upload_id,
                }
            ),
            "to": "host",
            "event": "art_app_request",
        },
    }
    header = json.dumps(outer, separators=(",", ":")).encode("utf-8")
    return len(header).to_bytes(2, "big") + header + jpeg


def _payload(frame: dict) -> dict:
    data = frame.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _conn_info(payload: dict) -> dict:
    info = payload.get("conn_info", {})
    if isinstance(info, str):
        info = json.loads(info or "{}")
    return info if isinstance(info, dict) else {}


def _required_id(payload: dict) -> str:
    content_id = content_id_of(payload)
    if not content_id:
        raise TVError("The TV did not keep that picture")
    return content_id
