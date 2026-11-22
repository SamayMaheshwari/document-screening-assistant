# Model card - OCR and MRZ extraction

| | |
|---|---|
| Component | `backend/app/modules/ocr_mrz/extract.py` (zone OCR) and `mrz.py` (ICAO 9303 TD3 parser / check digits / look-alike correction) |
| Engine | RapidOCR (ONNX Runtime) pre-trained detection + recognition models, **not fine-tuned**; version recorded per field in the database (`engine_version`) |
| Deterministic parts | MRZ parsing, check-digit arithmetic, field-type correction (O/0, I/1, B/8, S/5, Z/2, G/6 by field position), filler (`<`) run repair. No ML, no guessing of check digits |
| Version | ocr-zone-v1 (template UTO-TD3-v1); see `config.versions` in `data/evaluation/results.json` |

## Intended use
Decision support for a trained officer screening a **single passport data-page image** of the supported template
(fictional UTO TD3 in this prototype). Extracted values are shown with confidence and raw text next to the image; an
officer can correct any field and every correction is audited. Output feeds validation rules; it never decides alone.

**Not intended for:** unattended decisions, other document types/layouts/scripts, identity verification, or use on real
personal data without a formal data-protection assessment and a re-evaluation on authorised data.

## Data
- Training: none by this project (pre-trained engine used as is).
- Evaluation: synthetic documents from `backend/app/synthetic/generator.py` (illustrated portraits, fictional names, ICAO
  test State UTO), seeds 20000+, grouped split (person / template / session) so variants of one source never cross the
  split. Only captures that pass the quality gate are scored for OCR.

## Metrics
All numbers, 95% bootstrap CIs and sample sizes live in `data/evaluation/results.json` (group `metrics.ocr`) and are
rendered in `model-work/evaluation/REPORT.md`: per-field VIZ exact match, MRZ character error rate (raw and after
normalisation), MRZ exact-line match and MRZ parse success. Weak spots visible in the report: (1) the raw MRZ
output has a CER of roughly 10% because the recogniser drops '<' filler runs and confuses O/0 - the deterministic
normalisation brings it to near zero; (2) `place_of_birth` loses the space between words ("LAKEVERDANT"), which is not
used by any validation rule; (3) one holder's MRZ date of birth was read with a dropped digit, which the filler
repair pads back to 44 characters, so fields shift and the VIZ/MRZ cross-check raises a confident false mismatch
(end-to-end priority HIGH instead of MEDIUM for three variants of that holder). This is a documented limitation of the
repair step, not hidden: the officer sees the MRZ crop and can correct the line.

## Limitations
- One font family, clean rendering, one layout: OCR accuracy on real passports (security printing, guilloche overprint,
  holograms, laminate glare, different fonts such as OCR-B) is **unknown** and expected to be lower.
- Zone-based reading assumes the page was rectified to the template frame; unsupported layouts yield nothing useful.
- Look-alike correction can mask a genuine OCR error only if the corrected text still passes the check digits; a wrong
  check digit is never repaired, so errors surface as REVIEW (low confidence) or FAIL (high confidence).
- Non-Latin names/transliteration are not covered.

## Subgroup / demographic caveat
The evaluation data have **no demographic coverage**: names come from a fixed list of 20 surnames and 16 given-name
pairs, portraits are illustrations, there is no variation in script, name length distribution, skin tone or age
representation in photographs. No subgroup performance claim can be made. Before any real use, error rates must be
measured per nationality/script/issuer and per capture device.

## Ethical notes
Passport images contain sensitive personal data. This prototype uses synthetic data only. Auditor role views are
redacted; originals are stored unchanged with a SHA-256 hash; all views/corrections are audit-logged in a hash chain.
Wrong OCR can create false mismatches for a traveller; therefore low-confidence mismatches are REVIEW, not FAIL, and
the officer always sees the image.
