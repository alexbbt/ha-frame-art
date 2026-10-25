"""A small WebSocket client for the Frame art channel."""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
from urllib.parse import quote


def encode_frame(opcode: int, payload: bytes, mask: bytes | None) -> bytes:
    """Build one WebSocket frame. Clients must pass a 4-byte mask."""
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    masked = 0x80 if mask else 0
    if length < 126:
        header.append(masked | length)
    elif length < 65536:
        header.append(masked | 126)
        header += length.to_bytes(2, "big")
    else:
        header.append(masked | 127)
        header += length.to_bytes(8, "big")
    if mask is None:
        return bytes(header) + payload
    if len(mask) != 4:
        raise ValueError("WebSocket mask must be 4 bytes")
    masked_payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + mask + masked_payload


class FrameBuffer:
    """Pull complete WebSocket frames out of a byte buffer."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> None:
        self._buffer += data

    def pop(self) -> tuple[int, bytes] | None:
        if len(self._buffer) < 2:
            return None
        length = self._buffer[1] & 0x7F
        offset = 2
        if length == 126:
            if len(self._buffer) < 4:
                return None
            length = int.from_bytes(self._buffer[2:4], "big")
            offset = 4
        elif length == 127:
            if len(self._buffer) < 10:
                return None
            length = int.from_bytes(self._buffer[2:10], "big")
            offset = 10
        masked = bool(self._buffer[1] & 0x80)
        if masked:
            if len(self._buffer) < offset + 4 + length:
                return None
            mask = self._buffer[offset : offset + 4]
            start = offset + 4
            payload = bytes(
                byte ^ mask[index % 4]
                for index, byte in enumerate(self._buffer[start : start + length])
            )
        else:
            if len(self._buffer) < offset + length:
                return None
            payload = bytes(self._buffer[offset : offset + length])
        opcode = self._buffer[0] & 0x0F
        del self._buffer[: offset + (4 if masked else 0) + length]
        return opcode, payload


class WebSocket:
    """Client socket that speaks just enough WebSocket for the TV."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._frames = FrameBuffer()

    def send_text(self, text: str) -> None:
        self._send(0x1, text.encode("utf-8"))

    def send_binary(self, payload: bytes) -> None:
        self._send(0x2, payload)

    def recv(self) -> str | bytes:
        while True:
            frame = self._frames.pop()
            if frame is None:
                chunk = self._sock.recv(65536)
                if not chunk:
                    raise ConnectionError("The TV closed the connection")
                self._frames.feed(chunk)
                continue
            opcode, payload = frame
            if opcode == 0x8:
                raise ConnectionError("The TV closed the connection")
            if opcode == 0x9:
                self._send(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                return payload.decode("utf-8", "replace")
            if opcode == 0x2:
                return payload
            raise ConnectionError("The TV sent an unsupported message")

    def close(self) -> None:
        try:
            self._send(0x8, b"")
        except OSError:
            pass
        self._sock.close()

    def _send(self, opcode: int, payload: bytes) -> None:
        self._sock.sendall(encode_frame(opcode, payload, os.urandom(4)))


def connect(host: str, port: int, path: str, timeout: float) -> WebSocket:
    """Open a WebSocket and return it after the upgrade response."""
    raw = socket.create_connection((host, port), timeout=timeout)
    sock: socket.socket = raw
    if port == 8002:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        sock = context.wrap_socket(raw, server_hostname=host)
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    buffered = bytearray()
    while b"\r\n\r\n" not in buffered:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise ConnectionError("The TV closed the connection")
        buffered += chunk
    head, rest = bytes(buffered).split(b"\r\n\r\n", 1)
    status = head.split(b"\r\n", 1)[0]
    if b" 101 " not in status:
        sock.close()
        raise ConnectionError("The TV did not accept the art connection")
    ws = WebSocket(sock)
    if rest:
        ws._frames.feed(rest)
    return ws


def art_path(name: str, token: str) -> str:
    """Path and query for the Frame art channel."""
    identity = {
        "name": name,
        "description": name,
        "id": "frame-art",
        "token": token,
    }
    import json

    encoded = base64.b64encode(json.dumps(identity).encode("utf-8")).decode("ascii")
    return "/api/v2/channels/com.samsung.art-app?name=" + quote(encoded, safe="")
