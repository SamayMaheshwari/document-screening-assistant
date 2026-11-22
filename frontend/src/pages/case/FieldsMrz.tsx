import { useState } from "react";
import { AlertCircle, Check, Equal, HelpCircle, Pencil, ScanText, X } from "lucide-react";
import { api } from "../../api";
import type { Field, Results } from "../../types";
import { Card, ConfBar, StatusPill, useToast } from "../../ui";

const DIGIT_POS: Record<string, number> = { passport_number: 9, date_of_birth: 19, date_of_expiry: 27, personal_number: 42, composite: 43 };
const DIGIT_LABEL: Record<string, string> = { passport_number: "Passport no.", date_of_birth: "Date of birth", date_of_expiry: "Date of expiry", personal_number: "Personal no.", composite: "Composite" };
const XC: { label: string; viz: string; mrz: string; check: string }[] = [
  { label: "Surname", viz: "surname", mrz: "surname", check: "xc_surname" },
  { label: "Given names", viz: "given_names", mrz: "given_names", check: "xc_given_names" },
  { label: "Date of birth", viz: "date_of_birth", mrz: "date_of_birth", check: "xc_dob" },
  { label: "Date of expiry", viz: "date_of_expiry", mrz: "date_of_expiry", check: "xc_expiry" },
  { label: "Passport number", viz: "passport_number", mrz: "passport_number", check: "xc_number" },
  { label: "Sex", viz: "sex", mrz: "sex", check: "xc_sex" },
  { label: "Nationality", viz: "nationality", mrz: "nationality", check: "xc_nationality" },
  { label: "Issuing State", viz: "issuer_code", mrz: "issuer", check: "xc_issuer" },
];

function MrzLine({ text, line, r }: { text: string; line: 1 | 2; r: Results }) {
  const mrz = r.mrz!;
  const digitState: Record<number, boolean> = {};
  if (line === 2) for (const d of mrz.digit_checks) digitState[DIGIT_POS[d.name]] = d.valid;
  const fixes = new Set(mrz.repairs.filter(x => x.line === line && x.from.length === 1).map(x => x.position));
  return <div className="mrz-line">{text.split("").map((ch, i) => <span key={i} className={digitState[i] === true ? "ok" : digitState[i] === false ? "bad" : fixes.has(i) ? "fix" : ""}>{ch}</span>)}</div>;
}

