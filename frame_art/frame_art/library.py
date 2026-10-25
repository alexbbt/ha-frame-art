"""Folders for pictures. The TV itself only has one photo pile and Favorites."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

MY_PHOTOS = "MY-C0002"
FAVORITES = "MY-C0004"


def favorite_plan(wanted: set[str], current: set[str]) -> tuple[list[str], list[str]]:
    """Return content ids to favorite and content ids to remove from Favorites."""
    return sorted(wanted - current), sorted(current - wanted)


class Library:
    """Albums and the pictures uploaded from this app."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def status(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def ensure_album(self) -> str:
        with self._lock:
            if not self._data["albums"]:
                album_id = self._add_album("My photos")
                self._save()
                return album_id
            return self._data["albums"][0]["id"]

    def add_album(self, name: str) -> dict:
        with self._lock:
            album_id = self._add_album(name)
            self._save()
            return self._album(album_id)

    def rename_album(self, album_id: str, name: str) -> dict:
        with self._lock:
            album = self._album(album_id)
            album["name"] = _album_name(name)
            self._save()
            return dict(album)

    def delete_album(self, album_id: str) -> None:
        """Remove a folder. Pictures stay on the TV and move to another folder."""
        with self._lock:
            albums = self._data["albums"]
            if len(albums) < 2:
                raise ValueError("Keep at least one folder")
            if not any(album["id"] == album_id for album in albums):
                raise ValueError("That folder is gone")
            destination = next(album["id"] for album in albums if album["id"] != album_id)
            for photo in self._data["photos"]:
                if photo["album_id"] == album_id:
                    photo["album_id"] = destination
            self._data["albums"] = [album for album in albums if album["id"] != album_id]
            if self._data.get("playing_album_id") == album_id:
                self._data["playing_album_id"] = None
                self._data["playing"] = None
            self._save()

    def add_photo(self, album_id: str, name: str, content_id: str = "") -> dict:
        with self._lock:
            self._album(album_id)
            photo = {
                "id": uuid.uuid4().hex,
                "album_id": album_id,
                "name": name,
                "content_id": content_id,
            }
            self._data["photos"].insert(0, photo)
            self._save()
            return dict(photo)

    def set_content(self, photo_id: str, content_id: str) -> dict:
        with self._lock:
            photo = self._photo(photo_id)
            if not content_id:
                raise ValueError("The TV did not keep that picture")
            photo["content_id"] = content_id
            self._save()
            return dict(photo)

    def move_photo(self, photo_id: str, album_id: str) -> dict:
        with self._lock:
            self._album(album_id)
            photo = self._photo(photo_id)
            photo["album_id"] = album_id
            self._save()
            return dict(photo)

    def remove_photo(self, photo_id: str) -> dict:
        with self._lock:
            photo = self._photo(photo_id)
            self._data["photos"] = [
                item for item in self._data["photos"] if item["id"] != photo_id
            ]
            self._save()
            return dict(photo)

    def album_content_ids(self, album_id: str) -> list[str]:
        with self._lock:
            self._album(album_id)
            return [
                photo["content_id"]
                for photo in self._data["photos"]
                if photo["album_id"] == album_id and photo.get("content_id")
            ]

    def mark_playing(self, mode: str | None, album_id: str | None) -> None:
        with self._lock:
            if album_id is not None:
                self._album(album_id)
            self._data["playing"] = mode
            self._data["playing_album_id"] = album_id
            self._save()

    def sync_tv(self, album_id: str, content_ids: list[tuple[str, str]]) -> None:
        """Add pictures found on the TV and drop local ones the TV no longer has."""
        with self._lock:
            self._album(album_id)
            on_tv = {content_id for content_id, _name in content_ids}
            self._data["photos"] = [
                photo
                for photo in self._data["photos"]
                if not photo.get("content_id") or photo["content_id"] in on_tv
            ]
            known = {photo["content_id"] for photo in self._data["photos"]}
            for content_id, name in content_ids:
                if content_id in known:
                    continue
                self._data["photos"].append(
                    {
                        "id": uuid.uuid4().hex,
                        "album_id": album_id,
                        "name": name or content_id,
                        "content_id": content_id,
                    }
                )
            self._save()

    def _add_album(self, name: str) -> str:
        album_id = uuid.uuid4().hex
        self._data["albums"].append({"id": album_id, "name": _album_name(name)})
        return album_id

    def _album(self, album_id: str) -> dict:
        for album in self._data["albums"]:
            if album["id"] == album_id:
                return album
        raise ValueError("That folder is gone")

    def _photo(self, photo_id: str) -> dict:
        for photo in self._data["photos"]:
            if photo["id"] == photo_id:
                return photo
        raise ValueError("That picture is gone")

    def _load(self) -> dict:
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {}
        data.setdefault("albums", [])
        data.setdefault("photos", [])
        data.setdefault("playing", None)
        data.setdefault("playing_album_id", None)
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self._data), encoding="utf-8")
        temporary.replace(self.path)


def _album_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Name the folder")
    return cleaned[:40]
