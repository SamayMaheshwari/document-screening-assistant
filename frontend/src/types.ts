export type Status = "PASS" | "FAIL" | "REVIEW" | "INCONCLUSIVE" | "UNAVAILABLE" | "NOT_APPLICABLE";
export type CaseStatus = "NEW" | "PROCESSING" | "COMPLETED" | "REVIEW_REQUIRED" | "RECAPTURE_REQUIRED" | "FAILED" | "REVIEWED";
export type Priority = "LOW" | "MEDIUM" | "HIGH" | "INCOMPLETE";

export interface User { id: string; username: string; name: string; role: "officer" | "admin" | "auditor"; permissions: string[] }

export interface CaseSummary {
  id: string; case_number: string; status: CaseStatus; document_type: string | null; label: string | null; holder: string | null;
  capture_source: string; failure_reason: string | null; priority: Priority | null; complete: boolean | null;
  unresolved_count: number; reason_count: number; created_at: string; updated_at: string; capture_count: number; reviewed: boolean;
}

export interface Step { key: string; label: string; status: "pending" | "running" | "done" | "failed" | "skipped"; detail: string; at: string | null }

export interface QualityMetric { name: string; label: string; value: number | null; unit: string; status: Status; message: string; threshold: string }

export interface Correction { officer: string; previous: string; new: string; reason: string; at: string }
export interface Field {
  id: string; name: string; label: string; source: "VIZ" | "MRZ"; raw: string; value: string | null; corrected_value: string | null;
  confidence: number; bbox: number[] | null; needs_review: boolean; engine: string; engine_version: string; corrections: Correction[];
}

export interface Check {
  id: string; check_type: string; dimension: string; title: string; status: Status; message: string; source: string;
  rule_version: string; evidence: Record<string, any> | null; checked_at: string;
}

export interface Dimension { label: string; level: string; counts: { pass: number; fail: number; review: number; unresolved: number; not_applicable: number }; checks: string[] }
export interface Reason { check_id: string; dimension: string; status: string; text: string }
export interface Risk {
  priority: Priority; dimensions: Record<string, Dimension>; complete: boolean; reasons: Reason[]; unresolved: Reason[];
  policy_version: string; created_at: string;
}

export interface MrzInfo {
  lines: string[]; format_ok: boolean; errors: string[]; parsed: Record<string, string> | null;
  repairs: { line: number; position: number; from: string; to: string; expected: string }[];
  digit_checks: { name: string; printed: string; computed: string | null; valid: boolean }[]; confidence: number[];
}

export interface Results {
  case: CaseSummary; pii_redacted: boolean; steps: Step[]; limitations: string[];
  document: null | {
    id: string; sha256: string; media_type: string; size_bytes: number; width: number; height: number; capture_index: number;
    original_filename: string; quality: QualityMetric[]; preprocessing: Record<string, any>; has_rectified: boolean; has_heatmap: boolean; created_at: string;
  };
  documents: { id: string; capture_index: number; sha256: string; superseded: boolean; created_at: string; original_filename: string }[];
  fields: Field[]; mrz: MrzInfo | null; checks: Check[];
  forensics: null | { applicable: boolean; status: Status | null; reason: string; model_version: string; has_heatmap: boolean;
    findings: { zone: string; status: string; z: number; region: number[]; message: string }[] };
  face: null | { quality: Status; comparison: Status; message: string; model_version: string };
  risk: Risk | null;
  reviews: { id: string; officer: string; outcome: string; rationale: string; reviewed_at: string }[];
  template?: { id: string; size: number[]; photo: number[]; stamp: number[]; mrz: number[]; fields: Record<string, number[]> };
}

export interface AuditItem { seq: number; timestamp: string; actor: string; actor_role: string; action: string; case_id: string | null; request_id: string | null; metadata: Record<string, any>; hash: string }
export interface Stats { total: number; by_status: Record<string, number>; by_priority: Record<string, number>; check_status: Record<string, number>; needs_attention: number; cases_with_unresolved: number; last_24h: number }
export interface Sample { id: string; title: string; expected: string; seed: number; core: boolean; flags: Record<string, string> }
