import { useCallback, useEffect, useRef, useState } from "react";

export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

/** Tiny fetch hook: {data, error, reload}. */
export function useApi<T>(path: string | null, deps: any[] = [], pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    if (!path) return;
    get<T>(path)
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(String(e?.message || e)); });
    let iv: any = 0;
    if (pollMs > 0) iv = setInterval(reload, pollMs);
    return () => { alive = false; clearInterval(iv); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  return { data, error, reload, setData };
}

export type StreamEvent = { kind: string; data: any; at: number };

/** SSE subscription to /api/stream. Returns recent events (newest first) + connection state. */
export function useStream(maxKeep = 60, onEvent?: (ev: StreamEvent) => void) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.addEventListener("hello", () => setConnected(true));
    const push = (kind: string) => (e: MessageEvent) => {
      let data: any = {};
      try { data = JSON.parse(e.data); } catch { /* ignore */ }
      const ev = { kind, data, at: Date.now() };
      setEvents((prev) => [ev, ...prev].slice(0, maxKeep));
      cbRef.current?.(ev);
    };
    es.addEventListener("journal", push("journal"));
    es.addEventListener("receipt", push("receipt"));
    es.onerror = () => setConnected(false);
    return () => es.close();
  }, [maxKeep]);

  return { events, connected };
}
