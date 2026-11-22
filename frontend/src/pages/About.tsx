import { AlertTriangle, ArrowRight, BookOpen, Database, Gauge, Lock, Map, Scale, ShieldCheck } from "lucide-react";
import { Card, STATUS_META, StatusPill } from "../ui";
import type { Status } from "../types";

const FLOW = ["Upload", "Intake & hash", "Rectify + quality gate", "OCR + MRZ", "Validation rules", "Forensics (baseline)", "Face 1:1 (optional)", "External checks", "Evidence & priority", "Officer review"];
const ROADMAP = [
  { t: "Done in this prototype", items: ["Secure intake, hashing, quality gate with recapture", "Zone OCR + deterministic ICAO 9303 TD3 parser", "Versioned rules, VIZ/MRZ cross-checks, date rules", "Transparent review-priority policy; audit hash chain", "Baseline ELA forensics with honest limits", "Synthetic data generator + evaluation harness"] },
  { t: "Before any pilot", items: ["Authorised, representative real-data collection and labelling", "Re-calibration and independent evaluation on held-out issuers/templates", "ePassport chip + ICAO PKD verification", "Registry integrations through approved interfaces", "Hardening: SAST/DAST, penetration test, malware scanning, MFA/IdP", "Legal, privacy, biometric and operational approvals"] },
  { t: "Later", items: ["Licensed, independently evaluated 1:1 face model with PAD testing", "Trained localised tamper models per issuer template", "Multispectral capture hardware (UV/IR) for substrate features", "Celery/Redis workers, PostgreSQL, MinIO, monitoring (config change, not rewrite)"] },
];

export default function About() {
  return (
    <div className="rise">
      <div className="page-h"><div><h1>About & limits</h1><p>What this system is, how it reaches its results, and — just as important — what it cannot do.</p></div></div>

      <div className="banner info"><ShieldCheck size={22} /><div><b>A document-screening assistant with a transparent evidence trail — not a fraud detector.</b><p>It reduces routine reading and cross-checking effort and shows exactly why a case needs a human look. Authorised officers make every consequential decision.</p></div></div>

      <Card title="End-to-end flow" icon={<Gauge size={16} />} className="" >
        <div className="flow">{FLOW.map((f, i) => <span key={f} className="row" style={{ gap: 8 }}><span className="node">{f}</span>{i < FLOW.length - 1 && <ArrowRight size={15} className="arrow" />}</span>)}</div>
      </Card>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card title="Check statuses used everywhere" icon={<BookOpen size={16} />}>
          <div className="col" style={{ gap: 11 }}>{(Object.keys(STATUS_META) as Status[]).map(s => <div key={s} className="row" style={{ alignItems: "flex-start" }}><div style={{ minWidth: 132 }}><StatusPill status={s} /></div><span style={{ color: "var(--text-2)", fontSize: 13 }}>{STATUS_META[s].hint}</span></div>)}</div>
          <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>Design rule: a timeout, a missing record, or a low-quality capture is <b>never</b> converted into a fraud signal.</p>
        </Card>
        <Card title="Principles" icon={<Scale size={16} />}>
          <ul className="rules" style={{ marginTop: 0 }}>
            <li><ShieldCheck size={15} /><span><b>Evidence first</b> — every alert links to its source region, rule, timestamp and version.</span></li>
            <li><ShieldCheck size={15} /><span><b>Fail visibly</b> — unavailable services and poor inputs are shown, not hidden.</span></li>
            <li><ShieldCheck size={15} /><span><b>Human oversight</b> — no autonomous admission, refusal or accusation.</span></li>
            <li><ShieldCheck size={15} /><span><b>Privacy by design</b> — synthetic data only here; role-based redaction; append-only audit.</span></li>
            <li><ShieldCheck size={15} /><span><b>No 1:N face search</b>, ever. 1:1 comparison only, quality-gated, with human fallback.</span></li>
          </ul>
        </Card>
      </div>

      <Card title="Honest limitations" icon={<AlertTriangle size={16} />} className="" >
        <ul className="rules" style={{ marginTop: 0 }}>
          {[
            "Image forensics is a weak baseline (ELA vs a template reference). It cannot prove editing and a clean result does not authenticate a document.",
            "An RGB photo cannot authenticate holograms, UV/IR features, substrate or tactile security features; those need suitable capture equipment.",
            "Results were developed and measured on synthetic documents of one fictional template. Performance on real documents, other issuers, cameras and demographics is unknown until evaluated on authorised data.",
            "Face comparison, ePassport chip / PKD verification and live registry checks are stubs here and are labelled UNAVAILABLE or NOT APPLICABLE.",
            "OCR can misread characters; the portal shows OCR confidence and lets officers correct fields, re-running every dependent check with an audit record.",
          ].map((t, i) => <li key={i}><AlertTriangle size={14} style={{ color: "var(--review)" }} /><span>{t}</span></li>)}
        </ul>
      </Card>

      <div className="grid g3" style={{ marginTop: 18 }}>
        {ROADMAP.map((c, i) => (
          <Card key={c.t} title={c.t} icon={i === 0 ? <Database size={16} /> : i === 1 ? <Lock size={16} /> : <Map size={16} />}>
            <ul className="rules" style={{ marginTop: 0 }}>{c.items.map(x => <li key={x}><ArrowRight size={14} style={{ color: "var(--brand)" }} /><span>{x}</span></li>)}</ul>
          </Card>
        ))}
      </div>
    </div>
  );
}
