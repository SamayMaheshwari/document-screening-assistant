"""Generate a deterministic synthetic evaluation dataset (images + one JSON label per image + labels.json manifest).

    python model-work/datasets/generate_synthetic_dataset.py                  # ~120 documents
    python model-work/datasets/generate_synthetic_dataset.py --n 280 --out data/synthetic_dataset

Design
  * One "person" per seed (seed = 20000 + person index). All variants of a person share that seed, so a person's
    documents are near-duplicates of each other (same holder, same layout) - exactly the situation in which a
    naive random split would leak between train and test. The split therefore works on GROUPS (see
    evaluation/split.py).
  * Persons are paired into sessions (session_id) and print lots (template_id suffix `/lotNNN`), so the three
    grouping keys (person_id, template_id, session_id) all carry structure.
  * Every person gets a clean capture plus a rotating subset of the other variants, so that all variants of
    app/synthetic/generator.py VARIANTS are covered.
  * Seed range 20000+ never overlaps calibration seeds (5000-5079), demo seeds (1001-1005, 2001+) or test seeds (30000+).
  * Everything is synthetic: fictional people, ICAO test State UTO, visible DEMO watermark.

Output label format = what generator.make_sample emits (variant, ground_truth, mrz, tamper_regions, person_id,
template_id, session_id, ...) plus `doc_id` and `file`, so company data can later be dropped into the same layout.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

SEED_BASE = 20000
PERSONS_PER_SESSION = 2


def plan(n: int, per_person: int) -> list[dict]:
    from app.synthetic.generator import VARIANTS
    others = [v for v in VARIANTS if v != "clean"]
    n_persons = math.ceil(n / per_person)
    jobs: list[dict] = []
    for i in range(n_persons):
        start = (i * (per_person - 1)) % len(others)
        chosen = ["clean"] + [others[(start + j) % len(others)] for j in range(per_person - 1)]
        for v in chosen:
            jobs.append({"person_index": i, "seed": SEED_BASE + i, "variant": v,
                         "session_id": f"SES{i // PERSONS_PER_SESSION:03d}", "lot": f"lot{i // PERSONS_PER_SESSION:03d}"})
    return jobs[:n]


def _make(job: dict, out_dir: str) -> dict:
    from app.synthetic.generator import make_sample
    data, label = make_sample(job["variant"], job["seed"], session_id=job["session_id"])
    doc_id = f"doc_{job['person_index']:04d}_{job['variant']}"
    label["template_base"] = label["template_id"]
    label["template_id"] = f"{label['template_id']}/{job['lot']}"
    label["doc_id"] = doc_id
    label["file"] = f"{doc_id}.jpg"
    out = Path(out_dir)
    (out / label["file"]).write_bytes(data)
    (out / f"{doc_id}.json").write_text(json.dumps(label, indent=1), encoding="utf-8")
    return label


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=120, help="number of documents (default 120)")
    ap.add_argument("--per-person", type=int, default=6, help="documents per person: 1 clean + N-1 variants (default 6)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic_dataset")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    jobs = plan(a.n, a.per_person)
    print(f"generating {len(jobs)} documents ({len({j['person_index'] for j in jobs})} persons) into {a.out}")
    with ProcessPoolExecutor(max_workers=max(1, a.workers)) as ex:
        labels = list(ex.map(_make, jobs, [str(a.out)] * len(jobs), chunksize=4))
    manifest = {
        "dataset": {"name": "synthetic_dataset", "source": "synthetic", "generator": "backend/app/synthetic/generator.py",
                    "seed_range": [SEED_BASE, SEED_BASE + max(j["person_index"] for j in jobs)],
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "note": "Fictional people, ICAO test State UTO. No real personal data."},
        "documents": labels,
    }
    (a.out / "labels.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for l in labels:
        counts[l["variant"]] = counts.get(l["variant"], 0) + 1
    print("variants:", counts)
    print("wrote", a.out / "labels.json")


if __name__ == "__main__":
    main()
