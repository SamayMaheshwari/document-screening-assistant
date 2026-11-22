import type { Check, Results } from "../../types";

export type Box = number[]; // [x, y, w, h] in the rectified 1250x880 frame

export function regionOf(c: Check): Box | null {
  const e = c.evidence || {};
  if (Array.isArray(e.region) && e.region.length === 4) return e.region as Box;
  if (Array.isArray(e.regions) && e.regions[0]?.box) return e.regions[0].box as Box;
  return null;
}

export interface Flag { id: string; box: Box; title: string; status: string; message: string }

export function flagsOf(r: Results): Flag[] {
  const out: Flag[] = [];
  const seen = new Set<string>();
  const add = (f: Flag) => { const k = f.box.join(","); if (!seen.has(k)) { seen.add(k); out.push(f); } };
  for (const c of r.checks) {
    if (c.status !== "FAIL" && c.status !== "REVIEW") continue;
    if (c.id === "forensics_ela") continue; // shown per-zone below
    const b = regionOf(c);
    if (b) add({ id: c.id, box: b, title: c.title, status: c.status, message: c.message });
  }
  for (const f of r.forensics?.findings || []) {
    if (f.status === "REVIEW") add({ id: `ela_${f.zone}`, box: f.region, title: `ELA anomaly: ${f.zone.replace(/_/g, " ")}`, status: "REVIEW", message: f.message });
  }
  return out;
}

export const DIM_ICON_ORDER = ["document_integrity", "information_consistency", "document_status", "person_comparison"];
export const DIM_TITLE: Record<string, string> = {
  capture_quality: "Capture quality", document_integrity: "Document integrity", information_consistency: "Information consistency",
  document_status: "Document status", person_comparison: "Person-to-document comparison",
};
export const ZONE_LABEL = (z: string) => z.replace(/_/g, " ").replace(/^./, c => c.toUpperCase());
