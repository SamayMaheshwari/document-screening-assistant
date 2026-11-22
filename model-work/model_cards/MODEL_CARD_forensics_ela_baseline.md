# Model card - Forensics: ELA baseline (`ela-bgzone-baseline-0.2`)

| | |
|---|---|
| Component | `backend/app/modules/forensics/ela.py`, reference statistics `backend/rules/forensic_reference_uto_td3_v1.json` |
| Type | Statistical baseline, **not a learned model**: Error Level Analysis (JPEG re-save at q=75) on background pixels (glyph edges masked) per template zone, compared with per-template-colour-variant reference mean/std; flag when \|z\| >= 3.5 and relative deviation >= 25% |
| Calibration | Reference built from clean synthetic documents, seeds 5000-5079 (`backend/scripts/calibrate_forensics.py`) |
| Version | ela-bgzone-baseline-0.2 |

## Intended use
A **review aid**: highlights template zones whose compression/error-level profile differs from clean documents of the
same template so an officer knows where to look. Output is REVIEW / PASS / INCONCLUSIVE and a heatmap. It is never
proof of tampering and a PASS never authenticates a document.

**Not intended for:** automated rejection, evidence of forgery, non-template documents, screenshots, or captures that
were resampled.

## When it does not apply (reported as INCONCLUSIVE, never as a fraud signal)
Rectification that resamples (rotation, scaling, perspective warp) destroys the JPEG block alignment, as does a
template colour variant without reference statistics. The evaluation reports the "not applicable" fraction.

## Data
- Calibration: synthetic clean documents (seeds 5000-5079). Evaluation: synthetic grouped test split from seeds 20000+,
  tamper operations text redraw (surname, date of birth, passport number), portrait paste and stamp redraw, each with a
  deliberate foreign JPEG history (the simulated "pasted from another source").

## Metrics
See `data/evaluation/results.json`, group `metrics.forensics`: region-level precision / recall / F1 over (document,
zone) pairs, document-level tamper detection recall and clean-document false alert rate, localisation IoU, and the
not-applicable fraction. CIs are bootstrap over documents.

Honest reading: results on this synthetic data are strong because the simulated tampering leaves exactly the trace the
method looks for. Localisation IoU is near 1 **by construction** (forensic zones coincide with the generator's edit
boxes). Neither number transfers to real forgeries.

## Limitations
- Detects only a mismatch of JPEG history; a forger who edits and re-saves the whole image once, or prints and
  re-photographs, leaves no such trace. Metadata and compression traces can be stripped or forged.
- Cannot assess holograms, UV/IR, substrate, tactile or chip security features from an RGB image.
- Reference statistics are template- and tint-specific; a new template needs its own calibration set.
- Whole-zone localisation only; no pixel-level tamper map.

## Subgroup / demographic caveat
Synthetic portraits are illustrations; there is no photographic or demographic coverage, so portrait-region behaviour
on real faces, skin tones, lighting or photo printing processes is untested. No fairness claim is made.

## Ethical notes
A false forensic flag can delay a traveller; wording in the UI states "review aid, not proof", a forensic flag on its own yields at most MEDIUM priority (HIGH
needs a deterministic FAIL in the integrity or consistency dimension), and the officer makes the decision.
