# Fine-tuning plan (not implemented - nothing is trained in this prototype)

Both pipelines read the **same configurable dataset folder** as the evaluation harness
(`--dataset DIR` or `IDS_EVAL_DATASET`), through `model-work/evaluation/dataset.py` and the leakage-free group split in
`model-work/evaluation/split.py`. Pointing at company data later needs no code change, only labels in the manifest
format (`labels.json` or one JSON per image: variant, ground_truth, mrz, tamper_regions, person_id, template_id,
session_id).

## 1. OCR recogniser fine-tune (text-line recogniser, MRZ first)
- **Why**: the pre-trained RapidOCR recogniser mis-reads look-alikes (O/0), drops filler `<` runs and is weakest on the
  short `document_type` field. The MRZ uses a fixed alphabet (A-Z, 0-9, `<`), so a constrained recogniser is realistic.
- **Data**: crop MRZ lines (`T.MRZ_LINE_ZONES`) and VIZ fields (`T.FIELD_ZONES`) from rectified pages; targets are
  `label["mrz"]` and `label["ground_truth"]` (use the *edited* text for tampered fields). Add synthetic augmentation
  (blur, JPEG, glare, perspective) plus any authorised real scans.
- **Split**: group split by person / template / session; validation carved out of train by group as well. Test split is
  touched once per experiment through `evaluate.py`.
- **Method**: start from the PaddleOCR/RapidOCR recognition model (CRNN/SVTR family), CTC loss with the MRZ alphabet
  restriction, character-level augmentation, early stopping on validation CER; export to ONNX and drop in as an
  alternative engine behind `ocr.get_engine()`.
- **Acceptance**: MRZ CER and exact-line match (raw, before check-digit normalisation) at least as good as the baseline
  with non-overlapping bootstrap CIs, no regression on VIZ exact match, per-subgroup CER reported (issuer, script,
  device) once real data exist.

## 2. Tamper-region model
- **Why**: the ELA baseline works only on unresampled JPEGs and flags whole template zones.
- **Data**: images plus `tamper_regions` boxes (zone, type, box). Negatives: all untampered captures including
  resampled/rotated and recompressed ones, so the model learns when *not* to flag.
- **Method**: small segmentation/detection network over ELA + noise-residual + RGB input (e.g. U-Net or a
  forensic-feature CNN on the rectified card), trained to output a tamper heatmap per card; region decision by thresholded
  connected components, scored with the same region precision/recall/F1 and *pixel-level* IoU (not zone IoU).
- **Safeguards**: calibrate on a held-out group split; report false-alert rate on clean documents first; keep the
  output a review aid with the same INCONCLUSIVE semantics; version the model and store the version on every finding
  (`ForensicFinding.model_version`).
- **Acceptance**: higher region F1 than the ELA baseline on resampled captures at an equal or lower clean-document false
  alert rate, with CIs, and no claim beyond the tamper types present in the data.

## Common steps
1. Ingest authorised data, write labels in the manifest format, run `evaluation/split.py` to confirm zero group leakage.
2. Run `evaluate.py --dataset ...` for the baseline and keep its `results.json` as the reference.
3. Train on the train split only; tune on the validation carve-out; evaluate once on test.
4. Write a model card (`model_cards/`), record data hash, code commit and metrics pointer, then promote behind a
   configuration flag with rollback to the baseline.
5. Data protection: real passport images only in an approved environment, retention limits, and no copies outside it.
