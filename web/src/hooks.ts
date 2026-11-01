import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type State<T> = { data: T | undefined; error: unknown; loading: boolean };

// GET a path, optionally keep it fresh. Polling pauses while the tab is
// hidden, there's no point refreshing a board nobody is looking at.
export function useApi<T>(path: string | null, opts: { every?: number } = {}) {
  const [state, setState] = useState<State<T>>({ data: undefined, error: null, loading: true });
  const current = useRef(path);
  current.current = path;

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const data = await api.get<T>(path);
      if (current.current === path) setState({ data, error: null, loading: false });
    } catch (error) {
      if (current.current === path) setState((s) => ({ ...s, error, loading: false }));
    }
  }, [path]);

  useEffect(() => {
    setState((s) => ({ ...s, loading: true }));
    load();
    if (!opts.every) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, opts.every);
    return () => window.clearInterval(id);
  }, [load, opts.every]);

  return { ...state, reload: load };
}

// re-render every few seconds so "in 4m" style labels keep moving
export function useNow(ms = 5000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}
