import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, ArrowRight, CheckCircle2, FlaskConical, FolderOpen, RefreshCcw, ShieldAlert } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import type { AuditItem, CaseSummary, Stats } from "../types";
import { Card, CasePill, Empty, PriorityBadge, Spinner, STATUS_META, timeAgo } from "../ui";

const PRIO_COLORS: Record<string, string> = { LOW: "#22c55e", MEDIUM: "#f59e0b", HIGH: "#ef4444", INCOMPLETE: "#94a3b8" };
const PRIO_LABEL: Record<string, string> = { LOW: "Low", MEDIUM: "Medium", HIGH: "High", INCOMPLETE: "Not assessed (recapture)" };
const CHECK_COLORS: Record<string, string> = { PASS: "#22c55e", FAIL: "#ef4444", REVIEW: "#f59e0b", INCONCLUSIVE: "#8b5cf6", UNAVAILABLE: "#64748b", NOT_APPLICABLE: "#a8b3c7" };

function Donut({ data, total }: { data: { k: string; v: number }[]; total: number }) {
  const r = 52, c = 2 * Math.PI * r;
  let off = 0;
  return (
    <svg width="148" height="148" viewBox="0 0 148 148" role="img" aria-label="Review priority distribution">
      <circle cx="74" cy="74" r={r} fill="none" stroke="var(--line)" strokeWidth="18" />
      {data.filter(d => d.v > 0).map(d => {
        const len = (d.v / Math.max(total, 1)) * c;
        const el = <circle key={d.k} cx="74" cy="74" r={r} fill="none" stroke={PRIO_COLORS[d.k]} strokeWidth="18" strokeDasharray={`${Math.max(len - 2, 0)} ${c}`} strokeDashoffset={-off} transform="rotate(-90 74 74)" />;
        off += len;
        return el;
      })}
      <text x="74" y="72" textAnchor="middle" fontSize="26" fontWeight="800" fill="var(--text)">{total}</text>
      <text x="74" y="90" textAnchor="middle" fontSize="11" fill="var(--text-3)">cases</text>
    </svg>
  );
}

