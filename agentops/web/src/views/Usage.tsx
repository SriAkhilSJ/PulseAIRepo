import React, { useState } from "react";
import { useApi } from "../lib/api";
import { HBars, KpiCard } from "../components/bits";
import { fmtNum, fmtUsd, fmtPct, fmtDur } from "../lib/format";
import type { SeriesPoint, SummaryRow, ToolStat } from "../lib/types";

const GROUPS = ["day", "model", "provider", "mode", "task", "session"] as const;

export default function Usage() {
  const [groupBy, setGroupBy] = useState<(typeof GROUPS)[number]>("day");
  const [days, setDays] = useState(7);
  const sum = useApi<{ rows: SummaryRow[] }>(`/api/usage/summary?group_by=${groupBy}&days=${days}`, [groupBy, days]);
  const ser = useApi<{ series: SeriesPoint[] }>(`/api/usage/series?days=${days}`, [days]);
  const trn = useApi<{ turns: any[] }>(`/api/usage/turns?days=${days}&limit=200`, [days]);
  const tls = useApi<{ tools: ToolStat[] }>(`/api/tools/stats?days=${days}`, [days]);

  const rows = sum.data?.rows ?? [];
  const totCost = rows.reduce((a, r) => a + r.cost_usd, 0);
  const totTok = rows.reduce((a, r) => a + r.tokens, 0);
  const totCache = rows.reduce((a, r) => a + r.cache_tokens, 0);

  return (
    <>
      <div className="pagehead">
        <h1>Usage & Cost</h1>
        <span className="sub">Σ tokens × cost/token — receipts sink (S1) + router transparency (S8)</span>
      </div>

      <div className="toolbar">
        <div className="seg">
          {GROUPS.map((g) => <button key={g} className={groupBy === g ? "on" : ""} onClick={() => setGroupBy(g)}>{g}</button>)}
        </div>
        <div className="seg">
          {[1, 7, 30].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d}d</button>)}
        </div>
      </div>

      <div className="grid kpis" style={{ gridTemplateColumns: "repeat(4,1fr)" }}>
        <KpiCard label={`Spend (${days}d)`} value={fmtUsd(totCost)} />
        <KpiCard label={`Tokens (${days}d)`} value={fmtNum(totTok)} />
        <KpiCard label="Cache-hit ratio" value={fmtPct(totTok ? totCache / totTok : null)} chrome={false} />
        <KpiCard label="Turns" value={fmtNum(trn.data?.turns.length)} chrome={false} />
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Cost by {groupBy}</h3>
          <HBars rows={rows.map((r) => ({ label: r.key, value: r.cost_usd }))} fmt={fmtUsd} />
        </div>
        <div className="card">
          <h3>Tool leaderboard ({days}d)</h3>
          <table className="tbl">
            <thead><tr><th>tool</th><th>calls</th><th>failures</th><th>avg latency</th></tr></thead>
            <tbody>
              {(tls.data?.tools ?? []).map((t) => (
                <tr key={t.tool}>
                  <td><code>{t.tool}</code></td>
                  <td className="num">{t.calls}</td>
                  <td className="num" style={{ color: t.failures ? "var(--err)" : undefined }}>{t.failures}</td>
                  <td className="num muted">{fmtDur(t.avg_latency_s)}</td>
                </tr>
              ))}
              {(tls.data?.tools ?? []).length === 0 && <tr><td colSpan={4} className="muted">no tool intents journaled</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14, padding: 0 }}>
        <table className="tbl">
          <thead>
            <tr><th>{groupBy}</th><th>turns</th><th>tokens</th><th>cache</th><th>cache-hit</th><th>avg dur</th><th>errors</th><th>cost</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td className="mono">{r.key}</td>
                <td className="num">{r.turns}</td>
                <td className="num">{fmtNum(r.tokens)}</td>
                <td className="num muted">{fmtNum(r.cache_tokens)}</td>
                <td className="num">{fmtPct(r.cache_hit_ratio)}</td>
                <td className="num muted">{fmtDur(r.avg_duration_s)}</td>
                <td className="num" style={{ color: r.errors ? "var(--err)" : undefined }}>{r.errors}</td>
                <td className="num">{fmtUsd(r.cost_usd)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={8} className="muted">no receipts in window</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
