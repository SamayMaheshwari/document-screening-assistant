"""Preprocessing: locate the document, rectify to the canonical frame, measure quality.

Originals are never modified; this produces a separate derived image (PDF 5.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.enums import Status
from app.modules.classification import template as T


@dataclass
class QualityMetric:
    name: str
    label: str
    value: float | None
    unit: str
    status: str
    message: str
    threshold: str = ""


@dataclass
class Rectified:
    image: np.ndarray | None  # BGR, canonical size
    method: str  # crop | warp | resize | none
    card_found: bool
    touches_border: bool
    card_width_px: float
    angle_deg: float
    origin: tuple[int, int] | None
    resampled: bool
    quad: list[list[float]] | None
    notes: list[str] = field(default_factory=list)


def _order_points(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def locate_and_rectify(img: np.ndarray) -> Rectified:
    h, w = img.shape[:2]
    # estimate the surface colour from the darkest image corners (document is brighter than the desk)
    k = max(8, min(h, w) // 40)
    corners = [img[:k, :k], img[:k, -k:], img[-k:, :k], img[-k:, -k:]]
    meds = sorted((np.median(c.reshape(-1, 3), axis=0) for c in corners), key=lambda m: float(m.sum()))
    bg = np.mean(meds[:2], axis=0)
    sm = cv2.GaussianBlur(img, (7, 7), 0).astype(np.int16)
    delta = sm - bg[None, None, :]
    diff = np.abs(delta).sum(axis=2)
    darker = np.all(delta < -6, axis=2)  # cast shadow / darker surface: not part of the document
    mask = ((diff > 45) & ~darker).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return Rectified(None, "none", False, False, 0, 0, None, False, None, ["No document-like region found."])
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.15 * w * h:
        return Rectified(None, "none", False, False, 0, 0, None, False, None, ["Document region too small in frame."])
    x, y, bw, bh = cv2.boundingRect(c)
    touches = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
    rect = cv2.minAreaRect(c)
    (cx, cy), (rw, rh), ang = rect
    long_side, short_side = max(rw, rh), min(rw, rh)
    tilt = abs(((ang + 45) % 90) - 45)  # distance from axis-aligned
    notes: list[str] = []

    # full-frame scan (card fills image): accept without border penalty if aspect is right
    if touches and abs(bw / max(bh, 1) - T.CARD_W / T.CARD_H) < 0.08 and bw > 0.95 * w and bh > 0.95 * h:
        touches = False
        notes.append("Document fills the frame (flat scan).")

    if touches:
        return Rectified(None, "none", True, True, float(long_side), float(tilt), (x, y), False, None,
                         ["Document is cut off by the image border (incomplete capture)."])

    if tilt < 0.6 and abs(bw - T.CARD_W) <= 6:  # same scale, axis-aligned -> pure crop, no resampling
        ox = int(round(x / 8) * 8) if abs(x - round(x / 8) * 8) <= 2 else x
        oy = int(round(y / 8) * 8) if abs(y - round(y / 8) * 8) <= 2 else y
        crop = img[oy:oy + T.CARD_H, ox:ox + T.CARD_W]
        if crop.shape[0] == T.CARD_H and crop.shape[1] == T.CARD_W:
            return Rectified(crop.copy(), "crop", True, False, float(bw), float(tilt), (ox, oy), False,
                             [[ox, oy], [ox + T.CARD_W, oy], [ox + T.CARD_W, oy + T.CARD_H], [ox, oy + T.CARD_H]], notes)
    box = cv2.boxPoints(rect)
    quad = _order_points(box)
    wd = np.linalg.norm(quad[1] - quad[0])
    ht = np.linalg.norm(quad[3] - quad[0])
    if ht > wd:  # card captured portrait: rotate quad so long edge is the width
        quad = np.roll(quad, -1, axis=0)
    dst = np.array([[0, 0], [T.CARD_W - 1, 0], [T.CARD_W - 1, T.CARD_H - 1], [0, T.CARD_H - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad, dst)
    out = cv2.warpPerspective(img, M, (T.CARD_W, T.CARD_H), flags=cv2.INTER_CUBIC)
    method = "resize" if tilt < 0.6 else "warp"
    notes.append("Image was rescaled or rotated to the canonical frame (resampled).")
    return Rectified(out, method, True, False, float(long_side), float(tilt), None, True, quad.tolist(), notes)


def rotate_180(r: Rectified) -> Rectified:
    r.image = cv2.rotate(r.image, cv2.ROTATE_180)
    r.resampled = True
    r.notes.append("Document was upside-down; rotated 180 degrees.")
    return r


def measure_quality(r: Rectified, rules: dict) -> list[QualityMetric]:
    q = rules["quality"]
    out: list[QualityMetric] = []

    # crop completeness
    if not r.card_found:
        out.append(QualityMetric("crop", "Document fully in frame", None, "", Status.INCONCLUSIVE.value,
                                 "No document found in the image.", ""))
    elif r.touches_border:
        out.append(QualityMetric("crop", "Document fully in frame", None, "", Status.FAIL.value,
                                 "Document edge is cut off by the frame; part of the page (e.g. MRZ) may be missing.", "all four edges inside frame"))
    else:
        out.append(QualityMetric("crop", "Document fully in frame", None, "", Status.PASS.value,
                                 "All document edges are inside the frame.", "all four edges inside frame"))

    # resolution
    wpx = r.card_width_px
    if wpx <= 0:
        out.append(QualityMetric("resolution", "Resolution", None, "px", Status.INCONCLUSIVE.value, "Could not measure.", ""))
    else:
        s = Status.PASS if wpx >= q["min_card_width_px_review"] else (Status.REVIEW if wpx >= q["min_card_width_px_fail"] else Status.FAIL)
        msg = {"PASS": "Resolution is sufficient for OCR.", "REVIEW": "Resolution is marginal; OCR confidence may be reduced.",
               "FAIL": "Resolution is too low for reliable OCR."}[s.value]
        out.append(QualityMetric("resolution", "Resolution (document width)", round(wpx), "px", s.value, msg,
                                 f">= {q['min_card_width_px_review']} px"))

    if r.image is None:
        for n, lbl in (("blur", "Sharpness"), ("glare", "Glare")):
            out.append(QualityMetric(n, lbl, None, "", Status.INCONCLUSIVE.value, "Not measured (document not fully visible).", ""))
        return out

    gray = cv2.cvtColor(r.image, cv2.COLOR_BGR2GRAY)
    lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    s = Status.PASS if lap >= q["blur_laplacian_review"] else (Status.REVIEW if lap >= q["blur_laplacian_fail"] else Status.FAIL)
    msg = {"PASS": "Text edges are sharp.", "REVIEW": "Slightly soft; consider recapture.", "FAIL": "Image is too blurry for reliable reading."}[s.value]
    out.append(QualityMetric("blur", "Sharpness (Laplacian variance)", round(lap, 1), "", s.value, msg, f">= {q['blur_laplacian_review']}"))

    body = r.image[:728]  # exclude white MRZ band
    sat = float(np.mean(np.min(body, axis=2) >= 253))
    s = Status.PASS if sat < q["glare_fraction_review"] else (Status.REVIEW if sat < q["glare_fraction_fail"] else Status.FAIL)
    msg = {"PASS": "No significant glare.", "REVIEW": "Some glare present; check covered areas.", "FAIL": "Heavy glare obscures the document."}[s.value]
    out.append(QualityMetric("glare", "Glare (saturated area)", round(sat * 100, 2), "%", s.value, msg, f"< {q['glare_fraction_review'] * 100:.1f}%"))
    return out
