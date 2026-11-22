# Document Screening Assistant — User Manual (demo prototype)

> **Demo build.** All documents are synthetic: fictional people, the ICAO test State code `UTO`, illustrated portraits, and a visible "DEMO - SYNTHETIC DATA" banner. Do not upload real people's documents.

## 1. What this is (and is not)

A **document-screening assistant with a transparent evidence trail** for passport data pages. It:

1. accepts a document image safely,
2. checks capture quality,
3. reads the printed fields and the machine-readable zone (MRZ),
4. validates them against ICAO 9303 rules and against each other,
5. runs a weak baseline image-integrity check,
6. shows every check with its evidence, and everything it could **not** check,
7. hands the case to an officer, who records a decision and rationale.

It is **not** a fraud detector. It never accepts, refuses or accuses on its own. A review priority is a prompt for human attention, not a verdict.

## 2. Starting the system

```powershell
.\setup.ps1      # one time: installs everything inside this folder, builds the UI, seeds demo data
.\run_demo.ps1   # starts the app at http://127.0.0.1:8000
.\reset_demo.ps1 # restore the 11 seeded demo cases at any time
```

## 3. Roles and sign-in

| Account | Role | Can do |
|---|---|---|
| `officer / officer` | Officer | Create cases, view images, correct fields, attach recaptures, record reviews, export reports |
| `admin / admin` | Admin | View cases, reports and the audit log. Cannot record reviews |
| `auditor / auditor` | Auditor | View evidence structure and the audit log with **masked personal data and no document images** |

Login is a stub for the demo. A real deployment would use an identity provider with MFA.

## 4. Screen-by-screen guide

### Dashboard
Totals, cases awaiting review, recapture requests, a review-priority chart, an outcome breakdown of all checks, the "needs attention" queue and recent activity.

### Case queue
All cases, newest first. Filter by status or priority, or search by case number. Statuses:

| Status | Meaning |
|---|---|
| Processing | Pipeline running; the page updates live |
| Completed | Everything passed, nothing unresolved |
| Review required | Findings or unresolved checks need an officer |
| Recapture required | Capture quality too low; no unreliable results were generated |
| Reviewed | An officer has recorded a decision |
| Failed | Technical error (reason shown) |

### New screening
Drag in a JPEG/PNG (up to 12 MB). The real file signature is checked (the extension is ignored), size and pixel limits are enforced, and a SHA-256 of the unchanged original is stored. Rejected files show the exact reason.

### Demo lab
Fourteen synthetic passports. The first five form the demo script. Click **Screen this sample**, or download a sample to test the upload page.

### Case page
Header: case number, status, priority, holder, time, SHA-256. Buttons: **Attach recapture** and **Case report (PDF)**. Tabs:

- **Overview**: review priority, four evidence dimensions (document integrity, information consistency, document status, person-to-document comparison), the evidence behind the priority, checks that could not be verified, a document preview with flagged regions, capture quality, and the processing pipeline.
- **Document**: the rectified image with toggleable overlays: OCR fields (amber = low confidence), MRZ, flagged regions, ELA heatmap. Zoom, hover for details, click a flag to inspect it. You can switch to the original image.
- **Fields & MRZ**: the MRZ with per-character check-digit colouring (green valid, red invalid, dashed = OCR normalisation applied), the five check digits, a visual-zone vs MRZ table, and all OCR fields with raw text, confidence and engine. **Correct** lets an officer fix a value with a required reason.
- **Checks**: every check grouped by dimension with status, message, source, ruleset version and time. Filter by status. **On document** jumps to the region.
- **Forensics**: z-score bars per region against the template reference, the ELA heatmap and the limitations. Marked "review aid, not proof".
- **Review**: record an outcome and a rationale (at least 10 characters). History is shown alongside.
- **Audit**: this case's hash-chained event trail.

### Audit log (admin, auditor)
Every login, view, upload, correction, review and export. The banner shows whether the hash chain is intact; each row commits to the previous row's hash.

### Model evaluation
Metrics on a synthetic test set with confidence intervals and failure cases (280 synthetic documents, 84 in the held-out test split; regenerate with the harness in `model-work/evaluation`).

### About & limits
Statuses, principles, limitations and the roadmap to a pilot.

## 5. How to read results