export default function Dashboard() {
  const { user, can } = useAuth();
  const nav = useNavigate();
  const [stats, setStats] = useState<Stats | null>(null);
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [audit, setAudit] = useState<AuditItem[]>([]);

  const load = () => {
    api.get<Stats>("/stats").then(setStats).catch(() => {});
    api.get<{ items: CaseSummary[] }>("/cases?limit=60").then(r => setCases(r.items)).catch(() => {});
    if (can("audit:read")) api.get<{ items: AuditItem[] }>("/audit?limit=7").then(r => setAudit(r.items)).catch(() => {});
  };
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, []);

  if (!stats) return <div style={{ display: "grid", placeItems: "center", height: 300 }}><Spinner size={28} /></div>;
  const attention = cases.filter(c => ["REVIEW_REQUIRED", "RECAPTURE_REQUIRED", "FAILED"].includes(c.status)).sort((a, b) => ({ HIGH: 0, MEDIUM: 1, LOW: 2, INCOMPLETE: 3 } as any)[a.priority || "LOW"] - ({ HIGH: 0, MEDIUM: 1, LOW: 2, INCOMPLETE: 3 } as any)[b.priority || "LOW"]).slice(0, 6);
  const prioData = ["HIGH", "MEDIUM", "LOW", "INCOMPLETE"].map(k => ({ k, v: stats.by_priority[k] || 0 }));
  const prioTotal = prioData.reduce((a, b) => a + b.v, 0);
  const checkTotal = Object.values(stats.check_status).reduce((a, b) => a + b, 0) || 1;
  const completed = (stats.by_status.COMPLETED || 0) + (stats.by_status.REVIEWED || 0);

  return (
    <div className="rise">
      <div className="page-h">
        <div><h1>Good to see you, {user?.name.split(" ").slice(-2, -1)[0] || user?.name}</h1><p>Overview of screening activity. Review priority is a prompt for human attention, not a verdict.</p></div>
        <div className="row">
          <button className="btn" onClick={load}><RefreshCcw size={15} />Refresh</button>
          {can("case:create") && <Link to="/demo" className="btn primary" style={{ textDecoration: "none" }}><FlaskConical size={15} />Run the demo script</Link>}
        </div>
      </div>

      <div className="grid g4" style={{ marginBottom: 18 }}>
        <Card className="kpi"><div className="ic ic-blue"><FolderOpen size={22} /></div><div><div className="v">{stats.total}</div><div className="l">Total cases</div></div></Card>
        <Card className="kpi"><div className="ic ic-amber"><ShieldAlert size={22} /></div><div><div className="v">{stats.by_status.REVIEW_REQUIRED || 0}</div><div className="l">Awaiting officer review</div></div></Card>
        <Card className="kpi"><div className="ic ic-violet"><RefreshCcw size={22} /></div><div><div className="v">{stats.by_status.RECAPTURE_REQUIRED || 0}</div><div className="l">Recapture requested</div></div></Card>
        <Card className="kpi"><div className="ic ic-green"><CheckCircle2 size={22} /></div><div><div className="v">{completed}</div><div className="l">Completed / reviewed</div></div></Card>
      </div>

      <div className="grid g-main" style={{ marginBottom: 18 }}>
        <Card title="Needs attention" icon={<ShieldAlert size={16} />} right={<Link to="/cases" className="row" style={{ fontSize: 13, gap: 4 }}>All cases <ArrowRight size={14} /></Link>} pad={false}>
          {attention.length === 0 ? <Empty icon={<CheckCircle2 size={30} />} title="Nothing waiting" text="No cases need review right now. Run a demo sample to populate the queue." action={<Link to="/demo" className="btn sm">Open demo lab</Link>} /> : (
            <table className="t"><thead><tr><th>Case</th><th>Status</th><th>Priority</th><th>Findings</th><th></th></tr></thead><tbody>
              {attention.map(c => (
                <tr key={c.id} className="click" onClick={() => nav(`/cases/${c.id}`)}>
                  <td><div className="cell-main">{c.case_number}</div><div className="cell-sub">{c.label || c.document_type || "Passport"}</div></td>
                  <td><CasePill status={c.status} /></td>
                  <td><PriorityBadge p={c.priority} complete={c.complete} /></td>
                  <td className="cell-sub">{c.reason_count} flagged{c.unresolved_count ? ` · ${c.unresolved_count} unresolved` : ""}</td>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>{timeAgo(c.created_at)}</td>
                </tr>
              ))}
            </tbody></table>
          )}
        </Card>
        <Card title="Review priority" icon={<Activity size={16} />}>
          <div className="donut-wrap">
            <Donut data={prioData} total={prioTotal} />
            <div className="legend" style={{ flex: 1, minWidth: 160 }}>
              {prioData.map(d => <div key={d.k}><i style={{ background: PRIO_COLORS[d.k] }} />{PRIO_LABEL[d.k]}<b>{d.v}</b></div>)}
            </div>
          </div>
          <p className="muted" style={{ fontSize: 12, margin: "14px 0 0" }}>{stats.cases_with_unresolved} case(s) have unresolved checks (inconclusive or unavailable) — these never raise priority.</p>
        </Card>
      </div>

      <div className="grid g2">
        <Card title="All checks by outcome" icon={<CheckCircle2 size={16} />}>
          <div className="hbar">
            {Object.keys(STATUS_META).map(k => (
              <div className="hbar-row" key={k}>
                <span>{STATUS_META[k as keyof typeof STATUS_META].label}</span>
                <div className="hbar-track"><i style={{ width: `${((stats.check_status[k] || 0) / checkTotal) * 100}%`, background: CHECK_COLORS[k] }} /></div>
                <b style={{ textAlign: "right" }}>{stats.check_status[k] || 0}</b>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Recent activity" icon={<Activity size={16} />} right={can("audit:read") ? <Link to="/audit" style={{ fontSize: 13 }}>Audit log</Link> : null}>
          {!can("audit:read") ? <p className="muted" style={{ margin: 0 }}>Every view, edit, review and export is written to a tamper-evident audit log. Admins and auditors can inspect it.</p> : audit.length === 0 ? <p className="muted">No events yet.</p> : (
            <div className="timeline">{audit.map(a => <div className="tl" key={a.seq}><b>{a.action}</b><small>{a.actor} · {timeAgo(a.timestamp)}</small></div>)}</div>
          )}
        </Card>
      </div>
    </div>
  );
}
