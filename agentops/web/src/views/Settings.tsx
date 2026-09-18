import React from "react";
import { useApi } from "../lib/api";
import { Chip } from "../components/bits";
import type { Health } from "../lib/types";

export default function Settings({ health }: { health: Health | null }) {
  return (
    <>
      <div className="pagehead">
        <h1>Settings</h1>
        <span className="sub">data sources, security posture, about</span>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Data sources (read-only)</h3>
          <table className="tbl">
            <tbody>
              <tr><td className="muted">mode</td><td>{health?.data_source === "demo" ? <Chip tone="demo">DEMO DATA</Chip> : <Chip tone="ok">live engine sinks</Chip>}</td></tr>
              <tr><td className="muted">event journal</td><td className="mono">{health?.journal.path} {health?.journal.available ? <Chip tone="ok">readable</Chip> : <Chip tone="err">missing</Chip>}</td></tr>
              <tr><td className="muted">turn receipts</td><td className="mono">{health?.receipts.path} {health?.receipts.available ? <Chip tone="ok">readable</Chip> : <Chip tone="err">missing</Chip>}</td></tr>
              <tr><td className="muted">bearer auth</td><td>{health?.auth_required ? <Chip tone="ok">enforced</Chip> : <Chip tone="warn">off — set CRUSORAI_OPS_TOKEN for non-loopback</Chip>}</td></tr>
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
            The journal is opened <code>mode=ro</code> and receipts are parsed debris-tolerantly:
            the dashboard can never block or corrupt an agent turn.
          </p>
        </div>

        <div className="card">
          <h3>About</h3>
          <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <img src="/logo.png" alt="CrusorAI" style={{ width: 64, borderRadius: 12 }} />
            <div>
              <div style={{ fontSize: 17, fontWeight: 650 }}>CrusorAI <span className="muted" style={{ fontWeight: 500 }}>AgentOps</span></div>
              <div className="muted mono">v{health?.version ?? "…"} · {health?.product}</div>
            </div>
          </div>
          <p className="muted" style={{ fontSize: 12.5 }}>
            AgentOps console for the CrusorAI agent: sessions, time-travel traces, token & cost
            analytics, context health, errors, approvals and audit — built on the IJCATR1407.1001
            AgentOps framework (monitoring · debugging · automation · security).
          </p>
          <h3 style={{ marginTop: 14 }}>Compliance export [PDF §2.3]</h3>
          <div style={{ display: "flex", gap: 10 }}>
            <a className="chip ok" href="/api/export/audit?format=csv" download>⬇ audit pack (CSV)</a>
            <a className="chip info" href="/api/export/audit?format=json" download>⬇ audit pack (JSON)</a>
          </div>
          <p className="muted" style={{ fontSize: 11.5 }}>
            Immutable journal audit trail + turn receipts with computed costs — one file for compliance review.
          </p>
          <h3 style={{ marginTop: 14 }}>Environment</h3>
          <table className="tbl">
            <tbody>
              <tr><td className="muted mono">CRUSORAI_OPS_DATA_DIR</td><td className="mono">data root (default ~/.pulseai)</td></tr>
              <tr><td className="muted mono">CRUSORAI_OPS_TOKEN</td><td className="mono">bearer token for /api</td></tr>
              <tr><td className="muted mono">CRUSORAI_OPS_PRICES</td><td className="mono">JSON price table per 1M tok</td></tr>
              <tr><td className="muted mono">CRUSORAI_OPS_DEMO</td><td className="mono">on → labels UI as demo</td></tr>
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Prompt & policy registry [PDF §3.2]</h3>
          <PromptRegistry />
        </div>
      </div>
    </>
  );
}

function PromptRegistry() {
  const { data } = useApi<any>("/api/prompts", [], 15000);
  if (!data) return <div className="muted">loading…</div>;
  if (!data.available) return <div className="muted">prompt corpus not found at {data.dir}</div>;
  const dist = Object.entries(data.turn_distribution ?? {}) as [string, number][];
  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Chip tone="info">corpus {data.corpus_hash}</Chip>
        <span className="muted mono">{data.files.length} files · {data.dir}</span>
      </div>
      {dist.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="muted" style={{ fontSize: 11.5, marginBottom: 4 }}>turns by prompt_id (30d)</div>
          {dist.map(([pid, n]) => (
            <div className="hbar" key={pid}>
              <div className="mono">{pid}</div>
              <div className="track"><div className="fill" style={{ width: `${(n / Math.max(...dist.map((d) => d[1]))) * 100}%` }} /></div>
              <div className="val">{n} turns</div>
            </div>
          ))}
        </div>
      )}
      <table className="tbl" style={{ marginTop: 10 }}>
        <thead><tr><th>file</th><th>hash</th><th>bytes</th></tr></thead>
        <tbody>
          {data.files.slice(0, 12).map((f: any) => (
            <tr key={f.path}>
              <td className="mono">{f.path}</td>
              <td className="mono muted">{f.hash}</td>
              <td className="num muted">{f.bytes}</td>
            </tr>
          ))}
          {data.files.length > 12 && <tr><td colSpan={3} className="muted">… {data.files.length - 12} more files</td></tr>}
        </tbody>
      </table>
      <p className="muted" style={{ fontSize: 11.5 }}>
        Per-turn <code>prompt_id</code> emission by the engine is the remaining additive gap;
        demo receipts carry it so the attribution view is exercised end-to-end.
      </p>
    </>
  );
}
