# Demo walkthrough (about 10 minutes)

Start: `.\run_demo.ps1` → open http://127.0.0.1:8000 → sign in as **officer / officer**.
Reset to a clean state any time: `.\reset_demo.ps1` (then refresh the browser).

## 0. Framing (30 s)
> "This is a *document-screening assistant*, not a fraud detector. It reads the passport, runs checks, shows the evidence — and, importantly, shows what it could **not** check. A human makes every decision. All data here is synthetic: fictional people, test country code UTO."

Point at the orange strip: *synthetic data, decision support only.*

## 1. Dashboard (1 min)
KPIs, review-priority donut, the "needs attention" queue. Mention: priority is a prompt for human attention, never a verdict; unresolved checks never raise it.

## 2. Demo lab → run the five cases in order (6 min)
Go to **Demo lab**. Click *Screen this sample* on each; the case page shows the live pipeline.

| # | Case | What to point at |
|---|------|------------------|
| 1 | **Clean passport** | Pipeline steps animate. Everything passes → LOW, COMPLETED. Open **Document**: OCR boxes with confidence, MRZ box. Open **Fields & MRZ**: all five MRZ check digits green, VIZ-vs-MRZ table all ticks. |
| 2 | **MRZ check-digit error** | Deterministic FAIL on the passport-number digit (printed digit vs computed value). The composite digit also fails but is **counted once** (same root cause). HIGH. |
| 3 | **Edited surname** | VIZ says one surname, MRZ encodes another (FAIL). **Forensics** tab: ELA flags the surname region (REVIEW, "review aid, not proof"). Overview says two independent dimensions corroborate → HIGH. Click **Show** to jump to the highlighted region on the document. |
| 4 | **Blurry capture** | Quality gate fails. **Recapture requested; analysis not run** — everything downstream is INCONCLUSIVE rather than showing unreliable results. Click *Attach recapture*, upload the downloadable clean sample → the case re-processes; the old capture is preserved. |
| 5 | **Registry outage (simulated)** | All document checks pass but the registry shows **UNAVAILABLE** ("not a fraud signal"). Priority stays LOW, flagged *incomplete*, case routed for the manual procedure. |

## 3. Officer actions (1.5 min)
- **Fields & MRZ → Correct**: fix a field, give a reason; dependent checks re-run and the change is audited.
- **Review** tab: choose an outcome, write a rationale (required). Note the outcomes: no accept/refuse buttons.
- **Case report (PDF)**.

## 4. Governance (1 min)
- Sign out → sign in as **auditor**: masked personal data, no images, but full evidence structure.
- As **admin/auditor**: **Audit log** → *Hash chain intact* (each row commits to the previous row's hash).
- **Model evaluation**: metrics with confidence intervals and failure cases, on synthetic data.
- **About & limits**: statuses, principles, honest limitations, roadmap.

## Likely questions
**Is this detecting fake passports?** No. It checks structure (ICAO 9303 MRZ check digits), cross-field consistency, dates and capture quality, plus a weak baseline image indicator. It surfaces evidence for an officer.

**Why not a deep-learning tamper detector?** The plan (PDF §5.4) says start with deterministic checks and a documented baseline; train models only after dataset validation, with separate experiments for portrait/text/stamp regions. The evaluation harness and fine-tuning path are in place for when authorised real data exists.

**How good is it?** On synthetic data of one template — see *Model evaluation* page. We report confidence intervals and failure cases and state plainly that real-world performance is unknown until evaluated on authorised data.

**What about privacy?** Synthetic data only. Role-based redaction, private random-key storage, SHA-256 provenance, append-only hash-chained audit. Real data would need legal/privacy approvals first (PDF §10).

**What is stubbed?** Face verification (1:1 interface, quality gate, human fallback designed in), external registry (simulated outage), ePassport chip/PKD, jobs (BackgroundTasks → Celery by config), auth (stub → IdP). All labelled in the UI.

**How does it move to the real deployment stack?** Interfaces from day one: `StorageBackend` (LocalDisk → S3/MinIO), database URL env var (SQLite → PostgreSQL), `run_pipeline(case_id)` (BackgroundTasks → Celery), config via environment variables.

**What happens when OCR misreads?** OCR confidence is shown per field; a failing MRZ check digit with low OCR confidence is **REVIEW (possible reading error)**, not FAIL; officers can correct a field and every dependent check re-runs with a full audit record.
