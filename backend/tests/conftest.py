"""Shared fixtures. The environment is configured BEFORE any `app` import so the real
data/app.db and data/storage are never touched (settings are cached via get_settings)."""
import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ids_tests_"))
os.environ["IDS_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["IDS_STORAGE_ROOT"] = str(_TMP / "storage")
os.environ["IDS_SYNTHETIC_DIR"] = str(_TMP / "synthetic")
os.environ["IDS_DEMO_STEP_DELAY"] = "0"

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
assert str(_TMP) in str(get_settings().storage_root), "test settings are not isolated from real data"

# 30000+ : disjoint from demo (1001-1005, 2001+), calibration (5000-5079) and the eval dataset (20000+)
TEST_SEEDS = {
    "clean": 30001, "bad_check_digit": 30002, "edited_name": 30003, "blurry": 30004, "glare": 30005,
    "cropped": 30006, "low_res": 30007, "rotated": 30008, "expired": 30009, "registry_unavailable": 30010,
}


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp():
    yield
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def rules():
    from app.modules.validation.engine import load_rules
    return load_rules()


@pytest.fixture(scope="session")
def sample():
    """sample(variant) -> (jpeg_bytes, label); cached for the whole session."""
    from app.synthetic.generator import make_sample
    cache: dict = {}

    def get(variant: str):
        if variant not in cache:
            cache[variant] = make_sample(variant, TEST_SEEDS[variant])
        return cache[variant]
    return get


@pytest.fixture(scope="session")
def analysed(sample, rules):
    """analysed(variant) -> dict(img, rect, metrics, page|None, lines, repairs, label); OCR runs once per variant."""
    from app.modules.ocr_mrz import extract as ocr
    from app.modules.ocr_mrz.mrz import correct_by_field_type
    from app.modules.preprocessing.rectify import locate_and_rectify, measure_quality
    cache: dict = {}

    def get(variant: str):
        if variant not in cache:
            data, label = sample(variant)
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            rect = locate_and_rectify(img)
            metrics = {m.name: m for m in measure_quality(rect, rules)}
            page, lines, repairs = None, None, []
            if rect.image is not None and not any(m.status == "FAIL" for m in metrics.values()):
                page = ocr.extract_page(rect.image)
                l1, l2, repairs = correct_by_field_type(*page.mrz_lines)
                lines = (l1, l2)
            cache[variant] = dict(img=img, rect=rect, metrics=metrics, page=page, lines=lines, repairs=repairs, label=label)
        return cache[variant]
    return get
