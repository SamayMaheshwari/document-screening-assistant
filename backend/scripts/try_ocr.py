import sys, time, json
import cv2, numpy as np
from app.synthetic.generator import make_sample, VARIANTS
from app.modules.preprocessing.rectify import locate_and_rectify, measure_quality
from app.modules.ocr_mrz.extract import extract_page
from app.modules.ocr_mrz.mrz import parse_td3, correct_by_field_type
rules = json.load(open("rules/uto_td3_v1.json"))
for v in sys.argv[1:]:
    b, lab = make_sample(v, 1001 + hash(v) % 50)
    img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    r = locate_and_rectify(img)
    print("==", v, r.method, r.card_found, r.touches_border, round(r.card_width_px), r.notes)
    for m in measure_quality(r, rules):
        print("  Q", m.name, m.value, m.status)
    if r.image is None: continue
    t = time.time()
    po = extract_page(r.image); viz = po.viz
    lines, confs = po.mrz_lines, po.mrz_conf
    print("  ocr secs", round(time.time() - t, 2))
    gt = lab["ground_truth"]
    for f in viz:
        print("   ", f.name, ascii(f.raw), round(f.confidence, 2))
    print("  MRZ", lines, [round(c, 2) for c in confs], "\n  GT ", lab["mrz"])
    l1,l2,ch = correct_by_field_type(*lines); print("  corrections", ch); p = parse_td3(l1,l2); print("  mrz ok", p.format_ok, p.all_checks_valid)
