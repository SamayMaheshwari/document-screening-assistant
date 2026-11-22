import { useState } from "react";
import { Eye, ListChecks } from "lucide-react";
import type { Results, Status } from "../../types";
import { Card, STATUS_META, StatusPill } from "../../ui";
import { DIM_TITLE, regionOf } from "./helpers";

const ORDER = ["capture_quality", "document_integrity", "information_consistency", "document_status", "person_comparison"];

export default function ChecksTab({ r, go }: { r: Results; go: (tab: string, focus?: string) => void }) {
  const [f, setF] = useState<"ALL" | Status>("ALL");
  const counts = r.checks.reduce<Record<string, number>>((a, c) => ({ ...a, [c.status]: (a[c.status] || 0) + 1 }), {});
  const shown = r.checks.filter(c => f === "ALL" || c.status === f);
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="row wrap">
        <div className="seg" style={{ flexWrap: "wrap" }}>
          <button className={f === "ALL" ? "on" : ""} onClick={() => setF("ALL")}>All ({r.checks.length})</button>
          {(Object.keys(STATUS_META) as Status[]).filter(s => counts[s]).map(s => <button key={s} className={f === s ? "on" : ""} onClick={() => setF(s)}>{STATUS_META[s].label} ({counts[s]})</button>)}
        </div>
        <span className="muted" style={{ fontSize: 12.5 }}>Ruleset {r.checks[0]?.rule_version}. Every check records its source, rule version and time.</span>
      </div>
      {ORDER.map(d => {
        const rows = shown.filter(c => c.dimension === d);
        if (!rows.length) return null;
        return (
          <Card key={d} pad={false} title={<span>{DIM_TITLE[d]}</span>} icon={<ListChecks size={16} />}>
            {rows.map(c => {
              const box = regionOf(c);
              return (
                <div className="check" key={c.id}>
                  <div><StatusPill status={c.status} /></div>
                  <div>
                    <h5>{c.title}</h5><p>{c.message}</p>
                    <div className="src">{c.source} · {c.rule_version} · {new Date(c.checked_at).toLocaleTimeString()}</div>
                  </div>
                  <div>{box && (c.status === "FAIL" || c.status === "REVIEW") && <button className="btn sm" onClick={() => go("document", c.id)}><Eye size={13} />On document</button>}</div>
                </div>
              );
            })}
          </Card>
        );
      })}
      {r.face && <Card title="Face verification (1:1)" pad={false}><div className="check"><div><StatusPill status={r.face.comparison} /></div><div><h5>Person-to-document comparison</h5><p>{r.face.message}</p><div className="src">no 1:N search · human fallback · model: {r.face.model_version}</div></div><div /></div></Card>}
    </div>
  );
}
