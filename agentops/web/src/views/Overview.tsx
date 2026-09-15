import React from "react";
import { useApi, useStream, StreamEvent } from "../lib/api";
import { KpiCard, Chip, statusTone, HBars } from "../components/bits";
import { fmtNum, fmtUsd, fmtPct, fmtDur, deltaPct, timeAgo, shortId, fmtClock } from "../lib/format";
import type { Kpis, SeriesPoint, Session, ErrorRow, Health } from "../lib/types";

export default function Overview({ health, ticker, connected }: {
  health: Health | null; ticker: StreamEvent[]; connected: boolean;
}) {
  const k = useApi<Kpis>("/api/kpis?days=1");
  const series = useApi<{ series: SeriesPoint[] }>("/api/usage/series?days=7");
  const sessions = useApi<{ sessions: Session[] }>("/api/sessions?limit=8");
  const errs = useApi<{ errors: ErrorRow[] }>("/api/errors?days=7");

  const cur = k.data?.current, prev = k.data?.previous;
  const s = series.data?.series ?? [];
  const dCost = deltaPct(cur?.cost_usd ?? null, prev?.cost_usd ?? null);
  const dTurns = deltaPct(cur?.turns ?? null, prev?.turns ?? null);
  const dTok = deltaPct(cur?.tokens ?? null, prev?.tokens ?? null);

  return (
    <>
      <div className="pagehead">
        <h1>Overview</h1>
        <span className="sub">orchestration control plane — live agent telemetry</span>
        <span style={{ marginLeft: "auto" }}>
          {health?.data_source === "demo" ? <Chip tone="demo">DEMO DATA</Chip> : <Chip tone="ok">LIVE SINKS</Chip>}
        </span>
      </div>

      <div className="grid kpis">
        <KpiCard label="Turns today" value={fmtNum(cur?.turns)} delta={dTurns.text} deltaCls={dTurns.cls} spark={s.map((x) => x.turns)} />
        <KpiCard label="Tokens today" value={fmtNum(cur?.tokens)} delta={dTok.text} deltaCls={dTok.cls} spark={s.map((x) => x.tokens)} />
        <KpiCard label="Spend today" value={fmtUsd(cur?.cost_usd)} delta={dCost.text} deltaCls={dCost.cls === "up" ? "down" : dCost.cls === "down" ? "up" : "flat"} spark={s.map((x) => x.cost_usd)} />
        <KpiCard label="Completion" value={fmtPct(cur?.completion)} />
        <KpiCard label="p95 latency" value={fmtDur(cur?.p95_latency_s)} />
        <KpiCard label="Errors (7d)" value={fmtNum(errs.data?.errors.length)} chrome={false} />
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Live event stream {connected ? <span className="livedot" /> : <span className="livedot off" />}</h3>
          <div className="ticker">
            {ticker.length === 0 && <div className="muted">waiting for agent events…</div>}
            {ticker.map((ev, i) => (
              <div className="row" key={i}>
                <span className="t">{new Date(ev.at).toLocaleTimeString([], { hour12: false })}</span>
                <span className="k">{ev.kind === "receipt" ? "turn.receipt" : ev.data?.event_type}</span>
                <span className="muted">
                  {ev.kind === "receipt"
                    ? `${shortId(ev.data?.session || "", 12)} ${fmtNum((ev.data?.tokens?.input || 0) + (ev.data?.tokens?.output || 0))} tok · ${fmtUsd(ev.data?.cost_usd)} · ${ev.data?.completed ? "completed" : "FAILED"}`
                    : `${shortId(ev.data?.session_id || "", 12)} ${ev.data?.payload?.tool_name || ev.data?.payload?.model || ev.data?.payload?.error || ev.data?.payload?.status || ""}`}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Recent sessions</h3>
          <table className="tbl">
            <thead><tr><th>session</th><th>status</th><th>mode</th><th>turns</th><th>cost</th><th>last</th></tr></thead>
            <tbody>
              {(sessions.data?.sessions ?? []).map((x) => (
                <tr className="clickable" key={x.session_id} onClick={() => { location.hash = `#/sessions/${x.session_id}`; }}>
                  <td className="mono">{shortId(x.session_id, 14)}</td>
                  <td><Chip tone={statusTone(x.status)}>{x.status}</Chip></td>
                  <td className="muted">{x.mode}</td>
                  <td className="num">{x.turns}</td>
                  <td className="num">{fmtUsd(x.cost_usd)}</td>
                  <td className="muted">{timeAgo(x.last_at)}</td>
                </tr>
              ))}
              {(sessions.data?.sessions ?? []).length === 0 && <tr><td colSpan={6} className="muted">no sessions journaled yet</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Spend by day (7d)</h3>
          <HBars rows={s.map((x) => ({ label: x.day.slice(5), value: x.cost_usd }))} fmt={fmtUsd} />
        </div>
        <div className="card">
          <h3>Latest failures</h3>
          <table className="tbl">
            <thead><tr><th>when</th><th>session</th><th>error</th></tr></thead>
            <tbody>
              {(errs.data?.errors ?? []).slice(0, 5).map((e, i) => (
                <tr key={i}>
                  <td className="muted mono">{e.ts?.slice(5, 16)}</td>
                  <td className="mono">{shortId(e.session, 12)}</td>
                  <td style={{ color: "var(--err)" }}>{e.error}</td>
                </tr>
              ))}
              {(errs.data?.errors ?? []).length === 0 && <tr><td colSpan={3} className="muted">no failures in window 🎉</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
