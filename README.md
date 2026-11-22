# Document Screening Assistant — AI-based fake identity & travel document screening (demo prototype)

A **decision-support** tool for document officers. It reads a passport data page, validates it, shows *exactly* what it found and what it could not check, and hands the case to a human. It never accepts, refuses or accuses on its own.

> **Demo build.** All documents are **synthetic** (fictional people, ICAO test State code `UTO`, illustrated portraits, visible "DEMO - SYNTHETIC DATA" banner). No real personal data is used, scraped or stored.

Architecture and build plan: `capstone.pdf` (v1.0) in the parent folder. This repo implements its modular-monolith design with swappable interfaces.

## What works

| Area | Status in this prototype |
|---|---|
| Secure intake | Real file-signature check (extensions ignored), size/pixel/decode limits, SHA-256 of the unchanged original, random storage keys |
| Quality gate | Blur, glare, resolution, crop completeness → **recapture request** instead of unreliable results |
| Preprocessing | Document localisation, rotation/perspective rectification, separate derived image (original never modified) |
| OCR + MRZ | Zone-based OCR (RapidOCR/ONNX) with per-field value, confidence, bounding box, engine+version; **deterministic ICAO 9303 TD3 parser** with all 5 check digits; officer corrections with history |
| Validation | Versioned ruleset (`backend/rules/uto_td3_v1.json`): check digits, VIZ-vs-MRZ cross-checks, expiry/date rules, template recognition |
| Forensics (baseline) | ELA per template zone vs. a calibrated reference, heatmap, region flags — labelled **"review aid, not proof"**; marked INCONCLUSIVE on resampled captures |
| Risk | Transparent, rule-based review priority with 4 independent evidence dimensions, correlation grouping, and *unresolved* checks that never raise priority |
| Officer portal | React + TypeScript: dashboard, case queue, live pipeline progress, document viewer with evidence overlays, fields/MRZ view with correction, checks, forensics, review with rationale, PDF report, role-based redaction |
| Audit | Append-only, **hash-chained** audit log (verify button in UI) |
| Stubs (labelled) | 1:1 face verification, external registry (simulated outage demo), jobs via BackgroundTasks |

Statuses used everywhere: `PASS`, `FAIL`, `REVIEW`, `INCONCLUSIVE`, `UNAVAILABLE`, `NOT_APPLICABLE`. A missing/failed external check or low-quality input is never turned into a fraud signal.

## Quick start (Windows, no admin rights needed)

Requirements: Python 3.10+, Node 18+ (checked with Python 3.11, Node 22). Everything installs inside this folder.

```powershell
.\setup.ps1        # venv + pip install + npm install + build + calibrate + seed demo cases (one time)
.\run_demo.ps1     # starts API + UI on http://127.0.0.1:8000
```

Demo logins: `officer / officer`, `admin / admin`, `auditor / auditor` (stubbed auth; a real IdP with MFA replaces it).

Manual equivalents:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m scripts.calibrate_forensics 80      # builds rules/forensic_reference_uto_td3_v1.json
.\.venv\Scripts\python -m scripts.seed_demo --reset --all     # users + 11 demo cases
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000    # serves the built UI too
cd ..\frontend; npm install; npm run build                     # or `npm run dev` (port 5173, proxies /api)
```

Tests: `cd backend; .\.venv\Scripts\python -m pytest -q`

Reset the demo data at any time: `.\reset_demo.ps1`.

## The 5-case demo script (also in the **Demo lab** page)

1. **Clean passport** → everything passes, priority LOW, case COMPLETED.
2. **MRZ check-digit error** → deterministic FAIL on the passport-number digit (+ composite, counted once).
3. **Edited surname** → VIZ ≠ MRZ (FAIL) *and* ELA flags the edited region (REVIEW): two independent dimensions corroborate → HIGH.
4. **Blurry capture** → quality gate fails, **recapture requested**, all downstream checks INCONCLUSIVE (no unreliable results shown).
5. **Registry outage (simulated)** → every document check passes, registry shows **UNAVAILABLE**, priority stays LOW, case flagged incomplete — *not* a fraud signal.

More scenarios: edited DOB, portrait swap, stamp edit, passport-number mismatch, expired passport, glare, cropped, low resolution, photographed at an angle.

## Architecture (modular monolith — PDF §4, §8)

```
backend/app/
  api/            routes, serializers (role-based redaction)
  core/           config (env vars), security (stub auth + roles), enums
  database/       SQLAlchemy models (SQLite now, PostgreSQL later), session
  storage/        StorageBackend interface → LocalDiskStorage (S3/MinIO later)
  audit/          append-only hash-chained audit log
  modules/
    intake/       signature, size, decode, hashing, case creation
    preprocessing/ localisation, rectification, quality metrics
    classification/ template definition (UTO-TD3-v1 zones)
    ocr_mrz/      zone OCR, deterministic MRZ parser/builder, field-type correction
    validation/   versioned rules engine
    forensics/    ELA baseline
    face_verification/ 1:1 interface (stub)
    registry/     external connector interface (simulated stub)
    risk/         transparent review-priority policy
  orchestration/  run_pipeline(case_id)  ← swap BackgroundTasks for Celery here
  reporting/      PDF case report
  synthetic/      synthetic passport generator + demo samples
backend/rules/    versioned ruleset + forensic reference stats
frontend/         React + TypeScript (Vite) officer portal
model-work/       evaluation harness, datasets, model cards (see below)
data/             SQLite DB, private object storage, synthetic samples (git-ignored)
```

**Swapping to the deployment stack is configuration, not a rewrite:** `IDS_DATABASE_URL` (PostgreSQL), `IDS_STORAGE_BACKEND` (S3/MinIO implementation of `StorageBackend`), `run_pipeline` dispatch (Celery), identity provider (replace `core/security.py`).

API outline (PDF §7): `POST /api/v1/cases`, `GET /cases/{id}`, `GET /cases/{id}/results`, `POST /cases/{id}/recapture`, `POST /cases/{id}/review`, `GET /cases/{id}/report`, `GET /health` — interactive docs at `/docs`.

## Evaluation and the real-data path

`model-work/` holds an evaluation harness that reads a **configurable dataset folder** (manifest of images + labels), splits by source person / template / acquisition session so near-duplicates never cross train/test, and reports metrics with bootstrap confidence intervals and failure cases. Pointing it at authorised company data later needs no code change. See `model-work/evaluation/REPORT.md` and `model-work/model_cards/`.

## Honest limitations

- Forensics is a **baseline** (ELA vs. a template reference). It cannot prove editing; a clean result does not authenticate a document. Holograms, UV/IR, substrate and tactile features cannot be assessed from an RGB image.
- Everything was developed and measured on **synthetic documents of a single fictional template**. Performance on real documents, issuers, cameras and demographic groups is unknown until evaluated on authorised data.
- Face verification, ePassport chip/PKD verification and live registry integrations are **not implemented** (stubs, labelled).
- Not for production: demo auth, demo secret key, no malware scanning, no TLS, no encryption at rest. Hardening, PAD testing, penetration testing, privacy/legal review and a pilot process are out of scope here (PDF §10–§12) and must precede any operational use.

## Position

A **document-screening assistant with a transparent evidence trail**. Not a fraud detector. Humans make every consequential decision.
