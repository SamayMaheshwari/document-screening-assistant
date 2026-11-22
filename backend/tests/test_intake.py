import io
import warnings

import pytest
from PIL import Image

from app.core.config import Settings, get_settings
from app.modules.intake.validate import IntakeError, sniff, validate_upload


def _img(fmt: str, size=(64, 48)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 130, 140)).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _restore_pixel_limit():
    yield
    Image.MAX_IMAGE_PIXELS = get_settings().max_image_pixels


def test_sniff():
    assert sniff(_img("JPEG")) == "jpeg" and sniff(_img("PNG")) == "png"
    assert sniff(b"%PDF-1.7 x") == "pdf" and sniff(b"MZ\x90\x00") == "exe" and sniff(b"PK\x03\x04..") == "zip"
    assert sniff(b"GIF89a....") == "gif" and sniff(b"hello") is None


def test_accepts_jpeg_and_png(settings):
    j = validate_upload(_img("JPEG"), "a.jpg", settings)
    p = validate_upload(_img("PNG"), "a.png", settings)
    assert (j.kind, j.media_type, j.width, j.height) == ("jpeg", "image/jpeg", 64, 48)
    assert (p.kind, p.media_type) == ("png", "image/png")


def test_png_bytes_named_jpg_accepted_only_because_signature_is_checked(settings):
    info = validate_upload(_img("PNG"), "photo.jpg", settings)
    assert info.kind == "png" and info.media_type == "image/png"  # real type, not the claimed extension


def test_jpeg_bytes_with_odd_extension_still_judged_by_signature(settings):
    assert validate_upload(_img("JPEG"), "photo.exe", settings).kind == "jpeg"
    assert validate_upload(_img("JPEG"), "noextension", settings).kind == "jpeg"


@pytest.mark.parametrize("payload,kind", [
    (b"MZ\x90\x00\x03" + b"\x00" * 200, "exe"),
    (b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF", "pdf"),
    (b"PK\x03\x04" + b"\x00" * 100, "zip"),
    (b"GIF89a" + b"\x00" * 50, "gif"),
])
@pytest.mark.parametrize("name", ["scan.jpg", "scan.png", "scan.pdf"])
def test_non_image_types_rejected_regardless_of_extension(settings, payload, kind, name):
    with pytest.raises(IntakeError) as e:
        validate_upload(payload, name, settings)
    assert e.value.code == "type_not_allowed" and kind in e.value.message


def test_unknown_signature_rejected(settings):
    with pytest.raises(IntakeError) as e:
        validate_upload(b"just some text pretending to be a picture", "x.jpg", settings)
    assert e.value.code == "bad_signature"


def test_empty_file_rejected(settings):
    with pytest.raises(IntakeError) as e:
        validate_upload(b"", "x.jpg", settings)
    assert e.value.code == "empty"


def test_oversize_rejected(settings):
    big = b"\xff\xd8\xff" + b"\x00" * (settings.max_upload_mb * 1024 * 1024)
    with pytest.raises(IntakeError) as e:
        validate_upload(big, "x.jpg", settings)
    assert e.value.code == "too_large"


def test_corrupt_jpeg_rejected(settings):
    with pytest.raises(IntakeError) as e:
        validate_upload(b"\xff\xd8\xff\xe0" + b"garbage" * 40, "x.jpg", settings)
    assert e.value.code == "corrupt"


def test_truncated_jpeg_rejected(settings):
    data = _img("JPEG", (400, 300))
    with pytest.raises(IntakeError) as e:
        validate_upload(data[: len(data) // 2], "x.jpg", settings)
    assert e.value.code == "corrupt"


def test_png_with_bad_body_rejected(settings):
    with pytest.raises(IntakeError):
        validate_upload(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "x.png", settings)


def test_pixel_limit_enforced(settings):
    tight = Settings(max_image_pixels=2000)
    # slightly over the limit -> explicit pixel-limit rejection
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(IntakeError) as e:
            validate_upload(_img("PNG", (60, 40)), "x.png", tight)  # 2400 px > 2000
    assert e.value.code == "too_many_pixels"


def test_decompression_bomb_rejected(settings):
    tight = Settings(max_image_pixels=1000)
    # > 2x the limit makes Pillow raise DecompressionBombError at open; intake maps it to a rejection
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(IntakeError) as e:
            validate_upload(_img("PNG", (200, 200)), "bomb.png", tight)
    assert e.value.code in {"corrupt", "too_many_pixels"}


def test_within_pixel_limit_accepted(settings):
    tight = Settings(max_image_pixels=10_000)
    assert validate_upload(_img("PNG", (60, 40)), "x.png", tight).width == 60
