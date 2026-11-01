import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, setCsrf } from "./api";
import type { Me } from "./types";

type Session = {
  status: "loading" | "setup" | "anonymous" | "ready";
  me: Me | null;
  signedIn: (me: Me) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Session["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { needs_setup } = await api.get<{ needs_setup: boolean }>("/setup");
      if (needs_setup) {
        setStatus("setup");
        return;
      }
      const who = await api.get<Me>("/auth/me");
      setCsrf(who.csrf_token);
      setMe(who);
      setStatus("ready");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setMe(null);
        setStatus("anonymous");
      } else {
        throw err;
      }
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signedIn = useCallback((who: Me) => {
    setCsrf(who.csrf_token);
    setMe(who);
    setStatus("ready");
  }, []);

  const signOut = useCallback(async () => {
    await api.post("/auth/logout").catch(() => undefined);
    setCsrf(null);
    setMe(null);
    setStatus("anonymous");
  }, []);

  return <Ctx.Provider value={{ status, me, signedIn, signOut, refresh }}>{children}</Ctx.Provider>;
}

export function useSession() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}

// only follow "next" if it's a plain path on this site, never //evil.com or \evil.com
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/";
  return next;
}
