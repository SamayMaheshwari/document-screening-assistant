# Model card - Validation rules and review-priority policy

| | |
|---|---|
| Components | `backend/app/modules/validation/engine.py` (checks), `backend/app/modules/risk/engine.py` (priority), ruleset `backend/rules/uto_td3_v1.json` |
| Type | Deterministic, versioned, human-readable rules; **no machine learning**, no hidden scores |
| Versions | ruleset `uto-td3-rules@1.0.0`, policy `review-priority-policy@1.0.0` (also stored with every result) |

## What it does
- MRZ: structure (2 x 44 chars, charset, code `P`), five ICAO 9303 check digits.
- Cross-check: eight visual-zone fields against the MRZ (names, dates, number, sex, nationality, issuer).
- Status: expiry (EXPIRED is a *status* finding, not forgery), remaining validity, date-of-birth plausibility,
  issue-to-expiry window, template/issuer recognition.
- Priority: dimensions kept separate (integrity, consistency, status, person comparison); findings with the same root
  cause are counted once; UNAVAILABLE / INCONCLUSIVE never raise priority and are listed as unresolved; independent
  dimensions that agree are called out as corroboration; a failed quality gate gives INCOMPLETE (recapture).

## Intended use
Evidence aggregation to **order an officer's queue** and explain why. Decision support only: every outcome requires a
human review with a written rationale.

## Data and metrics
Rules are not trained. They are exercised by the unit/API test-suite (`backend/tests`) and measured on the grouped
synthetic test split: check-digit error detection recall and false-alert rate, VIZ/MRZ mismatch detection recall,
expired-document recall, end-to-end per-variant priority agreement. See `data/evaluation/results.json`, group
`metrics.validation`, and `per_variant`.

Because the rules are deterministic and the synthetic data were generated to exercise them, high agreement is expected
and is a regression check, not evidence of real-world accuracy. Real error sources are upstream (OCR confidence,
capture quality): the rules deliberately downgrade low-confidence mismatches and check-digit failures to REVIEW.

## Limitations
- Covers one fictional issuer/template. Real issuers differ (validity periods, name transliteration, personal-number
  semantics, document-number formats); each needs its own versioned ruleset with effective dates.
- Two-digit-year century inference for MRZ dates is heuristic (birth: sliding window, expiry: 2000+).
- Priority thresholds (confidence 0.80 / 0.85, validity 30 days, 10 years) are demonstration values, not operational policy.
- No watch-list, lost/stolen or registry data: the registry check is a simulation and shows UNAVAILABLE when the
  outage is simulated.
- Face comparison and ePassport chip/PKD verification are not part of the prototype.

## Subgroup / demographic caveat
Name handling is upper-case Latin only; punctuation/space normalisation was tested on a handful of patterns. Names in
other scripts, long compound names, single-name holders and unusual date conventions are not covered. The synthetic
data contain no demographic variation, so no differential-impact analysis was possible; this must be done on authorised
data before deployment.

## Ethical notes
A false FAIL burdens a traveller, a false PASS misses a problem. The design therefore (1) never turns missing or
unreadable evidence into a fraud signal, (2) records the rule version with every result, (3) keeps the officer in the
loop with correction and review audit trails, and (4) states its limitations in every report.
