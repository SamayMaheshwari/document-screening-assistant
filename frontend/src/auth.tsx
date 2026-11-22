import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { api, getToken, setToken } from "./api";
import type { User } from "./types";

interface Ctx { user: User | null; loading: boolean; login: (u: string, p: string) => Promise<void>; logout: () => void; can: (perm: string) => boolean }
const AuthCtx = createContext<Ctx>(null as unknown as Ctx);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) { setLoading(false); return; }
    api.get<User>("/auth/me").then(setUser).catch(() => setToken("")).finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    const h = () => setUser(null);
    window.addEventListener("dsa-logout", h);
    return () => window.removeEventListener("dsa-logout", h);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const r = await api.post<{ token: string; user: User }>("/auth/login", { username, password });
    setToken(r.token);
    setUser(r.user);
  }, []);
  const logout = useCallback(() => { setToken(""); setUser(null); }, []);
  const can = useCallback((p: string) => !!user?.permissions.includes(p), [user]);
  return <AuthCtx.Provider value={{ user, loading, login, logout, can }}>{children}</AuthCtx.Provider>;
}