### Check statuses
| Status | Meaning |
|---|---|
| **PASS** | Check completed; no configured issue found |
| **FAIL** | A deterministic rule failed (for example a check digit does not match, or the document has expired) |
| **REVIEW** | A discrepancy or anomaly needs a human, or a failure may be an OCR misread |
| **INCONCLUSIVE** | Quality or model limits prevent a reliable result |
| **UNAVAILABLE** | An external service did not respond. **Not a fraud signal** |
| **NOT_APPLICABLE** | The check does not apply (for example no live face capture in this demo) |

### Review priority
- **High**: a deterministic failure in integrity or consistency (for example a VIZ/MRZ mismatch, or a bad check digit).
- **Medium**: a review-aid flag or a status issue (for example expired).
- **Low**: nothing raised.
- **Not assessed**: capture quality was insufficient; recapture first.
- Unresolved checks never raise priority. They show as an **incomplete** tag and are listed under "Could not be verified".
- Findings with the same root cause count once.

## 6. Typical officer workflow

1. **New screening**, or screen a demo sample. Watch the pipeline.
2. If the status is *Recapture required*, use **Attach recapture** with a new image and a rationale. The old capture is kept and linked.
3. Open **Overview**. Read the evidence behind the priority and the unresolved items.
4. Use **Show** or the **Document** tab to look at flagged regions on the image.
5. In **Fields & MRZ**, check fields marked "verify" and correct any OCR misreads. Dependent checks re-run and the change is audited.
6. Record the decision in **Review**.
7. Export the **Case report (PDF)**. The export is recorded in the audit log.

## 7. The five demo cases

| # | Case | What it shows |
|---|---|---|
| 1 | Clean passport | Full happy path: all checks pass, priority Low, Completed |
| 2 | MRZ check-digit error | Deterministic FAIL; the composite digit counts once |
| 3 | Edited surname | VIZ vs MRZ mismatch plus an ELA region flag; two dimensions corroborate, so High |
| 4 | Blurry capture | Quality gate fails; recapture requested; downstream checks INCONCLUSIVE |
| 5 | Registry outage (simulated) | Document checks pass; registry UNAVAILABLE; priority Low but incomplete |

Extra scenarios: edited date of birth, portrait swap, stamp edit, passport-number mismatch, expired passport, glare, cropped capture, low resolution, photographed at an angle.

## 8. How it works inside

1. **Intake**: signature, size, decode and pixel checks. The original is stored unchanged under a random key with its SHA-256.
2. **Preprocessing**: locate the document, rotate/rectify it to a standard frame (a separate derived image), then measure blur, glare, resolution and crop.
3. **Quality gate**: poor captures stop here with a recapture request.
4. **OCR + MRZ**: zone-based OCR (RapidOCR) gives per-field value, confidence, box and engine version. The MRZ parser is deterministic ICAO 9303 TD3 code with all five check digits. OCR look-alike confusions (O/0, I/1…) are corrected by field type, and every change is recorded. A wrong check digit is never "fixed".
5. **Validation**: a versioned ruleset (`backend/rules/uto_td3_v1.json`) drives check digits, VIZ/MRZ cross-checks, date rules and template recognition. A failing digit read with low OCR confidence is REVIEW, not FAIL.
6. **Forensics (baseline)**: error-level analysis per zone, compared with a reference built from clean synthetic documents. It is marked INCONCLUSIVE on rotated or rescaled captures, because those captures lose their compression history.
7. **Face and registry**: stubs, labelled in the UI.
8. **Risk**: a transparent rule-based policy (`review-priority-policy@1.0.0`).
9. **Officer review**: decision plus rationale, a PDF report, and an append-only hash-chained audit log.

## 9. Limitations

- Forensics is a weak baseline. It cannot prove editing, and a clean result does not authenticate a document. Holograms, UV/IR and substrate features cannot be assessed from an RGB image.
- Results come from synthetic documents of one fictional template. Performance on real documents, issuers, cameras and demographic groups is unknown until evaluated on authorised data.
- Face verification, ePassport chip/PKD checks and live registry integrations are not implemented.
- Not production-ready: demo login and secret key, no TLS, no malware scanning, no encryption at rest.

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| Blank page or "Frontend not built" | Run `.\setup.ps1`, or `cd frontend; npm run build` |
| Port 8000 busy | Stop the other server, or edit the port in `run_demo.ps1` |
| Demo data looks changed | `.\reset_demo.ps1`, then refresh the browser |
| Upload rejected | The message states the reason: type, size, corrupt file or too many pixels |
| First screening is slow | The OCR model loads on first use (a few seconds) |
