import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, FileImage, Loader2, ShieldCheck, UploadCloud, X } from "lucide-react";
import { api } from "../api";
import { Card, useToast } from "../ui";

export default function NewCase() {
  const nav = useNavigate();
  const toast = useToast();
  const inp = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [over, setOver] = useState(false);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const pick = (f?: File | null) => {
    setErr("");
    if (!f) return;
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };
  const submit = async () => {
    if (!file) return;
    setBusy(true); setErr("");
    const fd = new FormData();
    fd.append("file", file);
    if (label.trim()) fd.append("label", label.trim());
    try {
      const r = await api.upload<{ case_id: string; case_number: string }>("/cases", fd);
      toast("ok", `Case ${r.case_number} created — processing`);
      nav(`/cases/${r.case_id}`);
    } catch (e: any) {
      setErr(e.message);
      setBusy(false);
    }
  };

  return (
    <div className="rise">
      <div className="page-h"><div><h1>New screening</h1><p>Upload a passport data-page image. The original is hashed and preserved unchanged; all analysis uses a separate derived copy.</p></div></div>
      <div className="grid g-main">
        <Card>
          {!file ? (
            <div className={`drop ${over ? "over" : ""}`} onClick={() => inp.current?.click()}
              onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={e => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files?.[0]); }}>
              <div className="big-ic"><UploadCloud size={30} /></div>
              <h3>Drop a document image here</h3>
              <p>or click to browse · JPEG or PNG · up to 12 MB</p>
              <input ref={inp} type="file" accept="image/jpeg,image/png" hidden onChange={e => pick(e.target.files?.[0])} />
            </div>
          ) : (
            <div className="preview">
              <img src={preview} alt="Upload preview" />
              <div className="col">
                <div className="row spread"><b className="row"><FileImage size={16} />{file.name}</b><button className="btn sm" onClick={() => { setFile(null); setErr(""); }}><X size={14} />Remove</button></div>
                <div className="muted" style={{ fontSize: 12.5 }}>{(file.size / 1024).toFixed(0)} KB · {file.type || "unknown type"}</div>
                <div><label className="fl">Case label (optional)</label><input className="input" placeholder="e.g. Counter 3 – morning shift" value={label} onChange={e => setLabel(e.target.value)} maxLength={120} /></div>
                {err && <div className="banner err" style={{ margin: 0 }}><X size={16} /><div><b>Upload rejected</b><p>{err}</p></div></div>}
                <button className="btn primary" style={{ justifyContent: "center", padding: 12 }} disabled={busy} onClick={submit}>{busy ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}Start screening</button>
              </div>
            </div>
          )}
          {err && !file && <div className="banner err" style={{ marginTop: 14 }}><X size={16} /><div>{err}</div></div>}
        </Card>
        <Card title="What happens on upload" icon={<ShieldCheck size={16} />}>
          <ul className="rules">
            <li><CheckCircle2 size={15} /><span>The <b>real file signature</b> is checked (extensions are not trusted), plus size, decode and pixel limits.</span></li>
            <li><CheckCircle2 size={15} /><span>A <b>SHA-256</b> of the original is stored; the original file is never modified.</span></li>
            <li><CheckCircle2 size={15} /><span><b>Quality gate:</b> blur, glare, resolution and crop are measured. Poor captures trigger a recapture request instead of unreliable results.</span></li>
            <li><CheckCircle2 size={15} /><span>OCR + <b>ICAO 9303 MRZ</b> parsing, cross-checks, date rules, baseline forensics.</span></li>
            <li><CheckCircle2 size={15} /><span>Unavailable or inconclusive checks are listed as such — <b>never as fraud signals</b>.</span></li>
          </ul>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 16 }}>Demo only: please upload synthetic documents. Don’t upload real people’s identity documents to this prototype. Need samples? Use the Demo lab.</p>
        </Card>
      </div>
    </div>
  );
}
