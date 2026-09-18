import React from "react";
import { useApi } from "../lib/api";
import { Chip, HBars } from "../components/bits";
import { fmtPct, timeAgo } from "../lib/format";

export default function Learning() {
  const { data } = useApi<any>("/api/learning", [], 10000);
  if (!data) return <div className="muted">loading…</div>;

  return (
    <>
      <div className="pagehead">
        <h1>Learning & Adaptation</h1>
        <span className="sub">feedback store attribution — which context layers actually earn their tokens</span>
        <span style={{ marginLeft: "auto" }}>
          {data.available ? <Chip tone="ok">{data.records} records</Chip> : <Chip tone="mut">no feedback store</Chip>}
        </span>
      </div>

      {!data.available && (
        <div className="card muted">
          No <code>context_feedback.jsonl</code> at {data.path}. Live agents write it automatically after each
          task (src/context/feedback_memory.py); demo mode seeds it via <code>scripts/seed_phase3.py</code>.
        </div>
      )}

      {data.available && (
        <>
          <div className="grid kpis" style={{ gridTemplateColumns: "repeat(3,1fr)" }}>
            <div className="card kpi"><div className="label">records</div><div className="value num chrome">{data.records}</div></div>
            <div className="card kpi"><div className="label">base success rate</div><div className="value num">{fmtPct(data.success_rate)}</div></div>
            <div className="card kpi"><div className="label">confidence rule</div><div className="value" style={{ fontSize: 12, fontWeight: 500 }}>{data.confidence_rule}</div></div>
          </div>

          <div className="grid cols-2" style={{ marginTop: 14 }}>
            <div className="card">
              <h3>Layer attribution (success rate vs base)</h3>
              {data.layers.map((l: any) => (
                <div className="hbar" key={l.layer}>
                  <div className="mono" title={l.layer}>{l.layer.length > 18 ? l.layer.slice(0, 17) + "…" : l.layer}</div>
                  <div className="track">
                    <div className="fill" style={{ width: `${(l.success_rate || 0) * 100}%`, background: (l.delta_vs_base ?? 0) >= 0 ? "linear-gradient(90deg,#2b8f68,#3ecf8e)" : "linear-gradient(90deg,#8f2b2b,#f0564a)" }} />
                  </div>
                  <div className="val">{fmtPct(l.success_rate)}</div>
                </div>
              ))}
              <div className="muted" style={{ fontSize: 11.5, marginTop: 8 }}>
                green = above base success rate · red = below · weights only nudged when confidence rule met
              </div>
            </div>
            <div className="card">
              <h3>Layer usage & confidence</h3>
              <table className="tbl">
                <thead><tr><th>layer</th><th>used</th><th>Δ vs base</th><th>weight nudge</th></tr></thead>
                <tbody>
                  {data.layers.map((l: any) => (
                    <tr key={l.layer}>
                      <td className="mono">{l.layer}</td>
                      <td className="num">{l.used}</td>
                      <td className="num" style={{ color: (l.delta_vs_base ?? 0) >= 0 ? "var(--ok)" : "var(--err)" }}>
                        {(l.delta_vs_base ?? 0) >= 0 ? "+" : ""}{((l.delta_vs_base ?? 0) * 100).toFixed(1)}pp
                      </td>
                      <td>{l.confidence ? <Chip tone="ok">eligible</Chip> : <Chip tone="mut">insufficient</Chip>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" style={{ marginTop: 14, padding: 0 }}>
            <table className="tbl">
              <thead><tr><th>when</th><th>outcome</th><th>task</th><th>layers used</th></tr></thead>
              <tbody>
                {data.recent.map((r: any, i: number) => (
                  <tr key={i}>
                    <td className="muted mono">{r.ts ? timeAgo(r.ts) : "—"}</td>
                    <td>{r.success ? <Chip tone="ok">success</Chip> : <Chip tone="err">fail</Chip>}</td>
                    <td className="muted" style={{ maxWidth: 340 }}>{r.task}</td>
                    <td className="mono muted" style={{ maxWidth: 260 }}>{(r.layers || []).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
