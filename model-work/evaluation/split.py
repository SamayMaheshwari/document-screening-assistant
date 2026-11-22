"""Leakage-free train/test split.

Documents are linked when they share a person_id, a template_id OR a session_id; the connected components of that
graph are the GROUPS. A whole group goes to one side, so near-duplicate variants of the same source (same holder,
same print lot, same capture session) can never straddle train and test, even through chains (A~B by person,
B~C by session => A, B, C stay together).

    python model-work/evaluation/split.py [--dataset DIR] [--test-frac 0.3] [--seed 7]
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict

DEFAULT_KEYS = ("person_id", "template_id", "session_id")


class _UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def _keys_of(doc) -> dict:
    return doc.group_keys if hasattr(doc, "group_keys") else doc


def connected_groups(docs, keys=DEFAULT_KEYS) -> list[list]:
    """Connected components over shared key values. `docs` are Doc objects or dicts with `doc_id` + key fields."""
    ids = [d.doc_id if hasattr(d, "doc_id") else d["doc_id"] for d in docs]
    uf = _UF(ids)
    seen: dict[tuple, str] = {}
    for d, i in zip(docs, ids):
        k = _keys_of(d)
        for key in keys:
            v = k.get(key)
            if v in (None, ""):
                continue
            if (key, v) in seen:
                uf.union(i, seen[(key, v)])
            else:
                seen[(key, v)] = i
    comp: dict[str, list] = defaultdict(list)
    for d, i in zip(docs, ids):
        comp[uf.find(i)].append(d)
    return sorted(comp.values(), key=lambda g: min(x.doc_id if hasattr(x, "doc_id") else x["doc_id"] for x in g))


def group_split(docs, test_frac: float = 0.30, seed: int = 7, keys=DEFAULT_KEYS):
    """Seeded split by group. Returns (train_docs, test_docs). Deterministic for the same input and seed."""
    groups = connected_groups(docs, keys)
    order = list(range(len(groups)))
    random.Random(seed).shuffle(order)
    target = test_frac * len(docs)
    test, train = [], []
    for gi in order:
        g = groups[gi]
        if len(test) + len(g) / 2 < target:  # greedy: take the group while its midpoint stays under the target
            test.extend(g)
        else:
            train.extend(g)
    key = lambda d: d.doc_id if hasattr(d, "doc_id") else d["doc_id"]
    return sorted(train, key=key), sorted(test, key=key)


def check_no_leak(train, test, keys=DEFAULT_KEYS) -> dict:
    """Return {key: sorted shared values} - every list must be empty for a leak-free split."""
    leaks = {}
    for key in keys:
        a = {_keys_of(d).get(key) for d in train} - {None, ""}
        b = {_keys_of(d).get(key) for d in test} - {None, ""}
        leaks[key] = sorted(a & b)
    return leaks


def main() -> None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from evaluation.dataset import load_dataset
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset")
    ap.add_argument("--test-frac", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    ds = load_dataset(a.dataset)
    tr, te = group_split(ds.docs, a.test_frac, a.seed)
    leaks = check_no_leak(tr, te)
    print(f"{len(ds.docs)} docs in {len(connected_groups(ds.docs))} groups -> train {len(tr)} / test {len(te)}; leaks: {leaks}")


if __name__ == "__main__":
    main()
