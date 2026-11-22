const TOKEN_KEY = "dsa_token";

export const getToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
export const setToken = (t: string) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } };

export class ApiError extends Error {
  status: number; code?: string;
  constructor(status: number, message: string, code?: string) { super(message); this.status = status; this.code = code; }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = getToken();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(`/api/v1${path}`, { ...init, headers });
  if (res.status === 401 && !path.startsWith("/auth/login")) { setToken(""); window.dispatchEvent(new Event("dsa-logout")); }
  if (!res.ok) {
    let msg = res.statusText, code: string | undefined;
    try {
      const j = await res.json();
      const d = j.detail;
      if (typeof d === "string") msg = d;
      else if (d?.message) { msg = d.message; code = d.code; }
      else if (Array.isArray(d)) msg = d.map((x: any) => x.msg).join("; ");
    } catch { /* ignore */ }
    throw new ApiError(res.status, msg, code);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : (res.blob() as unknown)) as Promise<T>;
}

export const api = {
  get: <T,>(p: string) => request<T>(p),
  post: <T,>(p: string, body?: unknown) => request<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T,>(p: string, body: unknown) => request<T>(p, { method: "PATCH", body: JSON.stringify(body) }),
  upload: <T,>(p: string, form: FormData) => request<T>(p, { method: "POST", body: form }),
  blob: (p: string) => request<Blob>(p),
};

export const imgUrl = (caseId: string, kind: "original" | "rectified" | "heatmap", v: string | number = "", log = false) =>
  `/api/v1/cases/${caseId}/image?kind=${kind}&token=${encodeURIComponent(getToken())}&v=${v}${log ? "&log=1" : ""}`;
export const sampleImgUrl = (id: string) => `/api/v1/demo/samples/${id}/image?token=${encodeURIComponent(getToken())}`;

export async function downloadBlob(path: string, filename: string) {
  const blob = await api.blob(path);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
