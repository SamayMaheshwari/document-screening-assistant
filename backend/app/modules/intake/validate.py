"""Secure intake validation (PDF 5.1): real file signature, size, decode and pixel limits."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings

SIGNATURES = {
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "pdf": (b"%PDF-",),
    "gif": (b"GIF87a", b"GIF89a"),
    "exe": (b"MZ",),
    "zip": (b"PK\x03\x04",),
}
MEDIA = {"jpeg": "image/jpeg", "png": "image/png"}


class IntakeError(Exception):
    def __init__(self, message: str, code: str = "invalid_file"):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class IntakeInfo:
    kind: str
    media_type: str
    width: int
    height: int
    size_bytes: int


def sniff(data: bytes) -> str | None:
    for kind, sigs in SIGNATURES.items():
        if any(data.startswith(s) for s in sigs):
            return kind
    return None


def validate_upload(data: bytes, filename: str, settings: Settings) -> IntakeInfo:
    if not data:
        raise IntakeError("Empty file.", "empty")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IntakeError(f"File exceeds the {settings.max_upload_mb} MB limit.", "too_large")
    kind = sniff(data)
    if kind is None:
        raise IntakeError("Unrecognised file signature; only JPEG and PNG images are accepted.", "bad_signature")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if kind not in settings.allowed_types:
        raise IntakeError(f"File type '{kind}' is not permitted (allowed: {', '.join(settings.allowed_types)}). "
                          f"Extension '.{ext}' was ignored; the actual file signature was checked.", "type_not_allowed")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels  # decompression-bomb guard
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w * h > settings.max_image_pixels:
                raise IntakeError("Image resolution exceeds the safe pixel limit.", "too_many_pixels")
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
    except IntakeError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError):
        raise IntakeError("Image is corrupt or cannot be decoded.", "corrupt")
    return IntakeInfo(kind=kind, media_type=MEDIA[kind], width=w, height=h, size_bytes=len(data))
