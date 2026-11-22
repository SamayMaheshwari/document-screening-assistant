"""Build per-template-variant ELA reference statistics from CLEAN synthetic documents (calibration split)."""
import json, sys
from collections import defaultdict
import cv2, numpy as np
from app.synthetic.generator import make_sample
from app.modules.preprocessing.rectify import locate_and_rectify
from app.modules.forensics.ela import ela_full, zone_features, estimate_tint, REF_FILE, MODEL_VERSION
N = int(sys.argv[1]) if len(sys.argv) > 1 else 80
vals = defaultdict(lambda: defaultdict(list))
for i in range(N):
    b, lab = make_sample("clean", 5000 + i)
    img = cv2.imdecode(np.frombuffer(b, np.uint8), 1)
    r = locate_and_rectify(img); ox, oy = r.origin
    t = estimate_tint(r.image)
    for k, v in zone_features(ela_full(img)[oy:oy+880, ox:ox+1250], r.image).items():
        vals[t][k].append(v)
ref = {"model_version": MODEL_VERSION, "template": "UTO-TD3-v1", "n_reference_docs": N, "seeds": "5000..%d" % (5000+N-1),
       "tints": {t: {k: {"mean": float(np.mean(v)), "std": float(np.std(v)), "n": len(v)} for k, v in zs.items()} for t, zs in vals.items()}}
REF_FILE.write_text(json.dumps(ref, indent=2)); print({t: len(next(iter(z.values()))) for t, z in vals.items()})
