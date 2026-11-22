import { FormEvent, useState } from "react";
import { Eye, FileSearch, Fingerprint, Loader2, Lock, ScrollText, ShieldCheck, UserCheck } from "lucide-react";
import { useAuth } from "../auth";

const ACCOUNTS = [
  { u: "officer", p: "officer", d: "Screens & reviews" },
  { u: "admin", p: "admin", d: "Oversight" },
  { u: "auditor", p: "auditor", d: "Redacted view" },
];

export default function Login() {
  const { login } = useAuth();
  const [username, setU] = useState("officer");
  const [password, setP] = useState("officer");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e?: FormEvent, u = username, p = password) => {
    e?.preventDefault();
    setBusy(true); setErr("");
    try { await login(u, p); } catch (ex: any) { setErr(ex.message || "Sign-in failed"); } finally { setBusy(false); }
  };

  return (
    <div className="login">
      <div className="login-hero">
        <div>
          <div className="row" style={{ gap: 12 }}>
            <div className="brand-mark"><ShieldCheck size={22} /></div>
            <b style={{ color: "#fff", fontSize: 15 }}>Document Screening Assistant</b>
          </div>
          <h1>Screen travel documents with a <em>transparent evidence trail</em>.</h1>
          <p className="lead">An AI-assisted decision-support tool for document officers. It reads the passport, checks it, and shows exactly what it found and what it could not check. People make every decision.</p>
          <div className="hero-points">
            <div className="hero-point"><div className="ic"><FileSearch size={18} /></div><div><b>Every alert links to its evidence</b><span>Source region, rule, ruleset version and timestamp for each check.</span></div></div>
            <div className="hero-point"><div className="ic"><Fingerprint size={18} /></div><div><b>Fails visibly, never silently</b><span>Unavailable or low-quality checks are shown as such, never turned into a fraud signal.</span></div></div>
            <div className="hero-point"><div className="ic"><UserCheck size={18} /></div><div><b>Human oversight by design</b><span>No automatic acceptance, refusal or accusation. Officer review with recorded rationale.</span></div></div>
            <div className="hero-point"><div className="ic"><ScrollText size={18} /></div><div><b>Tamper-evident audit trail</b><span>Append-only, hash-chained log of every view, edit, review and export.</span></div></div>
          </div>
        </div>
        <div className="login-note">Demonstration build. All documents are synthetic with fictional people and the ICAO test State “UTO”. No real personal data is used or stored.</div>
      </div>
      <div className="login-pane">
        <form className="login-card rise" onSubmit={submit}>
          <h2>Sign in</h2>
          <p className="sub">Use a demo account to explore the officer portal.</p>
          <div className="col" style={{ gap: 14 }}>
            <div><label className="fl">Username</label><input className="input" value={username} onChange={e => setU(e.target.value)} autoFocus autoComplete="username" /></div>
            <div><label className="fl">Password</label><input className="input" type="password" value={password} onChange={e => setP(e.target.value)} autoComplete="current-password" /></div>
            {err && <div className="banner err" style={{ margin: 0, padding: "10px 14px" }}><Lock size={16} /><div>{err}</div></div>}
            <button className="btn primary" disabled={busy} style={{ justifyContent: "center", padding: 12 }}>{busy ? <Loader2 size={16} className="spin" /> : <Lock size={16} />}Sign in</button>
          </div>
          <div className="acct">
            {ACCOUNTS.map(a => (
              <button type="button" key={a.u} onClick={() => { setU(a.u); setP(a.p); submit(undefined, a.u, a.p); }}>
                <b>{a.u}</b><small>{a.d}</small>
              </button>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 18, textAlign: "center" }}><Eye size={12} style={{ verticalAlign: -2 }} /> Stubbed login for the demo. Production would use an approved identity provider with MFA.</p>
        </form>
      </div>
    </div>
  );
}
