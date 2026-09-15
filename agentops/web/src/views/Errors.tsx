import React, { useState } from "react";
import { useApi } from "../lib/api";
import { Chip } from "../components/bits";
import { fmtDate, shortId } from "../lib/format";
import type { ErrorRow, RuntimeReceipt } from "../lib/types";

export default function Errors() {
  const [days, setDays] = useState(7);
  const { data, error } = useApi<{ errors: ErrorRow[]; runtime_receipts: RuntimeReceipt[] }>(`/api/errors?days=${days}`, [days]);

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
