import { AlertTriangle, ArrowUpRight, CircleDashed, Eye, Gauge, ImageOff, RefreshCcw, ShieldCheck, UserCheck } from "lucide-react";
import { imgUrl } from "../../api";
import type { Results } from "../../types";
import { Card, StatusPill } from "../../ui";
import { DIM_ICON_ORDER, DIM_TITLE, flagsOf, regionOf } from "./helpers";
import { Stepper } from "./Stepper";

const DIAL: Record<string, string> = { LOW: "dial-low", MEDIUM: "dial-med", HIGH: "dial-high", INCOMPLETE: "dial-inc" };
const PRIO_TEXT: Record<string, string> = { LOW: "LOW", MEDIUM: "MEDIUM", HIGH: "HIGH", INCOMPLETE: "N/A" };
const DOT: Record<string, string> = { FAIL: "var(--fail)", REVIEW: "var(--review)", INFO: "var(--brand)", INCONCLUSIVE: "var(--inconc)", UNAVAILABLE: "var(--unavail)" };

export default function Overview({ r, go, canRecapture, onRecapture }: { r: Results; go: (tab: string, focusId?: string) => void; canRecapture: boolean; onRecapture: () => void }) {
  const risk = r.risk;
  const c = r.case;
  const flags = flagsOf(r);
  const q = r.document?.quality || [];
  const regionById = new Map(r.checks.map(ch => [ch.id, regionOf(ch)]));

  return (
    <div className="grid g-main">
      <div className="col" style={{ gap: 18 }}>
        {c.status === "RECAPTURE_REQUIRED" && (
          <div className="banner recap"><RefreshCcw size={22} />
            <div style={{ flex: 1 }}><b>Recapture requested — analysis was not run</b>
              <p>The capture quality was too low for reliable OCR, so no downstream results were generated rather than showing unreliable ones. {q.filter(m => m.status === "FAIL" || m.status === "INCONCLUSIVE").map(m => m.message).join(" ")}</p>
              {canRecapture && <button className="btn sm" style={{ marginTop: 10 }} onClick={onRecapture}><RefreshCcw size={13} />Attach a new capture</button>}
            </div>
          </div>
        )}
        {c.status === "REVIEWED" && r.reviews.length > 0 && (
          <div className="banner info"><UserCheck size={22} /><div><b>Reviewed by {r.reviews[r.reviews.length - 1].officer}</b><p>{r.reviews[r.reviews.length - 1].outcome.replace(/_/g, " ").toLowerCase()} — “{r.reviews[r.reviews.length - 1].rationale}”</p></div></div>
        )}

        {risk && (
          <Card pad={false}>
            <div className="risk-hero">
              <div className={`risk-dial ${DIAL[risk.priority]}`}><div>{PRIO_TEXT[risk.priority]}<small>PRIORITY</small></div></div>
              <div style={{ flex: 1 }}>
                <h2 style={{ fontSize: 19 }}>{risk.priority === "INCOMPLETE" ? "Not assessed — recapture needed" : `${risk.priority[0] + risk.priority.slice(1).toLowerCase()} review priority`}</h2>
                <p style={{ margin: "5px 0 0", color: "var(--text-2)" }}>
                  {risk.priority === "INCOMPLETE" ? "A reliable assessment is not possible from this capture." :
                    risk.reasons.filter(x => x.status !== "INFO").length === 0 ? "No configured rule or indicator raised a finding." :
                      `${risk.reasons.filter(x => x.status !== "INFO").length} finding(s) raised by deterministic rules or review-aid indicators.`}
                  {risk.complete === false && risk.priority !== "INCOMPLETE" ? ` ${risk.unresolved.length} check(s) could not be completed.` : ""}
                </p>
                <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}><ShieldCheck size={13} style={{ verticalAlign: -2 }} /> A prompt for human attention, not a fraud verdict. Policy: {risk.policy_version}</p>
              </div>
            </div>
          </Card>
        )}

        {risk && (
          <div className="grid g2">
            {DIM_ICON_ORDER.map(d => {
              const dim = risk.dimensions[d];
              if (!dim) return null;
              return (
                <div key={d} className={`dim d-${dim.level}`}>
                  <h5>{DIM_TITLE[d]}</h5>
                  <div className={`lv lv-${dim.level}`}>{dim.level === "CLEAR" ? "Clear" : dim.level === "FAIL" ? "Failed check" : dim.level === "REVIEW" ? "Needs review" : dim.level === "INCOMPLETE" ? "Incomplete" : dim.level === "NOT_ASSESSED" ? "Not assessed" : "Not applicable"}</div>
                  <small>{dim.counts.pass} passed · {dim.counts.fail} failed · {dim.counts.review} review · {dim.counts.unresolved} unresolved</small>
                </div>
              );
            })}
          </div>
        )}

        {risk && risk.reasons.length > 0 && (
          <Card title="Evidence behind this priority" icon={<AlertTriangle size={16} />}>
            {risk.reasons.map((x, i) => {
              const hasRegion = !!regionById.get(x.check_id) || x.check_id === "forensics_ela";
              return (
                <div className="reason" key={i}>
                  <span className="dotk" style={{ background: DOT[x.status] }} />
                  <div style={{ flex: 1 }}><p>{x.text}</p><small>{x.dimension.replace(/_/g, " ")} · {x.status}</small></div>
                  {hasRegion && <button className="btn sm" onClick={() => go("document", x.check_id)}><Eye size={13} />Show</button>}
                </div>
              );
            })}
          </Card>
        )}

        {risk && risk.unresolved.length > 0 && (
          <Card title="Could not be verified — not a fraud signal" icon={<CircleDashed size={16} />}>
            {risk.unresolved.map((x, i) => (
              <div className="reason" key={i}><span className="dotk" style={{ background: DOT[x.status] }} /><div><p>{x.text}</p><small>{x.status}</small></div></div>
            ))}
          </Card>
        )}
      </div>

      <div className="col" style={{ gap: 18 }}>
        <Card title="Document" icon={<Eye size={16} />} right={<button className="btn sm" onClick={() => go("document")}>Open viewer <ArrowUpRight size={13} /></button>}>
          {r.document && (r.document.has_rectified || r.document) && !r.pii_redacted ? (
            <div style={{ position: "relative", lineHeight: 0, borderRadius: 10, overflow: "hidden", background: "#0b1228" }}>
              <img src={imgUrl(c.id, r.document.has_rectified ? "rectified" : "original", r.document.capture_index)} alt="Document" style={{ width: "100%" }} />
              {r.document.has_rectified && (
                <svg viewBox="0 0 1250 880" style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} preserveAspectRatio="none">
                  {flags.map(f => <rect key={f.id} x={f.box[0]} y={f.box[1]} width={f.box[2]} height={f.box[3]} className="ov flag" />)}
                </svg>
              )}
            </div>
          ) : <div className="empty" style={{ padding: 24 }}><ImageOff size={26} /><p style={{ margin: 0 }}>{r.pii_redacted ? "Images are hidden for your role." : "No image"}</p></div>}
          {r.document && <dl className="kv" style={{ marginTop: 14 }}>
            <dt>Capture</dt><dd>#{r.document.capture_index} · {r.document.width}×{r.document.height}px · {(r.document.size_bytes / 1024).toFixed(0)} KB</dd>
            <dt>SHA-256</dt><dd className="mono" style={{ fontSize: 11 }}>{r.document.sha256.slice(0, 32)}…</dd>
            <dt>Rectification</dt><dd>{r.document.preprocessing.method || "—"}{r.document.preprocessing.resampled ? " (resampled)" : ""}</dd>
          </dl>}
        </Card>

        <Card title="Capture quality" icon={<Gauge size={16} />}>
          <div className="qm">
            {q.map(m => (
              <div className="qm-row" key={m.name}>
                <div><b style={{ fontWeight: 650 }}>{m.label}</b></div><StatusPill status={m.status} small />
                <small>{m.value !== null ? `${m.value}${m.unit ? " " + m.unit : ""} · ` : ""}{m.message}</small>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Processing pipeline" icon={<ShieldCheck size={16} />}><Stepper steps={r.steps} compact /></Card>
      </div>
    </div>
  );
}
