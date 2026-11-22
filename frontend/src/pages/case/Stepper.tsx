import { Check, Loader2, Minus, X } from "lucide-react";
import type { Step } from "../../types";

export function Stepper({ steps, compact }: { steps: Step[]; compact?: boolean }) {
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <div className={`step ${s.status}`} key={s.key}>
          <div className="dot">{s.status === "done" ? <Check size={13} /> : s.status === "running" ? <Loader2 size={13} className="spin" /> : s.status === "failed" ? <X size={13} /> : s.status === "skipped" ? <Minus size={13} /> : <span style={{ fontSize: 10, fontWeight: 700 }}>{i + 1}</span>}</div>
          <div><b>{s.label}</b>{(s.detail && (!compact || s.status !== "pending")) && <small>{s.detail}</small>}</div>
          <span className="muted" style={{ fontSize: 11.5, fontFamily: "var(--mono)" }}>{s.at || ""}</span>
        </div>
      ))}
    </div>
  );
}
