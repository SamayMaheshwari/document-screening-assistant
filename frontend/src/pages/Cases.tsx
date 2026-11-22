import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, Search } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { CaseSummary } from "../types";
import { Card, CasePill, CASE_META, Empty, PriorityBadge, Spinner, fmtDateTime, timeAgo } from "../ui";

const STATUSES = ["ALL", "REVIEW_REQUIRED", "RECAPTURE_REQUIRED", "PROCESSING", "COMPLETED", "REVIEWED", "FAILED"];

export default function Cases() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [items, setItems] = useState<CaseSummary[] | null>(null);
  const [status, setStatus] = useState("ALL");
  const [prio, setPrio] = useState("ALL");
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () => {
      const p = new URLSearchParams();
      if (status !== "ALL") p.set("status", status);
      if (prio !== "ALL") p.set("priority", prio);
      if (q.trim()) p.set("q", q.trim());
      api.get<{ items: CaseSummary[] }>(`/cases?${p}`).then(r => alive && setItems(r.items)).catch(() => {});
    };
    load();
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [status, prio, q]);

  return (
    <div className="rise">
      <div className="page-h">
        <div><h1>Case queue</h1><p>All screening cases. Sorted by newest first; use the filters to focus on cases that need attention.</p></div>
        {can("case:create") && <Link to="/cases/new" className="btn primary" style={{ textDecoration: "none" }}><Plus size={16} />New screening</Link>}
      </div>
      <Card pad={false}>
        <div style={{ padding: 16, borderBottom: "1px solid var(--line)" }} className="row wrap spread">
          <div className="seg" style={{ flexWrap: "wrap" }}>
            {STATUSES.map(s => <button key={s} className={status === s ? "on" : ""} onClick={() => setStatus(s)}>{s === "ALL" ? "All" : CASE_META[s as keyof typeof CASE_META].label}</button>)}
          </div>
          <div className="row">
            <div className="seg">{["ALL", "HIGH", "MEDIUM", "LOW"].map(p => <button key={p} className={prio === p ? "on" : ""} onClick={() => setPrio(p)}>{p === "ALL" ? "Any priority" : p[0] + p.slice(1).toLowerCase()}</button>)}</div>
            <div style={{ position: "relative" }}><Search size={15} style={{ position: "absolute", left: 11, top: 11, color: "var(--text-3)" }} /><input className="input" style={{ paddingLeft: 33, width: 220 }} placeholder="Search case number…" value={q} onChange={e => setQ(e.target.value)} /></div>
          </div>
        </div>
        {items === null ? <div style={{ padding: 40, textAlign: "center" }}><Spinner size={26} /></div> : items.length === 0 ? (
          <Empty title="No cases match" text="Try clearing the filters, or screen a demo sample." action={<Link to="/demo" className="btn sm">Open demo lab</Link>} />
        ) : (
          <table className="t"><thead><tr><th>Case</th><th>Holder</th><th>Status</th><th>Review priority</th><th>Findings</th><th>Captures</th><th>Created</th></tr></thead><tbody>
            {items.map(c => (
              <tr key={c.id} className="click" onClick={() => nav(`/cases/${c.id}`)}>
                <td><div className="cell-main">{c.case_number}</div><div className="cell-sub">{c.label || "Passport"}</div></td>
                <td>{c.holder ? <span className="cell-main" style={{ fontWeight: 550 }}>{c.holder}</span> : <span className="muted">—</span>}</td>
                <td><CasePill status={c.status} /></td>
                <td><PriorityBadge p={c.priority} complete={c.complete} /></td>
                <td className="cell-sub">{c.status === "PROCESSING" ? "…" : `${c.reason_count} flagged${c.unresolved_count ? ` · ${c.unresolved_count} unresolved` : ""}`}</td>
                <td className="cell-sub">{c.capture_count}</td>
                <td className="cell-sub" title={fmtDateTime(c.created_at)}>{timeAgo(c.created_at)}</td>
              </tr>
            ))}
          </tbody></table>
        )}
      </Card>
    </div>
  );
}
