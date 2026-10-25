"""Check picture names and file types before they go to the TV."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

MAX_BYTES = 40 * 1024 * 1024
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}


def safe_filename(name: str) -> str:
    """Return a single path segment with a known picture suffix."""
    base = Path(name or "").name
    suffix = Path(base).suffix.lower()
    if suffix not in ALLOWED:
        raise ValueError("Use a JPEG, PNG, WebP, or HEIC picture")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(base).stem).strip(".-")
    if not stem:
        stem = "picture"
    return stem[:80] + suffix


def looks_like_image(data: bytes, suffix: str) -> bool:
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".webp":
        return len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def convert_heic(data: bytes) -> bytes:
    """Turn an HEIC/HEIF payload into JPEG bytes using heif-convert."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source = folder / "in.heic"
        dest = folder / "out.jpg"
        source.write_bytes(data)
        try:
            proc = subprocess.run(
                ["heif-convert", str(source), str(dest)],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as err:
            raise ValueError("Could not read that HEIC picture") from err
        if proc.returncode != 0 or not dest.is_file():
            raise ValueError("Could not read that HEIC picture")
        return dest.read_bytes()


def save_upload(
    inbox: Path,
    filename: str,
    data: bytes,
    *,
    convert=convert_heic,
) -> str:
    """Write one picture into the inbox. Returns the stored file name."""
    if not data:
        raise ValueError("That file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError("That picture is larger than 40 MB")
    name = safe_filename(filename)
    suffix = Path(name).suffix.lower()
    if suffix in {".heic", ".heif"}:
        data = convert(data)
        name = f"{Path(name).stem}.jpg"
        suffix = ".jpg"
    if not looks_like_image(data, suffix):
        raise ValueError("That file is not a JPEG, PNG, or WebP picture")
    inbox.mkdir(parents=True, exist_ok=True)
    dest = _unique(inbox, name)
    dest.write_bytes(data)
    return dest.name


def list_pictures(folder: Path, limit: int | None = None) -> list[dict[str, int | str]]:
    if not folder.is_dir():
        return []
    files = [path for path in folder.iterdir() if path.is_file() and not path.name.startswith(".")]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if limit is not None:
        files = files[:limit]
    return [{"name": path.name, "bytes": path.stat().st_size} for path in files]


def delete_waiting(inbox: Path, name: str) -> None:
    """Remove one inbox file. Refuses anything that is not a direct child."""
    if not name or name != Path(name).name or name.startswith("."):
        raise ValueError("That picture is not waiting")
    path = (inbox / name).resolve()
    inbox_root = inbox.resolve()
    if inbox_root not in path.parents or not path.is_file():
        raise ValueError("That picture is not waiting")
    path.unlink()


def _unique(folder: Path, name: str) -> Path:
    dest = folder / name
    if not dest.exists():
        return dest
    stem = Path(name).stem
    suffix = Path(name).suffix
    for number in range(2, 1000):
        candidate = folder / f"{stem}-{number}{suffix}"
        if not candidate.exists():
            return candidate
    raise ValueError("Too many pictures already use that name")
