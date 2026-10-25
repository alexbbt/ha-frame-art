"""Talk to a Samsung Frame art channel."""

from __future__ import annotations

import json
import random
import time
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
        self._queued: list[dict] = []

    def close(self) -> None:
        self.ws.close()

    def request(self, name: str, *, request_id: str | None = None, wait_for: str | None = None, **params):
        req_id = request_id or str(uuid.uuid4())
        body = {"request": name, "id": req_id, "request_id": req_id, **params}
        self.ws.send_text(art_message(body))
        return self._wait(req_id, wait_for, name)

    def _api_version(self) -> str:
        try:
            payload = self.request("api_version")
        except TVError:
            payload = self.request("get_api_version")
        version = payload.get("version") if isinstance(payload, dict) else None
        return str(version or "")

    def _wait(
        self,
        request_id: str | None,
        sub_event: str | None,
        request_name: str = "",
        deadline: float | None = None,
    ) -> dict:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise TVError("The TV did not answer")
            if self._queued:
                frame = self._queued.pop(0)
            else:
                try:
                    raw = self.ws.recv()
                except (TimeoutError, ConnectionError, OSError) as err:
                    raise TVError("The TV did not answer") from err
                frames = _frames_from_tv(raw)
                if not frames:
                    continue
                frame = frames[0]
                self._queued.extend(frames[1:])
            binary = frame.pop("binary", None)
            event = frame.get("event", "")
            if event == "ms.channel.unauthorized":
                raise TVError("Accept Frame Art on the TV screen, then try again")
            if event != "d2d_service_message":
                if binary and not event:
                    return {"binary": binary}
                if deadline is not None:
                    print(f"Frame Art skipped {event or 'message'}", flush=True)
                continue
            payload = _payload(frame)
            if binary:
                payload["binary"] = binary
            # A thumbnail's own id is not the request id. Matching it drops the preview.
            if payload.get("event") != "thumbnail":
                message_id = payload.get("request_id", payload.get("id"))
                if request_id and message_id not in {None, request_id}:
                    if deadline is not None:
                        print(f"Frame Art skipped {payload.get('event') or 'reply'}", flush=True)
                    continue
            if payload.get("event") == "error":
                named = _request_of(payload)
                if named and request_name and named != request_name:
                    continue
                raise _refused(payload, request_name)
            if sub_event is None or payload.get("event") in {None, "*", sub_event}:
                return payload

    def _connection_ready(self, request_id: str) -> dict:
        """Keep reading until the TV sends the preview socket, or an inline image."""
        for _ in range(8):
            payload = self._wait(request_id, "ready_to_use")
            inline = payload.get("binary")
            if isinstance(inline, (bytes, bytearray)) and inline:
                return payload
            info = _conn_info(payload)
            if info.get("ip") and info.get("port"):
                return payload
        raise TVError("The TV did not send a preview")

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

    def slideshow(
        self,
        category_id: str,
        minutes: int,
        *,
        shuffle: bool = True,
        content_ids: list[str] | None = None,
    ) -> None:
        """Start or stop the TV slideshow. A folder is the content list on this set."""
        chosen = [content_id for content_id in (content_ids or []) if content_id]
        params = {
            "value": "off" if minutes <= 0 else str(minutes),
            "category_id": category_id,
            "type": "shuffleslideshow" if shuffle else "slideshow",
        }
        if chosen:
            params["content_list"] = json.dumps([{"content_id": content_id} for content_id in chosen])
        try:
            self.request("set_slideshow_status", **params)
        except TVError:
            if not chosen or category_id == MY_PHOTOS:
                raise
            params["category_id"] = MY_PHOTOS
            self.request("set_slideshow_status", **params)

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

    def apply_slideshow(
        self,
        category_id: str,
        minutes: int,
        shuffle: bool,
        content_ids: list[str] | None = None,
    ) -> None:
        self.slideshow(category_id, minutes, shuffle=shuffle, content_ids=content_ids)

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
        inline = _image_bytes(ready.get("binary"))
        if inline:
            return inline
        return _recv_thumbnail(_conn_info(ready))

    def thumbnails(self, content_ids: list[str]) -> dict[str, bytes]:
        ids = []
        seen = set()
        for content_id in content_ids:
            if content_id and content_id not in seen:
                seen.add(content_id)
                ids.append(content_id)
        if not ids:
            return {}
        # Store art closes the preview socket for the whole request.
        own = [content_id for content_id in ids if not content_id.startswith("SAM-S")]
        found = self._thumbnail_batch(own) if own else {}
        missing = [content_id for content_id in own if content_id not in found]
        if len(missing) > 1 or (missing and len(own) > 1):
            for content_id in missing:
                found.update(self._thumbnail_batch([content_id]))
        return {content_id: found[content_id] for content_id in ids if content_id in found}

    def _thumbnail_batch(self, content_ids: list[str]) -> dict[str, bytes]:
        ids = [content_id for content_id in content_ids if content_id]
        if not ids:
            return {}
        request_id = str(uuid.uuid4())
        self.ws.send_text(
            art_message(
                {
                    "request": "get_thumbnail_list",
                    "id": request_id,
                    "request_id": request_id,
                    "content_id_list": [{"content_id": content_id} for content_id in ids],
                    "conn_info": {
                        "d2d_mode": "socket",
                        "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                        "id": request_id,
                    },
                }
            )
        )
        setter = getattr(self.ws, "set_timeout", None)
        if setter:
            setter(8)
        found: dict[str, bytes] = {}
        waiting = ""
        deadline = time.monotonic() + 12
        for _ in range(len(ids) + 2):
            if len(found) >= len(ids):
                break
            try:
                payload = self._wait(request_id, None, "get_thumbnail_list", deadline)
            except TVError:
                break
            _keep_thumb(found, payload)
            content_id = str(payload.get("content_id") or "")
            image = _image_bytes(payload.get("binary"))
            if content_id and image:
                waiting = ""
            elif content_id and payload.get("event") == "thumbnail":
                waiting = content_id
            elif image and waiting and waiting not in found:
                found[waiting] = image
                waiting = ""
            info = _conn_info(payload)
            if info.get("ip") and info.get("port") and len(found) < len(ids):
                print(f"Frame Art downloading {len(ids)} previews", flush=True)
                try:
                    for key, data in _recv_thumbnail_list(info).items():
                        _keep_named(found, key, data)
                except (OSError, TVError, json.JSONDecodeError):
                    pass
                break
        return found

    def play_folder(self, content_ids: list[str], minutes: int, *, shuffle: bool = True) -> bool:
        """Make Favorites equal this set and rotate it. Returns whether one is on screen."""
        wanted = set(content_ids)
        turn_on, turn_off = favorite_plan(wanted, self.favorite_ids())
        for content_id in turn_on:
            self.set_favorite(content_id, True)
        for content_id in turn_off:
            try:
                self.set_favorite(content_id, False)
            except TVError as err:
                print(f"Frame Art left {content_id} favorite: {err}", flush=True)
        self.slideshow(FAVORITES, minutes, shuffle=shuffle, content_ids=content_ids)
        if not content_ids:
            return False
        try:
            self.show(content_ids[0])
        except TVError:
            return False
        return True

    def play_all(self, minutes: int, *, shuffle: bool = True) -> None:
        self.slideshow(MY_PHOTOS, minutes, shuffle=shuffle)


