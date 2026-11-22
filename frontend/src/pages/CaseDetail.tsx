import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronRight, Clock, Copy, Download, FileText, Fingerprint, Loader2, RefreshCcw, UploadCloud } from "lucide-react";
import { api, ApiError, downloadBlob } from "../api";
import { useAuth } from "../auth";
import type { Results } from "../types";
import { CasePill, Card, PriorityBadge, Spinner, fmtDateTime, useToast } from "../ui";
import Overview from "./case/Overview";
import DocumentViewer from "./case/DocumentViewer";
import FieldsMrz from "./case/FieldsMrz";
import ChecksTab from "./case/ChecksTab";
import ForensicsTab from "./case/ForensicsTab";
import { AuditTab, ReviewTab } from "./case/ReviewTab";
import { Stepper } from "./case/Stepper";

const TABS = [
  { id: "overview", label: "Overview" }, { id: "document", label: "Document" }, { id: "fields", label: "Fields & MRZ" },
  { id: "checks", label: "Checks" }, { id: "forensics", label: "Forensics" }, { id: "review", label: "Review" }, { id: "audit", label: "Audit" },
];

export default function CaseDetail() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const [r, setR] = useState<Results | null>(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("overview");
  const [focus, setFocus] = useState<string | undefined>();
  const [recap, setRecap] = useState(false);
  const first = useRef(true);

  const load = useCallback(async () => {
    try {
      const res = await api.get<Results>(`/cases/${id}/results${first.current ? "?log=1" : ""}`);
      first.current = false;
      setR(res);
    } catch (e) { setErr(e instanceof ApiError && e.status === 404 ? "Case not found." : (e as Error).message); }
  }, [id]);

  useEffect(() => { first.current = true; setR(null); setErr(""); setTab("overview"); load(); }, [id, load]);
  const processing = r && (r.case.status === "PROCESSING" || r.case.status === "NEW");
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, 900);
    return () => clearInterval(t);
  }, [processing, load]);

  const go = (t: string, focusId?: string) => { setFocus(focusId); setTab(t); window.scrollTo({ top: 0, behavior: "smooth" }); };

  if (err) return <div className="empty card" style={{ padding: 60 }}><h4>{err}</h4><Link to="/cases" className="btn sm">Back to queue</Link></div>;
  if (!r) return <div style={{ display: "grid", placeItems: "center", height: 300 }}><Spinner size={28} /></div>;

  const c = r.case;
  const flagged = r.checks.filter(x => x.status === "FAIL" || x.status === "REVIEW").length;
  const needVerify = r.fields.filter(f => f.needs_review && !f.corrected_value).length;
  const doneSteps = r.steps.filter(s => s.status === "done" || s.status === "skipped" || s.status === "failed").length;

  const report = async () => {
    try { await downloadBlob(`/cases/${id}/report`, `${c.case_number}-report.pdf`); toast("ok", "Report generated — export recorded in the audit log"); }
    catch (e) { toast("err", (e as Error).message); }
  };

  return (
    <div className="rise">
      <div className="crumb"><Link to="/cases">Case queue</Link><ChevronRight size={13} />{c.case_number}</div>
      <div className="case-head">
        <div>
          <h1>{c.case_number}<CasePill status={c.status} />{c.priority && <PriorityBadge p={c.priority} complete={c.complete} />}</h1>
          <div className="meta-row">
            <span><FileText size={14} />{c.label || c.document_type || "Passport"}</span>
            {c.holder && <span style={{ fontWeight: 600, color: "var(--text)" }}>{c.holder}</span>}
            <span><Clock size={14} />{fmtDateTime(c.created_at)}</span>
            {r.document && <span title={r.document.sha256}><Fingerprint size={14} /><span className="mono" style={{ fontSize: 12 }}>{r.document.sha256.slice(0, 14)}…</span><Copy size={12} style={{ cursor: "pointer" }} onClick={() => { navigator.clipboard?.writeText(r.document!.sha256); toast("info", "SHA-256 copied"); }} /></span>}
            {c.capture_count > 1 && <span>{c.capture_count} captures</span>}
          </div>
        </div>
        <div className="row">
          {can("case:recapture") && !processing && <button className="btn" onClick={() => setRecap(true)}><RefreshCcw size={15} />Attach recapture</button>}
          {can("case:report") && !processing && <button className="btn primary" onClick={report}><Download size={15} />Case report (PDF)</button>}
        </div>
      </div>

      {r.pii_redacted && <div className="banner warn"><Fingerprint size={20} /><div><b>Redacted view</b><p>Your role (auditor) sees masked personal data and no document images. Audit and evidence structure remain fully visible.</p></div></div>}

      {processing ? (
        <Card><div className="proc-hero"><Loader2 size={34} className="spin" color="var(--brand)" /><h2>Screening in progress…</h2><p className="muted">Analysing {c.case_number}. The page updates automatically.</p>
          <div className="progress-line" style={{ maxWidth: 420, margin: "14px auto 6px" }}><i style={{ width: `${(doneSteps / Math.max(r.steps.length, 1)) * 100}%` }} /></div></div>
          <div style={{ maxWidth: 560, margin: "0 auto", padding: "6px 24px 24px" }}><Stepper steps={r.steps} /></div></Card>
      ) : c.status === "FAILED" ? (
        <div className="banner err"><b>Processing failed</b><p>{c.failure_reason}</p></div>
      ) : (
        <>
          <div className="tabs">
            {TABS.map(t => (
              <button key={t.id} className={`tab ${tab === t.id ? "on" : ""}`} onClick={() => go(t.id)}>{t.label}
                {t.id === "checks" && <span className={`n ${flagged ? "alert" : ""}`}>{flagged ? `${flagged} flagged` : r.checks.length}</span>}
                {t.id === "fields" && needVerify > 0 && <span className="n alert">{needVerify} to verify</span>}
                {t.id === "review" && r.reviews.length > 0 && <span className="n">{r.reviews.length}</span>}
              </button>
            ))}
          </div>
          {tab === "overview" && <Overview r={r} go={go} canRecapture={can("case:recapture")} onRecapture={() => setRecap(true)} />}
          {tab === "document" && r.document && <DocumentViewer r={r} focusId={focus} clearFocus={() => setFocus(undefined)} />}
          {tab === "fields" && <FieldsMrz r={r} canEdit={can("field:correct")} reload={load} />}
          {tab === "checks" && <ChecksTab r={r} go={go} />}
          {tab === "forensics" && r.document && <ForensicsTab r={r} />}
          {tab === "review" && <ReviewTab r={r} canReview={can("case:review")} reload={load} />}
          {tab === "audit" && <AuditTab caseId={id} />}
        </>
      )}
      {recap && <RecaptureModal caseId={id} onClose={() => setRecap(false)} onDone={() => { setRecap(false); load(); }} />}
    </div>
  );
}

