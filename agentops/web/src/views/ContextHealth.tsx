import React, { useState } from "react";
import { useApi } from "../lib/api";
import { Chip } from "../components/bits";
import { Gauge } from "../components/charts2";
import { fmtNum, fmtPct, timeAgo, shortId } from "../lib/format";

type Snap = {
  session_id: string; at: number; model?: string; context_window?: number; used_tokens?: number;
  usage_percent?: number; usage_pressure_active?: boolean; threshold_percent?: number;
  compaction?: { events: number; tokens_reclaimed: number; micro_events: number };
  prompt_cache?: { hit_ratio: number; breaks: number; peak_prefix_tokens: number };
  stable_prefix_invalidations?: number;
  context_breakdown?: { layers: Record<string, number>; total_tokens: number };
};

export default function ContextHealth() {
  const { data } = useApi<{ sessions: Snap[] }>("/api/context/sessions", [], 5000);
  const snaps = data?.sessions ?? [];
  const [sel, setSel] = useState<string | null>(null);
  const cur = snaps.find((s) => s.session_id === sel) ?? snaps[0];
  const hist = useApi<{ history: Snap[] }>(cur ? `/api/context/${cur.session_id}/history` : null, [cur?.session_id]);

  const layers = cur?.context_breakdown?.layers ?? {};
  const layerRows = Object.entries(layers).sort((a, b) => b[1] - a[1]);
  const maxLayer = Math.max(...layerRows.map(([, v]) => v), 1);

  return (
    <>
      <div className="pagehead">
        <h1>Context Health</h1>
        <span className="sub">get_status() snapshots — window pressure, compaction, prompt cache, layer breakdown</span>
      </div>

      {snaps.length === 0 && (
        <div className="card muted">
          No context snapshots yet. Live: configure <code>CRUSORAI_OPS_ENGINE_URL</code> (proxies the engine's
          <code> /api/context/status</code>) or run the demo simulator which journals <code>context_status</code> rows.
        </div>
      )}

      {cur && (
        <>
          <div className="toolbar">
            <select value={cur.session_id} onChange={(e) => setSel(e.target.value)}>
              {snaps.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {shortId(s.session_id, 18)} · {timeAgo(s.at)}
                </option>
              ))}
            </select>
            {cur.usage_pressure_active ? <Chip tone="err">pressure active</Chip> : <Chip tone="ok">within budget</Chip>}
            {cur.prompt_cache && cur.prompt_cache.breaks > 0 && <Chip tone="warn">{cur.prompt_cache.breaks} cache-breaks</Chip>}
            <span className="muted">snapshot {timeAgo(cur.at)} · model {cur.model}</span>
          </div>

          <div className="grid cols-3">
            <div className="card" style={{ display: "flex", gap: 18, alignItems: "center", justifyContent: "center" }}>
              <Gauge value={cur.usage_percent ?? null} label="window used" warn={cur.threshold_percent ?? 75} />
              <div>
                <div className="muted" style={{ fontSize: 12 }}>used / window</div>
                <div className="num" style={{ fontSize: 18 }}>{fmtNum(cur.used_tokens)} / {fmtNum(cur.context_window)}</div>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>threshold {cur.threshold_percent}%</div>
              </div>
            </div>

            <div className="card">
              <h3>Compaction</h3>
              <table className="tbl">
                <tbody>
                  <tr><td className="muted">events</td><td className="num">{cur.compaction?.events ?? 0}</td></tr>
                  <tr><td className="muted">tokens reclaimed</td><td className="num">{fmtNum(cur.compaction?.tokens_reclaimed)}</td></tr>
                  <tr><td className="muted">micro-compactions</td><td className="num">{cur.compaction?.micro_events ?? 0}</td></tr>
                  <tr><td className="muted">prefix invalidations</td><td className="num">{cur.stable_prefix_invalidations ?? 0}</td></tr>
                </tbody>
              </table>
            </div>

            <div className="card">
              <h3>Prompt cache</h3>
              <table className="tbl">
                <tbody>
                  <tr><td className="muted">hit ratio</td><td className="num">{fmtPct(cur.prompt_cache?.hit_ratio ?? null)}</td></tr>
                  <tr><td className="muted">breaks</td><td className="num" style={{ color: (cur.prompt_cache?.breaks ?? 0) ? "var(--warn)" : undefined }}>{cur.prompt_cache?.breaks ?? 0}</td></tr>
                  <tr><td className="muted">peak prefix</td><td className="num">{fmtNum(cur.prompt_cache?.peak_prefix_tokens)}</td></tr>
                </tbody>
              </table>
              <h3 style={{ marginTop: 12 }}>Usage history</h3>
              <div className="muted num" style={{ fontSize: 11.5 }}>
                {(hist.data?.history ?? []).slice(-8).map((hSnap) => hSnap.usage_percent?.toFixed(0)).join(" → ") || "—"} %
              </div>
            </div>
          </div>

          <div className="card" style={{ marginTop: 14 }}>
            <h3>Layer breakdown ({fmtNum(cur.context_breakdown?.total_tokens)} tok)</h3>
            {layerRows.map(([name, v]) => (
              <div className="hbar" key={name}>
                <div className="mono">{name}</div>
                <div className="track"><div className="fill" style={{ width: `${(v / maxLayer) * 100}%` }} /></div>
                <div className="val">{fmtNum(v)}</div>
              </div>
            ))}
            {layerRows.length === 0 && <div className="muted">no breakdown in snapshot</div>}
          </div>
        </>
      )}
    </>
  );
}
