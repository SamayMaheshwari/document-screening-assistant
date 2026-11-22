import { useEffect, useState } from "react";
import { AlertTriangle, BarChart3, Bug, Info } from "lucide-react";
import { api } from "../api";
import { Card, Empty, Spinner } from "../ui";

interface Metric { id: string; label: string; value: number; ci: [number, number]; n: number; unit: string; note?: string }
interface Variant { variant: string; n: number; expected_priority: string; priority_match_rate: number; n_low: number; n_medium: number; n_high: number; n_incomplete: number; quality_gate_failed: number; ela_not_applicable: number; ela_region_flagged: number }
interface Evalr {
  available: boolean; generated_at?: string;
  dataset?: { name: string; n_documents: number; n_persons: number; split: { train: number; test: number; leaks: Record<string, string[]> } };
  config?: { bootstrap_resamples: number; versions: Record<string, string> };
  metrics?: Record<string, Metric[]>; per_variant?: Variant[];
  failure_cases?: { doc_id: string; variant: string; category: string; expected: string; got: string; note: string }[];
  n_failure_cases_total?: number; limitations?: string[];
}

const GROUPS: Record<string, { title: string; keys: string[] }> = {
  ocr: { title: "OCR and MRZ reading", keys: ["viz_exact_mean", "mrz_cer_raw", "mrz_cer_normalised", "mrz_exact_line_match", "viz_exact_place_of_birth"] },
  validation: { title: "Validation rules", keys: ["check_digit_detection_recall", "viz_mrz_mismatch_detection_recall", "expired_detection_recall", "clean_case_false_escalation_rate"] },
  quality_gate: { title: "Quality gate (recapture)", keys: ["recapture_precision", "recapture_recall"] },
  forensics: { title: "Forensics baseline (ELA)", keys: ["region_precision", "region_recall", "localisation_iou_detected", "document_false_alert_rate_clean", "ela_not_applicable_fraction"] },
};
const pct = (v: number, unit: string) => unit === "ratio" ? v.toFixed(2) : `${(v * 100).toFixed(v < 0.01 && v > 0 ? 2 : 1)}%`;

function MetricCard({ m }: { m: Metric }) {
  return (
    <Card className="metric" pad={false}>
      <div className="metric">
        <div className="l">{m.label}</div>
        <div className="v">{pct(m.value, m.unit)}</div>
        <div className="ci" title="95% bootstrap confidence interval"><i style={{ left: `${m.ci[0] * 100}%`, width: `${Math.max((m.ci[1] - m.ci[0]) * 100, 1)}%` }} /><b style={{ left: `calc(${m.value * 100}% - 1px)` }} /></div>
        <small>95% CI {pct(m.ci[0], m.unit)} – {pct(m.ci[1], m.unit)} · n = {m.n}{m.n < 20 ? " (small sample)" : ""}</small>
      </div>
    </Card>
  );
}

export default function Evaluation() {
  const [d, setD] = useState<Evalr | null>(null);
  useEffect(() => { api.get<Evalr>("/evaluation").then(setD); }, []);
  if (!d) return <div style={{ display: "grid", placeItems: "center", height: 300 }}><Spinner size={28} /></div>;
  if (!d.available) return <Empty icon={<BarChart3 size={30} />} title="No evaluation results yet" text="Run the evaluation harness in model-work/evaluation to populate this page." />;
  const leaks = Object.values(d.dataset!.split.leaks).reduce((a, b) => a + b.length, 0);

  return (
    <div className="rise">
      <div className="page-h"><div><h1>Model evaluation</h1><p>Measured on a held-out <b>synthetic</b> test split with bootstrap 95% confidence intervals and listed failure cases. These numbers describe the demo, not real-world performance.</p></div></div>
      <div className="banner warn"><AlertTriangle size={20} /><div><b>Optimistic by construction</b><p>Test documents come from the same generator the rules were designed against (one fictional template). Real documents, other issuers, cameras and demographics are untested until authorised data is available.</p></div></div>

      <div className="grid g4" style={{ marginBottom: 18 }}>
        <Card className="kpi"><div className="ic ic-blue"><BarChart3 size={22} /></div><div><div className="v">{d.dataset!.n_documents}</div><div className="l">synthetic documents</div></div></Card>
        <Card className="kpi"><div className="ic ic-green"><BarChart3 size={22} /></div><div><div className="v">{d.dataset!.split.test}</div><div className="l">test (train {d.dataset!.split.train})</div></div></Card>
        <Card className="kpi"><div className="ic ic-violet"><BarChart3 size={22} /></div><div><div className="v">{d.dataset!.n_persons}</div><div className="l">fictional people</div></div></Card>
        <Card className="kpi"><div className="ic ic-amber"><Info size={22} /></div><div><div className="v">{leaks}</div><div className="l">group leaks across split</div></div></Card>
      </div>

      {Object.entries(GROUPS).map(([g, cfg]) => {
        const rows = (d.metrics?.[g] || []).filter(m => cfg.keys.includes(m.id));
        return (
          <div key={g} style={{ marginBottom: 22 }}>
            <h3 style={{ fontSize: 15, margin: "0 0 10px" }}>{cfg.title}</h3>
            <div className="grid g3">{rows.map(m => <MetricCard key={m.id} m={m} />)}</div>
          </div>
        );
      })}

      <Card title="Outcome by scenario" icon={<BarChart3 size={16} />} pad={false}>
        <table className="t"><thead><tr><th>Scenario</th><th>n</th><th>Expected priority</th><th>Matched</th><th>Low / Med / High / Not assessed</th></tr></thead><tbody>
          {d.per_variant!.map(v => (
            <tr key={v.variant}><td style={{ fontWeight: 650 }}>{v.variant.replace(/_/g, " ")}</td><td>{v.n}</td><td><span className="tag">{v.expected_priority}</span></td>
              <td>{(v.priority_match_rate * 100).toFixed(0)}%</td><td className="mono" style={{ fontSize: 12.5 }}>{v.n_low} / {v.n_medium} / {v.n_high} / {v.n_incomplete}</td></tr>
          ))}
        </tbody></table>
      </Card>

      <div className="grid g2" style={{ marginTop: 18 }}>
        <Card title={`Failure cases (${d.failure_cases?.length ?? 0} of ${d.n_failure_cases_total ?? 0})`} icon={<Bug size={16} />} pad={false}>
          {(d.failure_cases || []).slice(0, 8).map((f, i) => (
            <div className="check" key={i} style={{ gridTemplateColumns: "1fr" }}>
              <div><h5>{f.doc_id} <span className="tag">{f.category}</span></h5><p style={{ fontSize: 12.5 }}>{f.note}</p></div>
            </div>
          ))}
        </Card>
        <Card title="Limitations" icon={<Info size={16} />}>
          <ul className="rules" style={{ marginTop: 0 }}>{(d.limitations || []).map((l, i) => <li key={i}><Info size={14} style={{ color: "var(--text-3)" }} /><span>{l}</span></li>)}</ul>
          <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>Generated {d.generated_at?.slice(0, 16).replace("T", " ")} UTC · {d.config?.bootstrap_resamples} bootstrap resamples · {Object.values(d.config?.versions || {}).join(" · ")}</p>
        </Card>
      </div>
    </div>
  );
}