def _frames_from_tv(raw: str | bytes) -> list[dict]:
    """Split one socket message into art events. Several previews can share it."""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [parsed] if isinstance(parsed, dict) else []
    frames: list[dict] = []
    buf = bytes(raw)
    for _ in range(40):
        if not buf:
            break
        image, used = _slice_image(buf)
        if image and used:
            frames.append({"binary": image})
            buf = buf[used:]
            continue
        start = buf.find(b"{")
        if start < 0:
            break
        end = _json_end(buf, start)
        if end is None:
            break
        try:
            parsed = json.loads(buf[start:end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            break
        if not isinstance(parsed, dict):
            break
        tail = buf[end:]
        if tail.startswith(b"\n"):
            tail = tail[1:]
        image, used = _slice_image(tail)
        if image and used:
            parsed["binary"] = image
            buf = tail[used:]
        else:
            buf = b""
        frames.append(parsed)
    return frames


def _json_end(buf: bytes, start: int) -> int | None:
    depth = 0
    for index in range(start, len(buf)):
        byte = buf[index]
        if byte == 0x7B:
            depth += 1
        elif byte == 0x7D:
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _slice_image(buf: bytes) -> tuple[bytes | None, int]:
    if buf.startswith(b"\xff\xd8\xff"):
        end = buf.find(b"\xff\xd9")
        if end < 0:
            return bytes(buf), len(buf)
        end += 2
        return bytes(buf[:end]), end
    if not buf.startswith(b"\x89PNG\r\n\x1a\n"):
        return None, 0
    offset = 8
    while offset + 8 <= len(buf):
        length = int.from_bytes(buf[offset : offset + 4], "big")
        tag = buf[offset + 4 : offset + 8]
        step = 12 + length
        if length < 0 or offset + step > len(buf):
            break
        offset += step
        if tag == b"IEND":
            return bytes(buf[:offset]), offset
    return bytes(buf), len(buf)


def _image_bytes(data) -> bytes | None:
    if isinstance(data, (bytes, bytearray)) and (
        bytes(data).startswith(b"\xff\xd8\xff") or bytes(data).startswith(b"\x89PNG")
    ):
        return bytes(data)
    return None


def _keep_thumb(found: dict[str, bytes], payload: dict) -> None:
    image = _image_bytes(payload.get("binary"))
    content_id = str(payload.get("content_id") or "")
    if image and content_id:
        found[content_id] = image


def _keep_named(found: dict[str, bytes], key: str, data: bytes) -> None:
    image = _image_bytes(data)
    if not image:
        return
    content_id = key.split(".", 1)[0]
    found[content_id] = image


def _request_of(payload: dict) -> str:
    raw = payload.get("request_data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return ""
    if isinstance(raw, dict):
        return str(raw.get("request") or "")
    return ""


def _refused(payload: dict, request_name: str) -> TVError:
    named = _request_of(payload) or request_name or "that request"
    code = payload.get("error_code")
    detail = f"The TV refused {named}"
    if code not in (None, ""):
        detail += f" ({code})"
    print(f"Frame Art TV error: {detail}", flush=True)
    return TVError(detail)


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
        expected = None
        while expected is None or len(found) < expected:
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
            expected = int(header.get("total") or len(found))
            if len(found) >= 40:
                break
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
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw.settimeout(20)
    try:
        if info.get("secured"):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(raw, server_hostname=host)
        else:
            sock = raw
        sock.connect((host, port))
        sock.settimeout(20)
        return sock
    except Exception:
        raw.close()
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
