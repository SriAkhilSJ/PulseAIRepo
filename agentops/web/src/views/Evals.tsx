import React, { useState } from "react";
import { useApi } from "../lib/api";
import { Chip, Sparkline } from "../components/bits";
import { fmtDur, fmtUsd, fmtPct, fmtNum, timeAgo } from "../lib/format";

export default function Evals() {
  const [tab, setTab] = useState<"runs" | "ab">("runs");
  const ev = useApi<any>("/api/evals", [], 30000);
  const ab = useApi<any>("/api/evals/ab?days=14", [], 30000);
  const reg = ev.data?.regression ?? {};

  return (
    <>
      <div className="pagehead">
        <h1>Evals & Regression</h1>
        <span className="sub">benchmark runs from lab/ + evidence from bench-results/ + A/B slices of live traffic</span>
        <span style={{ marginLeft: "auto" }}>
          <div className="seg">
            <button className={tab === "runs" ? "on" : ""} onClick={() => setTab("runs")}>runs</button>
            <button className={tab === "ab" ? "on" : ""} onClick={() => setTab("ab")}>A/B</button>
          </div>
        </span>
      </div>

      {tab === "runs" && (
        <>
          <div className="grid kpis" style={{ gridTemplateColumns: "repeat(4,1fr)" }}>
            <div className="card kpi"><div className="label">runs indexed</div><div className="value num chrome">{reg.total ?? 0}</div></div>
            <div className="card kpi"><div className="label">passed</div><div className="value num">{reg.passed ?? 0}</div></div>
            <div className="card kpi"><div className="label">pass rate</div><div className="value num">{fmtPct(reg.pass_rate ?? null)}</div></div>
            <div className="card kpi">
              <div className="label">outcome trend</div>
              <Sparkline data={(reg.points ?? []).map((p: any) => (p.ok ? 1 : 0))} w={170} />
            </div>
          </div>

          <div className="grid cols-2" style={{ marginTop: 14 }}>
            <div className="card" style={{ padding: 0 }}>
              <table className="tbl">
                <thead><tr><th>run</th><th>outcome</th><th>plan</th><th>traces</th><th>cost</th><th>age</th></tr></thead>
                <tbody>
                  {(ev.data?.runs ?? []).map((r: any) => (
                    <tr key={r.id}>
                      <td className="mono">{r.id}</td>
                      <td>{r.ok ? <Chip tone="ok">{r.status}</Chip> : <Chip tone="err">{r.status}</Chip>}</td>
                      <td className="num muted">{r.plan_total ? `${r.plan_done ?? 0}/${r.plan_total}` : "—"}</td>
                      <td className="num muted">{r.traces ?? "—"}</td>
                      <td className="num">{fmtUsd(r.cost_usd ?? null)}</td>
                      <td className="muted" title={r.error}>{timeAgo(r.ts)}</td>
                    </tr>
                  ))}
                  {(ev.data?.runs ?? []).length === 0 && <tr><td colSpan={5} className="muted">no lab reports found</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="card">
              <h3>Evidence artifacts (bench-results/)</h3>
              <table className="tbl">
                <thead><tr><th>run dir</th><th>screenshots</th><th>files</th><th>age</th></tr></thead>
                <tbody>
                  {(ev.data?.evidence ?? []).map((e: any) => (
                    <tr key={e.id}>
                      <td className="mono">{e.id}</td>
                      <td className="num">{e.screenshots}</td>
                      <td className="num muted">{e.files}</td>
                      <td className="muted">{timeAgo(e.ts)}</td>
                    </tr>
                  ))}
                  {(ev.data?.evidence ?? []).length === 0 && <tr><td colSpan={4} className="muted">none</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {tab === "ab" && (
        <div className="grid cols-3">
          {(["by_mode", "by_prompt_variant", "by_task"] as const).map((k) => (
            <div className="card" key={k}>
              <h3>{k.replace("by_", "").replace("_", " ")} (14d live traffic)</h3>
              <table className="tbl">
                <thead><tr><th>variant</th><th>n</th><th>compl.</th><th>avg cost</th><th>p95</th></tr></thead>
                <tbody>
                  {(ab.data?.[k] ?? []).map((r: any) => (
                    <tr key={r.key}>
                      <td className="mono">{r.key}</td>
                      <td className="num muted">{r.n}</td>
                      <td className="num">{fmtPct(r.completion)}</td>
                      <td className="num">{fmtUsd(r.avg_cost)}</td>
                      <td className="num muted">{fmtDur(r.p95_s)}</td>
                    </tr>
                  ))}
                  {(ab.data?.[k] ?? []).length === 0 && <tr><td colSpan={5} className="muted">no traffic</td></tr>}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
