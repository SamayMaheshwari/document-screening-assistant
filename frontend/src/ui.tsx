import { ReactNode, createContext, useCallback, useContext, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, CircleSlash, HelpCircle, Loader2, ServerCrash, XCircle } from "lucide-react";
import type { CaseStatus, Priority, Status } from "./types";

export const STATUS_META: Record<Status, { label: string; cls: string; icon: ReactNode; hint: string }> = {
  PASS: { label: "Pass", cls: "s-pass", icon: <CheckCircle2 size={13} />, hint: "Check completed and no configured issue found." },
  FAIL: { label: "Fail", cls: "s-fail", icon: <XCircle size={13} />, hint: "A deterministic rule or trusted source reports a defined failure." },
  REVIEW: { label: "Review", cls: "s-review", icon: <AlertTriangle size={13} />, hint: "An anomaly or discrepancy needs human assessment." },
  INCONCLUSIVE: { label: "Inconclusive", cls: "s-inconc", icon: <HelpCircle size={13} />, hint: "Quality or model limitations prevent a reliable result." },
  UNAVAILABLE: { label: "Unavailable", cls: "s-unavail", icon: <ServerCrash size={13} />, hint: "An external service did not respond. Not a fraud signal." },
  NOT_APPLICABLE: { label: "Not applicable", cls: "s-na", icon: <CircleSlash size={13} />, hint: "Check does not apply to this document or case." },
};

export function StatusPill({ status, small }: { status: Status | string; small?: boolean }) {
  const m = STATUS_META[status as Status];
  if (!m) return <span className="pill s-na">{status}</span>;
  return <span className={`pill ${m.cls} ${small ? "pill-sm" : ""}`} title={m.hint}>{m.icon}{m.label}</span>;
}

export const CASE_META: Record<CaseStatus, { label: string; cls: string }> = {
  NEW: { label: "New", cls: "c-new" }, PROCESSING: { label: "Processing", cls: "c-proc" }, COMPLETED: { label: "Completed", cls: "c-done" },
  REVIEW_REQUIRED: { label: "Review required", cls: "c-review" }, RECAPTURE_REQUIRED: { label: "Recapture required", cls: "c-recap" },
  FAILED: { label: "Failed", cls: "c-failed" }, REVIEWED: { label: "Reviewed", cls: "c-reviewed" },
};
export function CasePill({ status }: { status: CaseStatus }) {
  const m = CASE_META[status] || { label: status, cls: "c-new" };
  return <span className={`pill ${m.cls}`}>{status === "PROCESSING" && <Loader2 size={12} className="spin" />}{m.label}</span>;
}

export const PRIORITY_META: Record<Priority, { label: string; cls: string }> = {
  LOW: { label: "Low priority", cls: "p-low" }, MEDIUM: { label: "Medium priority", cls: "p-med" },
  HIGH: { label: "High priority", cls: "p-high" }, INCOMPLETE: { label: "Not assessed", cls: "p-inc" },
};
export function PriorityBadge({ p, complete }: { p: Priority | null; complete?: boolean | null }) {
  if (!p) return <span className="muted">—</span>;
  const m = PRIORITY_META[p];
  return <span className="prio-wrap"><span className={`prio ${m.cls}`}><i />{m.label}</span>{complete === false && p !== "INCOMPLETE" && <span className="incomplete-tag" title="Some checks are unresolved (inconclusive or unavailable)"><CircleDashed size={11} />incomplete</span>}</span>;
}

export function Card({ title, icon, right, children, className = "", pad = true }: { title?: ReactNode; icon?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && <header className="card-h"><h3>{icon}{title}</h3><div>{right}</div></header>}
      <div className={pad ? "card-b" : ""}>{children}</div>
    </section>
  );
}

export function Empty({ icon, title, text, action }: { icon?: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return <div className="empty">{icon}<h4>{title}</h4>{text && <p>{text}</p>}{action}</div>;
}

export function ConfBar({ v, min = 0.8 }: { v: number; min?: number }) {
  const pct = Math.round(v * 100);
  const cls = v >= 0.9 ? "ok" : v >= min ? "mid" : "low";
  return <div className="conf" title={`OCR confidence ${pct}%`}><div className={`conf-bar ${cls}`}><i style={{ width: `${pct}%` }} /></div><span>{pct}%</span></div>;
}

export function Spinner({ size = 18 }: { size?: number }) { return <Loader2 size={size} className="spin" />; }

export function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export const fmtDateTime = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

// ---- toasts
type Toast = { id: number; kind: "ok" | "err" | "info"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems(i => [...i, { id, kind, text }]);
    setTimeout(() => setItems(i => i.filter(t => t.id !== id)), 4800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">{items.map(t => <div key={t.id} className={`toast t-${t.kind}`}>{t.text}</div>)}</div>
    </ToastCtx.Provider>
  );
}