function RecaptureModal({ caseId, onClose, onDone }: { caseId: string; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async () => {
    if (!file) return;
    setBusy(true); setErr("");
    const fd = new FormData(); fd.append("file", file); fd.append("rationale", why);
    try { await api.upload(`/cases/${caseId}/recapture`, fd); toast("ok", "New capture attached — re-processing. Previous capture is preserved."); onDone(); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <div className="modal-bg" onClick={() => !busy && onClose()}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>Attach a new capture</h3>
        <p className="muted" style={{ margin: "0 0 14px" }}>The earlier capture is preserved and linked. The new image goes through the full pipeline.</p>
        <label className="fl">Image (JPEG / PNG)</label>
        <label className="drop" style={{ padding: 18, display: "block" }}><UploadCloud size={20} style={{ verticalAlign: -4 }} /> {file ? file.name : "Choose a file…"}<input type="file" hidden accept="image/jpeg,image/png" onChange={e => setFile(e.target.files?.[0] || null)} /></label>
        <label className="fl" style={{ marginTop: 12 }}>Rationale (required)</label>
        <input className="input" placeholder="e.g. Original capture was blurry; document re-presented" value={why} onChange={e => setWhy(e.target.value)} />
        {err && <div className="banner err" style={{ marginTop: 12, marginBottom: 0 }}>{err}</div>}
        <div className="row" style={{ marginTop: 18, justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" disabled={busy || !file || why.trim().length < 5} onClick={submit}>{busy && <Loader2 size={14} className="spin" />}Upload & re-process</button>
        </div>
      </div>
    </div>
  );
}
