"""Baseline image forensics: Error Level Analysis (ELA) vs. template reference statistics.

Feature: mean ELA over *background* pixels (glyph edges masked out) of each template zone, compared
with a per-template-variant reference built from clean synthetic documents. Masking text removes the
dependence on how much text a zone holds.

HONEST LIMITS: ELA is a weak, assumption-heavy indicator. It needs an unresampled capture and a
compatible JPEG history; metadata and compression traces can be stripped or forged; a clean
result does NOT authenticate a document. Output is a *review aid, not proof*. Hologram, UV, IR
and substrate features cannot be assessed from an RGB image.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.modules.classification import template as T

MODEL_VERSION = "ela-bgzone-baseline-0.2"
ELA_QUALITY = 75
REF_FILE = Path(__file__).resolve().parents[3] / "rules" / "forensic_reference_uto_td3_v1.json"
TINT_PROBE = (1120, 232, 80, 36)  # blank area used to identify the template colour variant
TINTS = {"cream": (247, 241, 226), "sky": (232, 241, 248), "sage": (234, 243, 233), "rose": (248, 236, 236)}


def ela_full(img_bgr: np.ndarray, quality: int = ELA_QUALITY) -> np.ndarray:
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, "JPEG", quality=quality, subsampling=0)
    buf.seek(0)
    re = np.asarray(Image.open(buf).convert("RGB")).astype(np.float32)
    return np.abs(rgb.astype(np.float32) - re).mean(axis=2)


def estimate_tint(card_bgr: np.ndarray) -> str | None:
    x, y, w, h = TINT_PROBE
    med = np.median(card_bgr[y:y + h, x:x + w].reshape(-1, 3), axis=0)[::-1]  # to RGB
    name, dist = min(((n, float(np.linalg.norm(med - np.array(c)))) for n, c in TINTS.items()), key=lambda t: t[1])
    return name if dist < 25 else None


def zone_features(ela_card: np.ndarray, card_bgr: np.ndarray) -> dict[str, float]:
    g = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gm = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    glyph = cv2.dilate((gm > 60).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    out = {}
    for name, (x, y, w, h) in T.FORENSIC_ZONES.items():
        patch, m = ela_card[y:y + h, x:x + w], ~glyph[y:y + h, x:x + w]
        out[name] = float(patch[m].mean()) if int(m.sum()) > 100 else float(patch.mean())
    return out


def load_reference() -> dict | None:
    return json.loads(REF_FILE.read_text()) if REF_FILE.exists() else None


@dataclass
class ZoneFinding:
    zone: str
    value: float
    ref_mean: float
    z: float
    deviation_pct: float
    status: str
    score: float
    box: list[int]
    message: str


@dataclass
class ForensicsResult:
    applicable: bool
    reason: str
    findings: list[ZoneFinding] = field(default_factory=list)
    heatmap_png: bytes | None = None
    model_version: str = MODEL_VERSION
    tint: str | None = None


def analyze(original_bgr: np.ndarray, card_bgr: np.ndarray, origin: tuple[int, int] | None, resampled: bool,
            rules: dict) -> ForensicsResult:
    ref = load_reference()
    if origin is None or resampled:
        return ForensicsResult(False, "Image was rescaled or rotated during rectification, so its JPEG compression history "
                                      "is no longer aligned. ELA is unreliable on resampled captures.")
    if ref is None:
        return ForensicsResult(False, "No calibrated reference statistics are available for this template.")
    tint = estimate_tint(card_bgr)
    if tint is None or tint not in ref["tints"]:
        return ForensicsResult(False, "This template variant has no calibrated reference set (reference sets are template-specific).")
    ox, oy = origin
    ela = ela_full(original_bgr)[oy:oy + T.CARD_H, ox:ox + T.CARD_W]
    if ela.shape != (T.CARD_H, T.CARD_W):
        return ForensicsResult(False, "Document region incomplete; ELA not computed.")
    cfg = rules["forensics"]
    feats = zone_features(ela, card_bgr)
    findings = []
    for zone, val in feats.items():
        r = ref["tints"][tint].get(zone)
        if not r:
            continue
        std = max(r["std"], 0.05 * r["mean"])
        z = (val - r["mean"]) / std
        dev = (val - r["mean"]) / max(r["mean"], 1e-6)
        flagged = abs(z) >= cfg["zscore_review"] and abs(dev) >= cfg["min_score_review"]
        direction = "lower" if z < 0 else "higher"
        msg = (f"Background error level in this region is {abs(dev) * 100:.0f}% {direction} than the template reference "
               f"(z = {z:+.1f}). This can indicate content with a different compression history, but is not proof of editing."
               if flagged else "Within the expected range for this template.")
        findings.append(ZoneFinding(zone, round(val, 3), round(r["mean"], 3), round(float(z), 2), round(float(dev * 100), 1),
                                    "REVIEW" if flagged else "PASS", round(float(min(1.0, abs(z) / 12.0)), 3),
                                    list(T.FORENSIC_ZONES[zone]), msg))
    heat = cv2.applyColorMap(np.clip(cv2.GaussianBlur(ela, (0, 0), 3) * 55, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    ok, png = cv2.imencode(".png", heat)
    return ForensicsResult(True, "ELA computed on an unresampled capture.", findings, png.tobytes() if ok else None,
                           tint=tint)
