"""Manifest-driven dataset loader - the 'real data path'.

Point it at any folder; no code change is needed to evaluate company data later:

    python model-work/evaluation/evaluate.py --dataset D:/company/passports
    IDS_EVAL_DATASET=D:/company/passports python model-work/evaluation/evaluate.py

Folder layout (either form):
  A) labels.json  - a list of records, or {"dataset": {...meta...}, "documents": [records]}
  B) one JSON per image with the same stem (scan_001.jpg + scan_001.json)

A record uses the format app/synthetic/generator.make_sample emits:
    variant          category used for the per-variant table (e.g. clean, edited_name, blurry ...)
    ground_truth     {field: value} as printed on the document (VIZ), field names of the UTO-TD3 template
    mrz              [line1, line2] as printed
    tamper_regions   [{"type", "zone", "box": [x, y, w, h]}] in the canonical (rectified) card frame
    person_id / template_id / session_id   grouping keys for the leakage-free split
    file             image path relative to the folder (default: <doc_id>.jpg|.jpeg|.png)
Only `file`/stem is strictly required. Missing grouping keys default to the doc id (each document its own group),
missing `variant` -> "unlabelled", missing `tamper_regions` -> []. Metrics whose labels are absent are skipped.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "data" / "synthetic_dataset"
IMAGE_EXTS = (".jpg", ".jpeg", ".png")
MANIFEST_NAMES = ("labels.json", "manifest.json")


class DatasetError(Exception):
    pass


@dataclass
class Doc:
    doc_id: str
    image_path: Path
    variant: str
    ground_truth: dict
    mrz: list
    tamper_regions: list
    person_id: str
    template_id: str
    session_id: str
    extra: dict = field(default_factory=dict)

    @property
    def group_keys(self) -> dict:
        return {"person_id": self.person_id, "template_id": self.template_id, "session_id": self.session_id}

    def read_bytes(self) -> bytes:
        return self.image_path.read_bytes()


@dataclass
class Dataset:
    root: Path
    docs: list[Doc]
    meta: dict

    @property
    def name(self) -> str:
        return self.meta.get("name") or self.root.name

    @property
    def source(self) -> str:
        return self.meta.get("source", "unknown")


def resolve_dataset_dir(arg: str | os.PathLike | None = None) -> Path:
    """CLI argument > IDS_EVAL_DATASET env var > data/synthetic_dataset."""
    return Path(arg or os.environ.get("IDS_EVAL_DATASET") or DEFAULT_DATASET).expanduser().resolve()


def _find_image(root: Path, rec: dict, doc_id: str) -> Path:
    cands = [rec["file"]] if rec.get("file") else [doc_id + e for e in IMAGE_EXTS]
    for c in cands:
        p = root / c
        if p.is_file():
            return p
    raise DatasetError(f"image for '{doc_id}' not found in {root} (tried {cands})")


def _to_doc(root: Path, rec: dict, fallback_id: str | None = None) -> Doc:
    doc_id = rec.get("doc_id") or (Path(rec["file"]).stem if rec.get("file") else fallback_id)
    if not doc_id:
        raise DatasetError(f"record without doc_id/file: {str(rec)[:120]}")
    known = {"doc_id", "file", "variant", "ground_truth", "mrz", "tamper_regions", "person_id", "template_id", "session_id"}
    return Doc(doc_id=doc_id, image_path=_find_image(root, rec, doc_id), variant=rec.get("variant") or "unlabelled",
               ground_truth=rec.get("ground_truth") or {}, mrz=list(rec.get("mrz") or []),
               tamper_regions=list(rec.get("tamper_regions") or []),
               person_id=str(rec.get("person_id") or doc_id), template_id=str(rec.get("template_id") or doc_id),
               session_id=str(rec.get("session_id") or doc_id), extra={k: v for k, v in rec.items() if k not in known})


def load_dataset(folder: str | os.PathLike | None = None) -> Dataset:
    root = resolve_dataset_dir(folder)
    if not root.is_dir():
        raise DatasetError(f"dataset folder does not exist: {root}")
    manifest = next((root / n for n in MANIFEST_NAMES if (root / n).is_file()), None)
    meta: dict = {}
    docs: list[Doc] = []
    if manifest:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            meta = data.get("dataset", {}) or {}
            records = data.get("documents")
            if records is None:
                raise DatasetError(f"{manifest.name}: expected a list or an object with a 'documents' list")
        else:
            records = data
        docs = [_to_doc(root, r) for r in records]
    else:
        for js in sorted(root.glob("*.json")):
            rec = json.loads(js.read_text(encoding="utf-8"))
            if isinstance(rec, dict) and ("ground_truth" in rec or "variant" in rec or "mrz" in rec):
                docs.append(_to_doc(root, rec, fallback_id=js.stem))
        meta = {"name": root.name}
    if not docs:
        raise DatasetError(f"no documents found in {root} (need labels.json or per-image JSON files)")
    ids = [d.doc_id for d in docs]
    if len(set(ids)) != len(ids):
        raise DatasetError("duplicate doc_id values in the manifest")
    docs.sort(key=lambda d: d.doc_id)
    return Dataset(root, docs, meta)
