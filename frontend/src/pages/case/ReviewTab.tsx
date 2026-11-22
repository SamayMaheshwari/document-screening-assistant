import { useEffect, useState } from "react";
import { ClipboardCheck, History, Lock, ScrollText, Send } from "lucide-react";
import { api } from "../../api";
import type { AuditItem, Results } from "../../types";
import { Card, fmtDateTime, useToast } from "../../ui";

const OUTCOMES: { id: string; title: string; text: string }[] = [
  { id: "NO_ISSUES_FOUND", title: "No issues found", text: "Routine processing. Evidence reviewed; nothing requires further action." },
  { id: "REFER_SECONDARY", title: "Refer to secondary examination", text: "Findings need a closer look by a second officer or specialist equipment." },
  { id: "RECAPTURE_REQUESTED", title: "Request recapture", text: "Capture quality or an unresolved check means the document should be re-presented." },
  { id: "ESCALATE_SUPERVISOR", title: "Escalate to supervisor", text: "Serious or unclear evidence that needs supervisory decision." },
];

export function ReviewTab({ r, canReview, reload }: { r: Results; canReview: boolean; reload: () => void }) {
  const toast = useToast();
  const [outcome, setOutcome] = useState("");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try { await api.post(`/cases/${r.case.id}/review`, { outcome, rationale: why }); toast("ok", "Review recorded and written to the audit log"); setOutcome(""); setWhy(""); reload(); }
    catch (e: any) { toast("err", e.message); } finally { setBusy(false); }
  };
  const open = r.risk?.reasons.filter(x => x.status !== "INFO").length ?? 0;
  return (
    <div className="grid g-main">
      <Card title="Officer decision" icon={<ClipboardCheck size={16} />}>
        <div className="banner info" style={{ marginBottom: 16 }}><Lock size={18} /><div><b>Human decision required</b><p>The system never accepts, refuses or accuses. Record your assessment and rationale; both are retained in the case record and audit trail.</p></div></div>
        {!canReview ? <p className="muted">Your role ({"read-only"}) cannot record reviews. Officers can record a decision here.</p> : (
          <>
            <div className="outcomes">
              {OUTCOMES.map(o => (
                <button key={o.id} className={`outcome ${outcome === o.id ? "on" : ""}`} onClick={() => setOutcome(o.id)}>
                  <input type="radio" checked={outcome === o.id} readOnly style={{ marginTop: 4 }} /><div><b>{o.title}</b><small>{o.text}</small></div>
                </button>
              ))}
            </div>
            <label className="fl" style={{ marginTop: 16 }}>Rationale (required, at least 10 characters)</label>
            <textarea rows={4} placeholder={open ? `Summarise what you examined and why you chose this outcome. (${open} finding(s) were raised by the system.)` : "Summarise what you examined and why you chose this outcome."} value={why} onChange={e => setWhy(e.target.value)} />
            <div className="row" style={{ justifyContent: "space-between", marginTop: 14 }}>
              <span className="muted" style={{ fontSize: 12.5 }}>{why.trim().length}/10 characters minimum</span>
              <button className="btn primary" disabled={busy || !outcome || why.trim().length < 10} onClick={submit}><Send size={15} />Record review</button>
            </div>
          </>
        )}
      </Card>
      <Card title="Review history" icon={<History size={16} />}>
        {r.reviews.length === 0 ? <p className="muted" style={{ margin: 0 }}>No review recorded yet.</p> : (
          <div className="timeline">{[...r.reviews].reverse().map(v => <div className="tl" key={v.id}><b>{v.outcome.replace(/_/g, " ").toLowerCase().replace(/^./, c => c.toUpperCase())}</b><small>{v.officer} · {fmtDateTime(v.reviewed_at)}</small><div style={{ marginTop: 4 }}>{v.rationale}</div></div>)}</div>
        )}
      </Card>
    </div>
  );
}

export function AuditTab({ caseId }: { caseId: string }) {
  const [items, setItems] = useState<AuditItem[] | null>(null);
  useEffect(() => { api.get<{ items: AuditItem[] }>(`/cases/${caseId}/audit`).then(r => setItems(r.items)).catch(() => setItems([])); }, [caseId]);
  return (
    <Card title="Audit trail for this case" icon={<ScrollText size={16} />} right={<span className="muted" style={{ fontSize: 12.5 }}>append-only · hash-chained</span>}>
      {!items ? <p className="muted">Loading…</p> : items.length === 0 ? <p className="muted">No events.</p> : (
        <div className="timeline">{items.map(a => (
          <div className="tl" key={a.seq}><b>{a.action}</b><small>{a.actor} ({a.actor_role}) · {fmtDateTime(a.timestamp)}</small>
            {Object.keys(a.metadata || {}).length > 0 && <div className="meta">{JSON.stringify(a.metadata).slice(0, 220)}</div>}<div className="meta">#{a.seq} · hash {a.hash}…</div></div>
        ))}</div>
      )}
    </Card>
  );
}
