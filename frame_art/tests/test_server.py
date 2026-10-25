"""Tests for multipart uploads."""

from __future__ import annotations

import unittest

from frame_art.server import parse_files


class ParseTests(unittest.TestCase):
    def test_reads_the_file_part(self) -> None:
        body = (
            b"--bound\r\n"
            b'Content-Disposition: form-data; name="file"; filename="room.jpg"\r\n'
            b"Content-Type: image/jpeg\r\n"
            b"\r\n"
            b"\xff\xd8\xffhello\r\n"
            b"--bound--\r\n"
        )
        files = parse_files("multipart/form-data; boundary=bound", body)
        self.assertEqual(files, [("room.jpg", b"\xff\xd8\xffhello")])

    def test_reads_every_file(self) -> None:
        body = (
            b"--bound\r\n"
            b'Content-Disposition: form-data; name="file"; filename="one.jpg"\r\n'
            b"\r\n"
            b"aaa\r\n"
            b"--bound\r\n"
            b'Content-Disposition: form-data; name="file"; filename="two.jpg"\r\n'
            b"\r\n"
            b"bbb\r\n"
            b"--bound--\r\n"
        )
        files = parse_files("multipart/form-data; boundary=bound", body)
        self.assertEqual(files, [("one.jpg", b"aaa"), ("two.jpg", b"bbb")])

    def test_requires_a_file(self) -> None:
        with self.assertRaises(ValueError):
            parse_files("multipart/form-data; boundary=bound", b"--bound--\r\n")
