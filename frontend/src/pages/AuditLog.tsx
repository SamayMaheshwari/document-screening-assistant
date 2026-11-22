import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Link2, ScrollText, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../api";
import type { AuditItem } from "../types";
import { Card, Spinner, fmtDateTime } from "../ui";

export default function AuditLog() {
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState("");
  const [chain, setChain] = useState<{ valid: boolean; checked: number } | null>(null);
  const load = () => api.get<{ items: AuditItem[]; total: number }>(`/audit?limit=300${filter ? `&action=${encodeURIComponent(filter)}` : ""}`).then(r => { setItems(r.items); setTotal(r.total); });
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [filter]);
  useEffect(() => { api.get<{ valid: boolean; checked: number }>("/audit/verify").then(setChain); }, [total]);
  const groups = ["", "auth", "case", "image", "field", "review", "report", "pipeline", "intake"];

  return (
    <div className="rise">
      <div className="page-h"><div><h1>Audit log</h1><p>Append-only record of every login, view, upload, edit, review and export. Each row commits to the hash of the previous row, so after-the-fact changes are detectable.</p></div>
        {chain && <div className={`banner ${chain.valid ? "info" : "err"}`} style={{ margin: 0, alignItems: "center" }}>{chain.valid ? <ShieldCheck size={22} /> : <ShieldX size={22} />}<div><b>{chain.valid ? "Hash chain intact" : "Chain broken!"}</b><p>{chain.checked} events verified</p></div></div>}
      </div>
      <Card pad={false}>
        <div style={{ padding: 14, borderBottom: "1px solid var(--line)" }}><div className="seg" style={{ flexWrap: "wrap" }}>{groups.map(g => <button key={g} className={filter === g ? "on" : ""} onClick={() => setFilter(g)}>{g === "" ? "All events" : g}</button>)}</div></div>
        {!items ? <div style={{ padding: 40, textAlign: "center" }}><Spinner /></div> : (
          <table className="t"><thead><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Case</th><th>Detail</th><th><Link2 size={13} style={{ verticalAlign: -2 }} /> Hash</th></tr></thead><tbody>
            {items.map(a => (
              <tr key={a.seq}>
                <td className="cell-sub mono">{a.seq}</td><td className="cell-sub" style={{ whiteSpace: "nowrap" }}>{fmtDateTime(a.timestamp)}</td>
                <td><div className="cell-main" style={{ fontWeight: 600 }}>{a.actor}</div><div className="cell-sub">{a.actor_role}</div></td>
                <td><span className="tag">{a.action}</span></td>
                <td>{a.case_id ? <Link to={`/cases/${a.case_id}`} className="mono" style={{ fontSize: 12 }}>{a.case_id.slice(0, 8)}…</Link> : <span className="muted">—</span>}</td>
                <td className="cell-sub" style={{ maxWidth: 340 }}>{Object.keys(a.metadata || {}).length ? JSON.stringify(a.metadata).slice(0, 110) : ""}</td>
                <td className="cell-sub mono">{a.hash}</td>
              </tr>
            ))}
          </tbody></table>
        )}
        {items && items.length === 0 && <div className="empty"><ScrollText size={28} /><h4>No events</h4></div>}
      </Card>
    </div>
  );
}
