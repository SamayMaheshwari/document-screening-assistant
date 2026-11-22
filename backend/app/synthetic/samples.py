"""Demo sample catalogue: deterministic synthetic documents served to the Demo Lab."""
from __future__ import annotations

import json

from app.core.config import get_settings
from app.synthetic.generator import DEMO_SCRIPT, VARIANTS, make_sample

_SEEDS = {v: s for v, s, _ in DEMO_SCRIPT}
_FLAGS = {v: f for v, _, f in DEMO_SCRIPT}
_extra = [v for v in VARIANTS if v not in _SEEDS]
for i, v in enumerate(_extra):
    _SEEDS[v] = 2001 + i


def catalogue() -> list[dict]:
    core = {v for v, _, _ in DEMO_SCRIPT}
    out = []
    for v, spec in VARIANTS.items():
        out.append({"id": v, "title": spec["title"], "expected": spec["expect"], "seed": _SEEDS[v], "core": v in core,
                    "flags": _FLAGS.get(v, {})})
    out.sort(key=lambda x: (not x["core"], [s for s, _, _ in DEMO_SCRIPT].index(x["id"]) if x["core"] else 99))
    return out


def sample_bytes(variant: str) -> tuple[bytes, dict]:
    if variant not in VARIANTS:
        raise KeyError(variant)
    d = get_settings().synthetic_dir / "samples"
    d.mkdir(parents=True, exist_ok=True)
    img, meta = d / f"{variant}.jpg", d / f"{variant}.json"
    if not (img.exists() and meta.exists()):
        b, label = make_sample(variant, _SEEDS[variant])
        img.write_bytes(b)
        meta.write_text(json.dumps(label, indent=1))
    return img.read_bytes(), json.loads(meta.read_text())


def flags_for(variant: str) -> dict:
    return dict(_FLAGS.get(variant, {}))