export default function FieldsMrz({ r, canEdit, reload }: { r: Results; canEdit: boolean; reload: () => void }) {
  const toast = useToast();
  const [editing, setEditing] = useState<Field | null>(null);
  const [val, setVal] = useState("");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const viz = r.fields.filter(f => f.source === "VIZ");
  const mrzFields = r.fields.filter(f => f.name.startsWith("mrz_line"));
  const mrz = r.mrz;
  const vizBy = Object.fromEntries(viz.map(f => [f.name, f]));
  const checkBy = Object.fromEntries(r.checks.map(c => [c.id, c]));

  const start = (f: Field) => { setEditing(f); setVal(f.corrected_value ?? (f.source === "MRZ" ? (r.mrz?.lines[f.name === "mrz_line1" ? 0 : 1] ?? "") : f.raw)); setWhy(""); };
  const save = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      const res = await api.patch<{ check_changes: Record<string, { from: string | null; to: string }> }>(`/cases/${r.case.id}/fields/${editing.id}`, { value: val, reason: why });
      const n = Object.keys(res.check_changes).length;
      toast("ok", n ? `Correction saved — ${n} check result(s) changed` : "Correction saved — no check results changed");
      setEditing(null);
      reload();
    } catch (e: any) { toast("err", e.message); } finally { setBusy(false); }
  };

  if (r.fields.length === 0) return <div className="empty card"><ScanText size={28} /><h4>No fields extracted</h4><p>OCR did not run for this capture (quality gate failed).</p></div>;

  return (
    <div className="col" style={{ gap: 18 }}>
      <Card title="Machine readable zone (ICAO 9303 · TD3)" icon={<ScanText size={16} />} right={mrz && <StatusPill status={mrz.format_ok ? (mrz.digit_checks.every(d => d.valid) ? "PASS" : "FAIL") : "REVIEW"} />}>
        {mrz ? <>
          <div className="mrz-box"><MrzLine text={mrz.lines[0]} line={1} r={r} /><MrzLine text={mrz.lines[1]} line={2} r={r} /></div>
          <div className="mrz-cap">
            <span><i style={{ background: "rgba(74,222,128,.5)" }} />check digit valid</span><span><i style={{ background: "#dc2626" }} />check digit invalid</span>
            <span><i style={{ outline: "1px dashed #fbbf24" }} />OCR normalisation applied</span>
            {mrz.repairs.length > 0 && <span>{mrz.repairs.length} normalisation(s): {mrz.repairs.map(x => x.expected.includes("filler") ? "filler run" : `${x.from}→${x.to}`).join(", ")}</span>}
          </div>
          <div className="digit-grid" style={{ marginTop: 16 }}>
            {mrz.digit_checks.map(d => (
              <div key={d.name} className={`digit ${d.valid ? "" : "bad"}`}>
                <b>{DIGIT_LABEL[d.name]}</b>
                <div className="big">{d.printed}{!d.valid && <small>expected {d.computed}</small>}{d.valid && <Check size={16} color="var(--pass)" />}</div>
                <small>{d.valid ? "matches algorithm" : "mismatch"}</small>
              </div>
            ))}
          </div>
          {mrz.errors.length > 0 && <div className="banner warn" style={{ marginTop: 14, marginBottom: 0 }}><AlertCircle size={18} /><div><b>Structure problems</b><p>{mrz.errors.join(" ")}</p></div></div>}
          {canEdit && <div className="row" style={{ marginTop: 14 }}>{mrzFields.map(f => <button key={f.id} className="btn sm" onClick={() => start(f)}><Pencil size={12} />Correct line {f.name.slice(-1)}</button>)}<span className="muted" style={{ fontSize: 12 }}>OCR may misread a character — a correction re-runs every dependent check and is audited.</span></div>}
        </> : <p className="muted">No MRZ was read.</p>}
      </Card>

      {mrz?.parsed && (
        <Card title="Visual zone vs MRZ cross-check" icon={<Equal size={16} />} pad={false}>
          <div className="cmp">
            <div className="h">Field</div><div className="h">Visual zone (OCR)</div><div className="h">MRZ (decoded)</div><div className="h"></div>
            {XC.map(x => {
              const v = vizBy[x.viz];
              const c = checkBy[x.check];
              const ok = c?.status === "PASS";
              return [
                <div key={x.label + "a"} style={{ fontWeight: 650 }}>{x.label}</div>,
                <div key={x.label + "b"} className="mono" style={{ fontSize: 12.5, color: c && !ok ? "var(--fail)" : undefined }}>{v?.corrected_value ?? v?.value ?? v?.raw ?? "—"}</div>,
                <div key={x.label + "c"} className="mono" style={{ fontSize: 12.5 }}>{r.mrz!.parsed![x.mrz] || "—"}</div>,
                <div key={x.label + "d"} title={c?.message}>{!c ? <HelpCircle size={17} color="var(--text-3)" /> : ok ? <Check size={17} color="var(--pass)" /> : c.status === "FAIL" ? <X size={17} color="var(--fail)" /> : <AlertCircle size={17} color={c.status === "REVIEW" ? "var(--review)" : "var(--inconc)"} />}</div>,
              ];
            })}
          </div>
        </Card>
      )}

      <Card title="Visual inspection zone fields" icon={<ScanText size={16} />} pad={false}>
        <table className="t"><thead><tr><th>Field</th><th>Value</th><th>Raw OCR text</th><th>Confidence</th><th>Engine</th>{canEdit && <th></th>}</tr></thead><tbody>
          {viz.map(f => (
            <tr key={f.id}>
              <td style={{ fontWeight: 650 }}>{f.label}{f.needs_review && !f.corrected_value && <span className="incomplete-tag" style={{ marginLeft: 8, color: "var(--review)", background: "var(--review-bg)" }}>verify</span>}</td>
              <td><span className={`val ${f.corrected_value ? "corr" : ""}`}>{f.corrected_value ?? f.value ?? <span className="muted">unreadable</span>}</span>
                {f.corrections.map((c, i) => <div key={i} className="cell-sub">Corrected by {c.officer}: “{c.previous}” → “{c.new}” — {c.reason}</div>)}</td>
              <td className="raw">{f.raw || "—"}</td>
              <td><ConfBar v={f.confidence} /></td>
              <td className="cell-sub">{f.engine} {f.engine_version}</td>
              {canEdit && <td><button className="btn sm" onClick={() => start(f)}><Pencil size={12} />Correct</button></td>}
            </tr>
          ))}
        </tbody></table>
      </Card>

      {editing && (
        <div className="modal-bg" onClick={() => !busy && setEditing(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Correct “{editing.label}”</h3>
            <p className="muted" style={{ margin: "0 0 14px" }}>The OCR value is kept in the history. Dependent checks are re-run and the change is written to the audit log.</p>
            <label className="fl">Corrected value</label>
            <input className="input mono" value={val} onChange={e => setVal(e.target.value)} />
            <label className="fl" style={{ marginTop: 12 }}>Reason (required)</label>
            <input className="input" placeholder="e.g. Verified against the original image" value={why} onChange={e => setWhy(e.target.value)} />
            <div className="row" style={{ marginTop: 18, justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setEditing(null)} disabled={busy}>Cancel</button>
              <button className="btn primary" disabled={busy || why.trim().length < 3} onClick={save}>Save correction</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
