import React, { useState } from "react";
import { useApi } from "../lib/api";
import { Chip } from "../components/bits";
import { ControlChart } from "../components/charts2";
import { fmtDate, fmtUsd, fmtPct, fmtDur, shortId } from "../lib/format";
import type { ErrorRow, RuntimeReceipt } from "../lib/types";

export default function Errors() {
  const [days, setDays] = useState(7);
  const { data, error } = useApi<{ errors: ErrorRow[]; runtime_receipts: RuntimeReceipt[] }>(`/api/errors?days=${days}`, [days]);
  const slo = useApi<any>(`/api/slo?days=${days}`, [days]);
  const cur = slo.data?.current ?? {};
  const tgt = slo.data?.targets ?? {};
  const cc = slo.data?.control?.cost_per_day;

  const sloRow = (label: string, value: string, target: string, ok: boolean | null) => (
    <tr>
      <td className="muted">{label}</td>
      <td className="num">{value}</td>
      <td className="num muted">{target}</td>
      <td>{ok === null ? <Chip tone="mut">n/a</Chip> : ok ? <Chip tone="ok">meets</Chip> : <Chip tone="err">misses</Chip>}</td>
    </tr>
  );

  return (
    <>
      <div className="pagehead">
        <h1>Errors & Reliability</h1>
        <span className="sub">failed turns, classified errors, latched runtime receipts</span>
        <span style={{ marginLeft: "auto" }}>
          <div className="seg">{[1, 7, 30].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d}d</button>)}</div>
        </span>
      </div>

      {error && <div className="err-msg">{error}</div>}

      <div className="card" style={{ padding: 0 }}>
        <table className="tbl">
          <thead><tr><th>when</th><th>session</th><th>model</th><th>mode</th><th>tools</th><th>error</th></tr></thead>
          <tbody>
            {(data?.errors ?? []).map((e, i) => (
              <tr key={i} className="clickable" onClick={() => { location.hash = `#/sessions/${e.session}`; }}>
                <td className="muted mono">{fmtDate(e.ts)}</td>
                <td className="mono">{shortId(e.session, 14)}</td>
                <td className="muted">{e.model}</td>
                <td className="muted">{e.mode}</td>
                <td className="num muted">{e.tool_calls}</td>
                <td style={{ color: "var(--err)" }}>{e.error}</td>
              </tr>
            ))}
            {(data?.errors ?? []).length === 0 && <tr><td colSpan={6} className="muted">no failures in window 🎉</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>SLO panel [case-study targets, PDF §10]</h3>
          <table className="tbl">
            <thead><tr><th>objective</th><th>current</th><th>target</th><th>status</th></tr></thead>
            <tbody>
              {sloRow("completion / uptime proxy", fmtPct(cur.completion), "≥ 90%", cur.completion == null ? null : cur.completion >= (tgt.completion ?? 0.9))}
              {sloRow("p95 turn latency", fmtDur(cur.p95_latency_s), "≤ 120s", cur.p95_latency_s == null ? null : cur.p95_latency_s <= (tgt.p95_latency_s ?? 120))}
              {sloRow("cost per task", fmtUsd(cur.cost_per_task), "trend ↓", null)}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Cost/day — SPC control chart (X̄ ± A₂R̄)</h3>
          {cc ? (
            <>
              <ControlChart points={cc.points} mean={cc.mean} ucl={cc.ucl} lcl={cc.lcl} fmt={fmtUsd} />
              <div className="muted" style={{ fontSize: 11.5, marginTop: 6 }}>
                {(cc.violations ?? []).length === 0
                  ? "process in control — no days outside limits"
                  : `${cc.violations.length} day(s) out of control (red) — investigate spend anomaly`}
              </div>
            </>
          ) : <div className="muted">loading…</div>}
        </div>
      </div>

      <SecurityCard days={days} />

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Runtime receipts (cache-break · degraded)</h3>
        <div className="ticker" style={{ maxHeight: 260 }}>
          {(data?.runtime_receipts ?? []).map((r, i) => (
            <div className="row" key={i}>
              <span className="t">{(r.ts || "").slice(11, 16)}</span>
              <span className="k"><Chip tone="warn">{r.kind}</Chip></span>
              <span className="muted mono">{shortId(r.session, 14)} · {JSON.stringify(r.detail).slice(0, 140)}</span>
            </div>
          ))}
          {(data?.runtime_receipts ?? []).length === 0 && <div className="muted">no latched runtime receipts in window</div>}
        </div>
      </div>
    </>
  );
}

function SecurityCard({ days }: { days: number }) {
  const { data } = useApi<{ suspects: any[] }>(`/api/security/scan?days=${days}`, [days]);
  const suspects = data?.suspects ?? [];
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <h3>Prompt-injection suspicion scan [PDF §2.3]</h3>
      {suspects.length === 0 && <div className="muted">no suspicious tool intents in window</div>}
      <div className="ticker" style={{ maxHeight: 220 }}>
        {suspects.map((s, i) => (
          <div className="row" key={i}>
            <span className="t">{new Date((s.ts || 0) * 1000).toLocaleTimeString([], { hour12: false })}</span>
            <span className="k"><Chip tone="err">{s.reason}</Chip></span>
            <span className="muted mono">{s.tool_name} · {shortId(s.session_id, 12)} · …{String(s.snippet).slice(0, 110)}…</span>
          </div>
        ))}
      </div>
    </div>
  );
}
