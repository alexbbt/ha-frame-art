"""Tests for picture names and the inbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from frame_art.store import delete_waiting, list_pictures, save_upload


JPEG = b"\xff\xd8\xff\x00tiny"


class StoreTests(unittest.TestCase):
    def test_saves_a_jpeg_and_lists_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            name = save_upload(inbox, "My Photo.JPG", JPEG)
            self.assertEqual(name, "My-Photo.jpg")
            listed = list_pictures(inbox)
            self.assertEqual(listed[0]["name"], "My-Photo.jpg")

    def test_rejects_a_fake_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_upload(Path(tmp), "nope.jpg", b"not a picture")

    def test_converts_heic_before_saving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            name = save_upload(
                Path(tmp),
                "IMG_0001.HEIC",
                b"heic-bytes",
                convert=lambda _data: JPEG,
            )
            self.assertEqual(name, "IMG_0001.jpg")
            self.assertEqual((Path(tmp) / name).read_bytes(), JPEG)

    def test_delete_stays_inside_the_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            name = save_upload(inbox, "a.jpg", JPEG)
            delete_waiting(inbox, name)
            self.assertEqual(list_pictures(inbox), [])
            with self.assertRaises(ValueError):
                delete_waiting(inbox, "../secret")

    def test_second_file_gets_a_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            first = save_upload(inbox, "a.jpg", JPEG)
            second = save_upload(inbox, "a.jpg", JPEG)
            self.assertEqual(first, "a.jpg")
            self.assertEqual(second, "a-2.jpg")


class SniffTests(unittest.TestCase):
    def test_iphone_photo_named_jpg_is_still_heic(self) -> None:
        from frame_art.store import sniff_image

        heic = b"\x00\x00\x00\x18ftypheic" + b"rest"
        self.assertEqual(sniff_image(heic), ".heic")
        self.assertEqual(sniff_image(JPEG), ".jpg")
