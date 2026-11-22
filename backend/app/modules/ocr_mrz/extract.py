"""Zone-based OCR of the visual inspection zone (VIZ) and MRZ lines using RapidOCR (ONNX).

Strategy: one text-detection pass over the rectified page, boxes are assigned to template zones,
and each assigned box is re-read on a tight crop (keeps word spaces). Raw OCR text is always
preserved; normalised values are derived separately (PDF 5.2).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.modules.classification import template as T
from app.modules.ocr_mrz.mrz import normalise_mrz_text

ENGINE_NAME = "RapidOCR"
_engine = None
_lock = threading.Lock()


def engine_version() -> str:
    try:
        import importlib.metadata as m
        return m.version("rapidocr-onnxruntime")
    except Exception:
        return "unknown"


def get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR(det_limit_type="max", det_limit_side_len=1280)
    return _engine


@dataclass
class OcrField:
    name: str
    source: str  # VIZ | MRZ
    raw: str
    normalized: str | None
    confidence: float
    bbox: list[int] | None  # [x, y, w, h] in rectified px


@dataclass
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float

    @property
    def cx(self): return (self.x0 + self.x1) / 2

    @property
    def cy(self): return (self.y0 + self.y1) / 2


def detect_boxes(img: np.ndarray) -> list[_Box]:
    res, _ = get_engine()(img, use_cls=False)
    out = []
    for quad, text, conf in res or []:
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        out.append(_Box(min(xs), min(ys), max(xs), max(ys), text, float(conf)))
    return out


def _reread(img: np.ndarray, b: _Box, pad=(6, 4)) -> tuple[str, float]:
    h, w = img.shape[:2]
    crop = img[max(0, int(b.y0) - pad[1]):min(h, int(b.y1) + pad[1]), max(0, int(b.x0) - pad[0]):min(w, int(b.x1) + pad[0])]
    if crop.size == 0:
        return b.text, b.conf
    r, _ = get_engine()(crop, use_det=False, use_cls=False, use_rec=True)
    if r and r[0][0].strip():
        return r[0][0].strip(), float(r[0][1])
    return b.text, b.conf


def _rec_zone(img: np.ndarray, zone, pad=(8, 3)) -> tuple[str, float]:
    x, y, w, h = zone
    crop = img[max(0, y - pad[1]):y + h + pad[1], max(0, x - pad[0]):x + w + pad[0]]
    r, _ = get_engine()(crop, use_det=False, use_cls=False, use_rec=True)
    if r and r[0][0].strip():
        return r[0][0].strip(), float(r[0][1])
    return "", 0.0


def _in_zone(b: _Box, zone, slack=6) -> bool:
    x, y, w, h = zone
    return x - slack <= b.cx <= x + w + slack and y - slack <= b.cy <= y + h + slack


MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def parse_viz_date(raw: str) -> date | None:
    m = re.fullmatch(r"\s*(\d{1,2})\s*([A-Za-z]{3})\s*(\d{4})\s*", raw.replace(".", " ").strip())
    if not m:
        return None
    mon = MONTHS.get(m.group(2).upper())
    if not mon:
        return None
    try:
        return date(int(m.group(3)), mon, int(m.group(1)))
    except ValueError:
        return None


def normalise_viz(name: str, raw: str) -> str | None:
    t = re.sub(r"\s+", " ", raw.strip())
    if name in ("date_of_birth", "date_of_issue", "date_of_expiry"):
        d = parse_viz_date(t)
        return d.isoformat() if d else None
    if name == "passport_number":
        return re.sub(r"[^A-Z0-9]", "", t.upper())
    if name in ("sex", "document_type"):
        return t.upper()[:1] or None
    if name == "issuer_code":
        return re.sub(r"[^A-Z]", "", t.upper())[:3] or None
    return t.upper()


@dataclass
class PageOcr:
    viz: list[OcrField]
    mrz_lines: list[str]
    mrz_conf: list[float]
    mrz_boxes: list[list[int]]


def extract_page(img: np.ndarray) -> PageOcr:
    boxes = detect_boxes(img)
    viz: list[OcrField] = []
    for name, zone in T.FIELD_ZONES.items():
        mine = sorted([b for b in boxes if _in_zone(b, zone) and b.cy < 725], key=lambda b: b.x0)
        if not mine:  # detector missed a short token (e.g. a single letter): recognise the zone directly
            raw, conf = _rec_zone(img, zone)
            viz.append(OcrField(name, "VIZ", raw, normalise_viz(name, raw) if raw else None, conf, list(zone)))
            continue
        parts = [_reread(img, b) for b in mine]
        raw = " ".join(p[0] for p in parts)
        conf = float(np.mean([p[1] for p in parts]))
        bbox = [int(min(b.x0 for b in mine)), int(min(b.y0 for b in mine)),
                int(max(b.x1 for b in mine) - min(b.x0 for b in mine)), int(max(b.y1 for b in mine) - min(b.y0 for b in mine))]
        viz.append(OcrField(name, "VIZ", raw, normalise_viz(name, raw), conf, bbox))
    lines, confs, bxs = [], [], []
    for zone in T.MRZ_LINE_ZONES:
        mine = sorted([b for b in boxes if _in_zone(b, zone, slack=4)], key=lambda b: b.x0)
        if not mine:
            lines.append(""); confs.append(0.0); bxs.append(list(zone))
            continue
        parts = [_reread(img, b, pad=(8, 3)) for b in mine]
        lines.append(normalise_mrz_text("".join(p[0] for p in parts)))
        confs.append(float(np.mean([p[1] for p in parts])))
        bxs.append([int(min(b.x0 for b in mine)), int(min(b.y0 for b in mine)),
                    int(max(b.x1 for b in mine) - min(b.x0 for b in mine)), int(max(b.y1 for b in mine) - min(b.y0 for b in mine))])
    return PageOcr(viz, lines, confs, bxs)
