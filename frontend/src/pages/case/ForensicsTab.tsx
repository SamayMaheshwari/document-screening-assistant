import { AlertTriangle, Flame, Info } from "lucide-react";
import { imgUrl } from "../../api";
import type { Results } from "../../types";
import { Card, StatusPill } from "../../ui";
import { ZONE_LABEL } from "./helpers";

const SCALE = 8, THR = 3.5;

export default function ForensicsTab({ r }: { r: Results }) {
  const fx = r.forensics;
  const doc = r.document!;
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="banner warn" style={{ margin: 0 }}><AlertTriangle size={22} /><div><b>Review aid, not proof</b><p>Image forensics here is a transparent <b>baseline</b> (Error Level Analysis against a template reference). It can highlight regions for a closer look. It cannot prove editing, and a clean result does not authenticate a document.</p></div></div>
      <div className="grid g-main">
        <Card title="Error-level analysis by region" icon={<Flame size={16} />} right={fx?.status && <StatusPill status={fx.status} />}>
          {fx?.applicable ? (
            <>
              <p className="muted" style={{ marginTop: 0, fontSize: 12.5 }}>Deviation of each region’s background error level from the calibrated reference for this template (z-score). Bars beyond the dashed threshold (±{THR}) are flagged for review.</p>
              {fx.findings.map(f => {
                const w = Math.min(Math.abs(f.z), SCALE) / SCALE * 50;
                const zRaw = (r.forensics!.findings.find(x => x.zone === f.zone) as any);
                return (
                  <div key={f.zone} className="zbar" title={f.message}>
                    <span style={{ fontWeight: f.status === "REVIEW" ? 700 : 500 }}>{ZONE_LABEL(f.zone)}</span>
                    <div className="zbar-track"><span className="mid" />
                      <span className="thr" style={{ left: `${50 + (THR / SCALE) * 50}%` }} /><span className="thr" style={{ left: `${50 - (THR / SCALE) * 50}%` }} />
                      <i className={f.status === "REVIEW" ? "flag" : ""} style={{ left: f.z < 0 ? `${50 - w}%` : "50%", width: `${w}%` }} /></div>
                    <span className="mono" style={{ fontSize: 12, textAlign: "right", color: f.status === "REVIEW" ? "var(--fail)" : "var(--text-3)" }}>{zRaw.z > 0 ? "+" : ""}{f.z.toFixed(1)}</span>
                  </div>
                );
              })}
              <div style={{ marginTop: 14 }}>{fx.findings.filter(f => f.status === "REVIEW").map(f => <div className="reason" key={f.zone}><span className="dotk" style={{ background: "var(--review)" }} /><div><p><b>{ZONE_LABEL(f.zone)}</b> — {f.message}</p></div></div>)}</div>
            </>
          ) : (
            <div className="banner info" style={{ margin: 0 }}><Info size={20} /><div><b>Not applicable to this capture</b><p>{fx?.reason || "Forensics did not run."}</p></div></div>
          )}
        </Card>
        <Card title="ELA heatmap" icon={<Flame size={16} />}>
          {doc.has_heatmap && !r.pii_redacted ? (
            <>
              <img src={imgUrl(r.case.id, "heatmap", doc.capture_index)} alt="ELA heatmap" style={{ width: "100%", borderRadius: 10, border: "1px solid var(--line)" }} />
              <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>Brighter = higher error level after recompression. Compare regions against each other and the reference — absolute brightness is not meaningful by itself.</p>
            </>
          ) : <p className="muted" style={{ margin: 0 }}>{r.pii_redacted ? "Hidden for your role." : "No heatmap was generated for this capture."}</p>}
        </Card>
      </div>
      <Card title="Known limitations" icon={<Info size={16} />}>
        <ul className="rules" style={{ marginTop: 0 }}>
          {r.limitations.map((l, i) => <li key={i}><Info size={14} style={{ color: "var(--text-3)" }} /><span>{l}</span></li>)}
        </ul>
      </Card>
    </div>
  );
}
