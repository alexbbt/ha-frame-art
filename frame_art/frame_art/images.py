"""Turn an upload into a JPEG the Frame can store."""

from __future__ import annotations

import io
from pathlib import Path

from .store import convert_heic, looks_like_image, safe_filename

FRAME = (3840, 2160)


def prepare_image(filename: str, data: bytes, *, convert=convert_heic) -> tuple[str, bytes]:
    """Return a display name and 4K JPEG bytes."""
    stored = safe_filename(filename)
    suffix = Path(stored).suffix.lower()
    if suffix in {".heic", ".heif"}:
        data = convert(data)
        suffix = ".jpg"
        stored = f"{Path(stored).stem}.jpg"
    if not looks_like_image(data, suffix):
        raise ValueError("That file is not a JPEG, PNG, or WebP picture")
    jpeg = to_frame_jpeg(data)
    return Path(stored).stem + ".jpg", jpeg


def to_frame_jpeg(data: bytes) -> bytes:
    """Letterbox a picture onto a 3840x2160 black frame."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image.thumbnail(FRAME, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", FRAME, (0, 0, 0))
        canvas.paste(image, ((FRAME[0] - image.width) // 2, (FRAME[1] - image.height) // 2))
        output = io.BytesIO()
        canvas.save(output, "JPEG", quality=90)
        return output.getvalue()
