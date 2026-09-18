import React, { useState } from "react";
import { useApi } from "../lib/api";
import { Chip } from "../components/bits";
import { fmtDur, timeAgo, shortId } from "../lib/format";

type Pending = {
  tool_id: string; session_id: string; requested_at: number; tool_name: string; args: any; source: string;
};
type Hist = {
  tool_id: string; session_id: string; resolved_at: number; latency_s: number | null;
  approved: boolean; timed_out: boolean; always_allow: boolean; tool_name: string; source: string;
};

export default function Approvals() {
  const pend = useApi<{ pending: Pending[]; engine_live: boolean }>("/api/approvals?state=pending", [], 3000);
  const hist = useApi<{ history: Hist[] }>("/api/approvals?state=history", [], 5000);
  const stats = useApi<any>("/api/approvals/stats?days=7", [], 5000);
  const [busy, setBusy] = useState<string | null>(null);

  const resolve = async (tool_id: string, approved: boolean, thread_id?: string) => {
    setBusy(tool_id);
    try {
      const res = await fetch(`/api/approvals/${encodeURIComponent(tool_id)}/resolve`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ approved, always_allow: false, thread_id }),
      });
      if (!res.ok) throw new Error(`${res.status}`);
      pend.reload(); hist.reload(); stats.reload();
    } catch (e) {
      alert(`resolve failed: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const s = stats.data;
  return (
    <>
      <div className="pagehead">
        <h1>Approvals</h1>
        <span className="sub">human-in-the-loop queue — fail-closed engine semantics preserved (timeout = deny)</span>
        <span style={{ marginLeft: "auto" }}>
          {pend.data?.engine_live ? <Chip tone="ok">engine live-proxy</Chip> : <Chip tone="mut">journal / demo mode</Chip>}
        </span>
      </div>

      <div className="grid kpis" style={{ gridTemplateColumns: "repeat(5,1fr)" }}>
        <div className="card kpi"><div className="label">pending now</div><div className="value num">{pend.data?.pending.length ?? 0}</div></div>
        <div className="card kpi"><div className="label">decisions (7d)</div><div className="value num chrome">{s?.total ?? 0}</div></div>
        <div className="card kpi"><div className="label">deny rate</div><div className="value num">{s?.deny_rate === null || s?.deny_rate === undefined ? "—" : (s.deny_rate * 100).toFixed(0) + "%"}</div></div>
        <div className="card kpi"><div className="label">timed out (deny)</div><div className="value num">{s?.timed_out ?? 0}</div></div>
        <div className="card kpi"><div className="label">median latency</div><div className="value num">{fmtDur(s?.median_latency_s ?? null)}</div></div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h3>Pending queue</h3>
        {(pend.data?.pending ?? []).length === 0 && <div className="muted">queue empty — nothing awaiting a human</div>}
        {(pend.data?.pending ?? []).map((p) => (
          <div key={p.tool_id} className="card" style={{ background: "var(--panel-2)", marginBottom: 10 }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              <Chip tone="warn">awaiting decision</Chip>
              <code>{p.tool_name}</code>
              <span className="mono muted">{shortId(p.session_id, 16)}</span>
              <span className="muted">{timeAgo(p.requested_at)}</span>
              <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <button className="seg" style={{ padding: 0 }} disabled={busy === p.tool_id}
                  onClick={() => resolve(p.tool_id, true, p.session_id)}>
                  <span style={{ padding: "6px 14px", color: "var(--ok)", fontWeight: 700 }}>approve</span>
                </button>
                <button className="seg" style={{ padding: 0 }} disabled={busy === p.tool_id}
                  onClick={() => resolve(p.tool_id, false, p.session_id)}>
                  <span style={{ padding: "6px 14px", color: "var(--err)", fontWeight: 700 }}>deny</span>
                </button>
              </span>
            </div>
            {p.args && <div className="mono muted" style={{ marginTop: 8 }}>{JSON.stringify(p.args)}</div>}
          </div>
        ))}
      </div>

      <div className="card" style={{ marginTop: 14, padding: 0 }}>
        <table className="tbl">
          <thead><tr><th>resolved</th><th>tool</th><th>session</th><th>decision</th><th>latency</th><th>flags</th><th>source</th></tr></thead>
          <tbody>
            {(hist.data?.history ?? []).map((h, i) => (
              <tr key={i}>
                <td className="muted mono">{new Date((h.resolved_at || 0) * 1000).toLocaleTimeString([], { hour12: false })}</td>
                <td><code>{h.tool_name}</code></td>
                <td className="mono muted">{shortId(h.session_id, 14)}</td>
                <td>{h.approved ? <Chip tone="ok">approved</Chip> : h.timed_out ? <Chip tone="err">timeout→deny</Chip> : <Chip tone="err">denied</Chip>}</td>
                <td className="num muted">{fmtDur(h.latency_s)}</td>
                <td>{h.always_allow ? <Chip tone="info">always-allow</Chip> : null}</td>
                <td className="muted">{h.source}</td>
              </tr>
            ))}
            {(hist.data?.history ?? []).length === 0 && <tr><td colSpan={7} className="muted">no decisions recorded yet</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
