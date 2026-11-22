import { useEffect, useMemo, useState } from "react";
import { Flame, ImageOff, Layers, Minus, Plus, ScanText, Flag } from "lucide-react";
import { imgUrl } from "../../api";
import type { Results } from "../../types";
import { StatusPill } from "../../ui";
import { flagsOf, ZONE_LABEL } from "./helpers";

interface Tip { x: number; y: number; html: JSX.Element }

export default function DocumentViewer({ r, focusId, clearFocus }: { r: Results; focusId?: string; clearFocus: () => void }) {
  const doc = r.document!;
  const caseId = r.case.id;
  const [view, setView] = useState<"rectified" | "original">(doc.has_rectified ? "rectified" : "original");
  const [showFields, setShowFields] = useState(true);
  const [showMrz, setShowMrz] = useState(true);
  const [showFlags, setShowFlags] = useState(true);
  const [showHeat, setShowHeat] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [tip, setTip] = useState<Tip | null>(null);
  const [sel, setSel] = useState<string | undefined>(focusId);
  const flags = useMemo(() => flagsOf(r), [r]);
  const rect = view === "rectified" && doc.has_rectified;

  useEffect(() => { if (focusId) { setSel(focusId); setShowFlags(true); } }, [focusId]);
  // ELA check id maps to all forensic flags
  const isSel = (id: string) => sel === id || (sel === "forensics_ela" && id.startsWith("ela_"));

  if (r.pii_redacted) return <div className="empty card" style={{ padding: 60 }}><ImageOff size={30} /><h4>Document images are hidden for your role</h4><p>Auditors see redacted data only. An officer or admin can view the image.</p></div>;

  const show = (e: React.MouseEvent, html: JSX.Element) => setTip({ x: Math.min(e.clientX + 14, window.innerWidth - 300), y: e.clientY + 14, html });

  return (
    <div className="viewer">
      <div>
        <div className="viewer-bar">
          <div className="seg">
            <button className={view === "rectified" ? "on" : ""} disabled={!doc.has_rectified} onClick={() => setView("rectified")}><Layers size={14} />Rectified</button>
            <button className={view === "original" ? "on" : ""} onClick={() => setView("original")}>Original</button>
          </div>
          {rect && <>
            <span className={`toggle ${showFields ? "on" : ""}`} onClick={() => setShowFields(!showFields)}><ScanText size={14} />OCR fields</span>
            <span className={`toggle ${showMrz ? "on" : ""}`} onClick={() => setShowMrz(!showMrz)}>MRZ</span>
            <span className={`toggle ${showFlags ? "on" : ""}`} onClick={() => setShowFlags(!showFlags)}><Flag size={14} />Flagged ({flags.length})</span>
            {doc.has_heatmap && <span className={`toggle ${showHeat ? "on" : ""}`} onClick={() => setShowHeat(!showHeat)}><Flame size={14} />ELA heatmap</span>}
          </>}
          <div className="row" style={{ marginLeft: "auto", gap: 6 }}>
            <button className="btn sm" onClick={() => setZoom(z => Math.max(0.6, +(z - 0.2).toFixed(1)))}><Minus size={13} /></button>
            <span style={{ fontSize: 12.5, fontWeight: 650, minWidth: 40, textAlign: "center" }}>{Math.round(zoom * 100)}%</span>
            <button className="btn sm" onClick={() => setZoom(z => Math.min(2.4, +(z + 0.2).toFixed(1)))}><Plus size={13} /></button>
          </div>
        </div>
        <div className="stage" onMouseLeave={() => setTip(null)}>
          <div className="stage-inner" style={{ width: `${zoom * 100}%` }}>
            <img src={imgUrl(caseId, view, doc.capture_index, true)} alt="Document" draggable={false} />
            {rect && doc.has_heatmap && <img className="heat" src={imgUrl(caseId, "heatmap", doc.capture_index)} alt="" style={{ opacity: showHeat ? 0.85 : 0 }} />}
            {rect && (
              <svg viewBox="0 0 1250 880" preserveAspectRatio="none">
                {showFields && r.fields.filter(f => f.source === "VIZ" && f.bbox).map(f => (
                  <rect key={f.id} x={f.bbox![0] - 4} y={f.bbox![1] - 3} width={f.bbox![2] + 8} height={f.bbox![3] + 6} className={`ov ${f.confidence < 0.8 || f.needs_review ? "low" : ""}`}
                    onMouseMove={e => show(e, <><b>{f.label}</b><br /><span className="mono">{f.corrected_value ?? f.value ?? f.raw}</span><br />confidence {Math.round(f.confidence * 100)}% · {f.engine}</>)} />
                ))}
                {showMrz && r.fields.filter(f => f.name.startsWith("mrz_line") && f.bbox).map(f => (
                  <rect key={f.id} x={f.bbox![0] - 4} y={f.bbox![1] - 3} width={f.bbox![2] + 8} height={f.bbox![3] + 6} className="ov mrz"
                    onMouseMove={e => show(e, <><b>{f.label}</b><br />Machine readable zone · confidence {Math.round(f.confidence * 100)}%</>)} />
                ))}
                {showFlags && flags.map(f => (
                  <rect key={f.id} x={f.box[0]} y={f.box[1]} width={f.box[2]} height={f.box[3]} className={`ov flag ${isSel(f.id) ? "sel" : ""}`}
                    onClick={() => setSel(f.id)} onMouseMove={e => show(e, <><b>{f.title}</b><br />{f.message}</>)} />
                ))}
              </svg>
            )}
          </div>
        </div>
        {!rect && <p className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>{doc.has_rectified ? "Overlays are only drawn on the rectified image." : "No rectified copy exists for this capture (quality gate failed)."} The original file is preserved unchanged.</p>}
        {tip && <div className="tip" style={{ left: tip.x, top: tip.y }}>{tip.html}</div>}
      </div>

      <div className="col">
        <div className="card"><div className="card-h"><h3><Flag size={15} />Flagged regions</h3></div>
          <div className="card-b side-list">
            {flags.length === 0 && <p className="muted" style={{ margin: 0 }}>No region was flagged by a rule or indicator on this capture.</p>}
            {flags.map(f => (
              <button key={f.id} className={`side-item ${isSel(f.id) ? "sel" : ""}`} onClick={() => { setSel(f.id); setShowFlags(true); }}>
                <span className="t1"><span>{f.title}</span><StatusPill status={f.status} small /></span>
                <small>{f.message}</small>
              </button>
            ))}
            {sel && <button className="btn sm" onClick={() => { setSel(undefined); clearFocus(); }}>Clear selection</button>}
          </div>
        </div>
        <div className="card"><div className="card-h"><h3><ScanText size={15} />Legend</h3></div>
          <div className="card-b col" style={{ fontSize: 12.5, gap: 8 }}>
            <span className="row"><i style={{ width: 14, height: 14, border: "2px solid #7b96ff", borderRadius: 3 }} />OCR field (confident)</span>
            <span className="row"><i style={{ width: 14, height: 14, border: "2px solid #f59e0b", borderRadius: 3 }} />OCR field with low confidence</span>
            <span className="row"><i style={{ width: 14, height: 14, border: "2px solid #22d3ee", borderRadius: 3 }} />Machine readable zone</span>
            <span className="row"><i style={{ width: 14, height: 14, border: "2px solid #ff5d5d", borderRadius: 3 }} />Flagged for officer attention</span>
            <p className="muted" style={{ margin: "4px 0 0" }}>Heatmap and flags are <b>review aids, not proof</b>. Hover a box for details.</p>
          </div>
        </div>
        {r.documents.length > 1 && <div className="card"><div className="card-h"><h3>Capture history</h3></div><div className="card-b col" style={{ fontSize: 12.5 }}>
          {r.documents.map(d => <div key={d.id} className="row spread"><span>Capture #{d.capture_index}{d.superseded ? " (superseded)" : " (current)"}</span><span className="mono muted">{d.sha256.slice(0, 10)}…</span></div>)}
        </div></div>}
      </div>
    </div>
  );
}
