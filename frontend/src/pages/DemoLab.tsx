import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download, FlaskConical, Info, Loader2, Play, Target } from "lucide-react";
import { api, downloadBlob, sampleImgUrl } from "../api";
import { useAuth } from "../auth";
import type { Sample } from "../types";
import { Card, Spinner, useToast } from "../ui";

export default function DemoLab() {
  const nav = useNavigate();
  const { can } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState<Sample[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { api.get<{ items: Sample[] }>("/demo/samples").then(r => setItems(r.items)); }, []);
  const run = async (id: string) => {
    setBusy(id);
    try {
      const r = await api.post<{ case_id: string; case_number: string }>(`/demo/samples/${id}/submit`);
      toast("ok", `Case ${r.case_number} created from sample`);
      nav(`/cases/${r.case_id}`);
    } catch (e: any) { toast("err", e.message); setBusy(null); }
  };
  if (!items) return <div style={{ display: "grid", placeItems: "center", height: 300 }}><Spinner size={28} /></div>;
  const core = items.filter(i => i.core);
  const more = items.filter(i => !i.core);

  const Tile = ({ s, n }: { s: Sample; n?: number }) => (
    <Card className="sample" pad={false}>
      <div className="thumb"><img src={sampleImgUrl(s.id)} alt={s.title} loading="lazy" />{n && <span className="num">{n}</span>}</div>
      <div className="body">
        <h4>{s.title}</h4>
        <p className="expected"><Target size={13} style={{ flex: "none", marginTop: 3 }} /><span><b>Expect:</b> {s.expected}</span></p>
        <div className="row">
          <button className="btn primary sm" disabled={!can("case:create") || !!busy} onClick={() => run(s.id)}>{busy === s.id ? <Loader2 size={13} className="spin" /> : <Play size={13} />}Screen this sample</button>
          <button className="btn sm" onClick={() => downloadBlob(`/demo/samples/${s.id}/download`, `demo_${s.id}.jpg`)} title="Download to test the upload flow"><Download size={13} /></button>
        </div>
      </div>
    </Card>
  );

  return (
    <div className="rise">
      <div className="page-h"><div><h1>Demo lab</h1><p>Synthetic passports for a guided walk-through. Everything here is fictional: invented people, the ICAO test State “UTO”, illustrated portraits, and a visible “DEMO - SYNTHETIC DATA” banner.</p></div></div>
      {!can("case:create") && <div className="banner warn"><Info size={18} /><div>Your role cannot create cases. Sign in as <b>officer</b> to run samples.</div></div>}
      <div className="row" style={{ marginBottom: 14 }}><FlaskConical size={18} color="var(--brand)" /><h3 style={{ fontSize: 16 }}>The demo script — five cases, in order</h3></div>
      <div className="samples" style={{ marginBottom: 30 }}>{core.map((s, i) => <Tile key={s.id} s={s} n={i + 1} />)}</div>
      <div className="row" style={{ marginBottom: 14 }}><h3 style={{ fontSize: 16 }}>More tampering and capture scenarios</h3></div>
      <div className="samples">{more.map(s => <Tile key={s.id} s={s} />)}</div>
    </div>
  );
}
