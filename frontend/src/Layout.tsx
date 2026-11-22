import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BarChart3, FlaskConical, FolderOpen, Info, LayoutDashboard, LogOut, Moon, PlusCircle, ScrollText, ShieldCheck, Sun } from "lucide-react";
import { useAuth } from "./auth";
import { api } from "./api";
import type { Stats } from "./types";

export default function Layout() {
  const { user, logout, can } = useAuth();
  const nav = useNavigate();
  const [attn, setAttn] = useState(0);
  const [dark, setDark] = useState(() => { try { return localStorage.getItem("dsa_theme") === "dark"; } catch { return false; } });

  useEffect(() => {
    const root = document.documentElement;
    let saved: string | null = null;
    try { saved = localStorage.getItem("dsa_theme"); } catch { /* ignore */ }
    if (saved) root.setAttribute("data-theme", saved);
  }, []);
  const toggleTheme = () => {
    const next = dark ? "light" : "dark";
    setDark(!dark);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("dsa_theme", next); } catch { /* ignore */ }
  };
  useEffect(() => {
    const load = () => api.get<Stats>("/stats").then(s => setAttn(s.needs_attention)).catch(() => {});
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, []);

  const initials = (user?.name || "?").split(" ").filter(w => !/^(Officer|Admin|Auditor)$/.test(w)).map(w => w[0]).slice(0, 2).join("");
  return (
    <div className="shell">
      <div className="demo-strip"><b>DEMO PROTOTYPE</b> · Synthetic, fictional data only (state code UTO) · Decision-support tool — officers make every decision</div>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><ShieldCheck size={22} /></div>
          <div><b>Document Screening<br />Assistant</b><span>Evidence trail</span></div>
        </div>
        <nav className="nav">
          <NavLink to="/" end><LayoutDashboard size={18} /><span>Dashboard</span></NavLink>
          <NavLink to="/cases" end><FolderOpen size={18} /><span>Case queue</span>{attn > 0 && <em className="badge" style={{ fontStyle: "normal" }}>{attn}</em>}</NavLink>
          {can("case:create") && <NavLink to="/cases/new"><PlusCircle size={18} /><span>New screening</span></NavLink>}
          <div className="nav-sec">Demonstration</div>
          <NavLink to="/demo"><FlaskConical size={18} /><span>Demo lab</span></NavLink>
          <NavLink to="/evaluation"><BarChart3 size={18} /><span>Model evaluation</span></NavLink>
          <div className="nav-sec">Governance</div>
          {can("audit:read") && <NavLink to="/audit"><ScrollText size={18} /><span>Audit log</span></NavLink>}
          <NavLink to="/about"><Info size={18} /><span>About & limits</span></NavLink>
        </nav>
        <div className="side-foot">
          <div className="user-chip"><div className="avatar">{initials}</div><div><b>{user?.name}</b><small>{user?.role}</small></div></div>
          <div className="side-btns">
            <button className="ghost-btn" onClick={toggleTheme} title="Toggle theme">{dark ? <Sun size={15} /> : <Moon size={15} />}<span>{dark ? "Light" : "Dark"}</span></button>
            <button className="ghost-btn" onClick={() => { logout(); nav("/"); }}><LogOut size={15} /><span>Sign out</span></button>
          </div>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}
