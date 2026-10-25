"""Turn an upload into a JPEG the Frame can store."""

from __future__ import annotations

import io
from pathlib import Path

from .store import MAX_BYTES, convert_heic, looks_like_image, safe_filename, sniff_image

FRAME = (3840, 2160)


def prepare_image(filename: str, data: bytes, *, convert=convert_heic) -> tuple[str, bytes]:
    """Return a display name and 4K JPEG bytes."""
    if not data:
        raise ValueError("That file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError("That picture is larger than 40 MB")
    kind = sniff_image(data)
    suffix = Path(filename or "").suffix.lower()
    if kind == ".heic" or suffix in {".heic", ".heif"}:
        data = convert(data)
        kind = sniff_image(data) or ".jpg"
    if kind not in {".jpg", ".png", ".webp"} or not looks_like_image(data, kind):
        raise ValueError("That file is not a JPEG, PNG, WebP, or HEIC picture")
    try:
        stored = safe_filename(filename if suffix in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"} else "picture.jpg")
    except ValueError:
        stored = "picture.jpg"
    jpeg = to_frame_jpeg(data)
    return f"{Path(stored).stem}.jpg", jpeg


def to_frame_jpeg(data: bytes) -> bytes:
    """Letterbox a picture onto a 3840x2160 black frame."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format == "JPEG":
                image.draft("RGB", FRAME)
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            image.thumbnail(FRAME, Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", FRAME, (0, 0, 0))
            canvas.paste(
                image, ((FRAME[0] - image.width) // 2, (FRAME[1] - image.height) // 2)
            )
            output = io.BytesIO()
            canvas.save(output, "JPEG", quality=90)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as err:
        raise ValueError("Could not read that picture") from err
