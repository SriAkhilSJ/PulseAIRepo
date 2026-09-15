import React, { useEffect, useMemo, useRef, useState } from "react";
import { useApi, useStream } from "../lib/api";
import { Chip } from "../components/bits";
import { fmtClock, fmtDur, fmtNum, fmtUsd, shortId } from "../lib/format";
import type { Trace, TraceEvent } from "../lib/types";

const evClass = (t: string, payload: any) => {
  if (t === "tool.result" && payload?.status && payload.status !== "ok") return "tool_result bad";
  if (t === "tool.result") return "tool_result";
  if (t === "tool.intent") return "tool_intent";
  if (t.startsWith("runtime")) return "runtime";
  return t.replace(".", "_");
};

const evBody = (ev: TraceEvent): React.ReactNode => {
  const p = ev.payload || {};
  switch (ev.event_type) {
    case "tool.intent":
      return <>→ <code>{p.tool_name}</code> {p.args ? <span className="mono">{JSON.stringify(p.args).slice(0, 160)}</span> : null}</>;
    case "tool.result":
      return <><code>{p.tool_name}</code> status=<span style={{ color: p.status === "ok" ? "var(--ok)" : "var(--err)" }}>{p.status}</span> {p.content ? <span>· {String(p.content).slice(0, 140)}</span> : null}</>;
    case "plan_created":
      return <>{(p.steps || []).map((s: any, i: number) => <div key={i}>· {s.detail || s.step}</div>)}</>;
    case "turn_started":
      return <>model <code>{p.model}</code> mode <code>{p.mode}</code></>;
    case "turn_failed":
      return <span style={{ color: "var(--err)" }}>{p.error}</span>;
    case "turn_done":
      return <span style={{ color: "var(--ok)" }}>{p.summary || "completed"}</span>;
    case "runtime_degraded":
      return <span style={{ color: "var(--warn)" }}>degraded: {p.reason} (layer {p.layer})</span>;
    default:
      return <span className="mono">{JSON.stringify(p).slice(0, 180)}</span>;
  }
};

export default function SessionTrace({ id }: { id: string }) {
  const { data, error, reload } = useApi<Trace>(`/api/sessions/${encodeURIComponent(id)}/trace`);
  const [idx, setIdx] = useState<number | null>(null); // null = live (show all)
  const [playing, setPlaying] = useState(false);
  const [stopMsg, setStopMsg] = useState<string | null>(null);
  const ivRef = useRef<any>(0);

  const kill = async () => {
    try {
      const res = await fetch("/api/control/stop", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ session_id: id }),
      });
      const body = await res.json();
      setStopMsg(res.ok ? `kill switch signaled for ${id.slice(0, 12)}…` : `kill switch: ${body.detail || res.status}`);
      setTimeout(reload, 1500);
    } catch (e) {
      setStopMsg(`kill switch failed: ${e}`);
    }
  };

  // refetch when the stream reports new journal rows for this session
  useStream(3, (ev) => {
    if (ev.kind === "journal" && ev.data?.session_id === id && idx === null) reload();
  });

  const events = data?.events ?? [];
  const cut = idx === null ? events.length : Math.min(idx, events.length);
  const shown = events.slice(0, cut);

  useEffect(() => () => clearInterval(ivRef.current), []);
  useEffect(() => {
    if (playing) {
      ivRef.current = setInterval(() => {
        setIdx((v) => {
          const nv = (v === null ? 1 : v + 1);
          if (nv >= events.length) { setPlaying(false); return events.length; }
          return nv;
        });
      }, 260);
    } else clearInterval(ivRef.current);
    return () => clearInterval(ivRef.current);
  }, [playing, events.length]);

  const failed = useMemo(() => events.some((e) => e.event_type === "turn_failed"), [events]);

  return (
    <>
      <div className="pagehead">
        <h1 className="mono" style={{ fontSize: 17 }}>{shortId(id, 26)}</h1>
        <a href="#/sessions" className="muted">← sessions</a>
        <span style={{ marginLeft: "auto" }}>
          {failed ? <Chip tone="err">has failures</Chip> : <Chip tone="ok">journaled</Chip>}
        </span>
        <button className="seg" style={{ padding: 0 }} onClick={kill} title="kill switch [PDF §6]">
          <span style={{ padding: "6px 12px", color: "var(--err)", fontWeight: 700 }}>⏹ stop session</span>
        </button>
      </div>
      {stopMsg && <div className="muted" style={{ marginBottom: 10, fontSize: 12.5 }}>{stopMsg}</div>}

      <div className="replay">
        <button onClick={() => { setIdx(1); setPlaying(true); }}>▶ replay</button>
        <button onClick={() => { setPlaying(false); setIdx(null); }}>⇥ live end</button>
        <input
          type="range" min={1} max={Math.max(events.length, 1)} value={cut}
          onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }}
        />
        <span className="pos">{cut} / {events.length} events</span>
      </div>

      {error && <div className="err-msg">{error}</div>}
      <div className="trace">
        <div className="card">
          <h3>Execution timeline (time-travel)</h3>
          <div className="tl">
            {shown.map((ev) => (
              <div className={`ev ${evClass(ev.event_type, ev.payload)}`} key={ev.seq}>
                <div className="head">
                  <span className="type">{ev.event_type}</span>
                  <span className="ts">{fmtClock(ev.created_at)}</span>
                  {ev.turn_id && <span className="ts">{shortId(ev.turn_id, 12)}</span>}
                </div>
                <div className="body">{evBody(ev)}</div>
              </div>
            ))}
            {shown.length === 0 && <div className="muted">no journaled events</div>}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <h3>Tool calls (intent → result)</h3>
            <table className="tbl">
              <thead><tr><th>tool</th><th>status</th><th>latency</th></tr></thead>
              <tbody>
                {(data?.tools ?? []).map((t) => (
                  <tr key={t.tool_call_id}>
                    <td>
                      <code>{t.name}</code>
                      {t.args && <div className="mono muted" style={{ marginTop: 3 }}>{JSON.stringify(t.args).slice(0, 90)}</div>}
                      {t.content_preview && <div className="mono muted">{t.content_preview.slice(0, 90)}</div>}
                    </td>
                    <td><Chip tone={t.status === "ok" ? "ok" : t.status ? "err" : "mut"}>{t.status || "pending"}</Chip></td>
                    <td className="num muted">{fmtDur(t.duration_s ?? null)}</td>
                  </tr>
                ))}
                {(data?.tools ?? []).length === 0 && <tr><td colSpan={3} className="muted">no tool calls</td></tr>}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3>Turn receipts (tokens · cost)</h3>
            <table className="tbl">
              <thead><tr><th>turn</th><th>tokens in/out/cache</th><th>cost</th><th>dur</th><th>result</th></tr></thead>
              <tbody>
                {(data?.receipts ?? []).map((r, i) => (
                  <tr key={i}>
                    <td className="mono">{shortId(r.turn || "", 12)}<div className="muted">{r.model}</div></td>
                    <td className="num">{fmtNum(r.tokens?.input)}/{fmtNum(r.tokens?.output)}/{fmtNum(r.tokens?.cache)}</td>
                    <td className="num">{fmtUsd(r.cost_usd)}</td>
                    <td className="num muted">{fmtDur(r.duration_s)}</td>
                    <td>{r.completed ? <Chip tone="ok">done</Chip> : <Chip tone="err" >failed</Chip>}{r.error && <div className="muted" style={{ marginTop: 4 }}>{r.error}</div>}</td>
                  </tr>
                ))}
                {(data?.receipts ?? []).length === 0 && <tr><td colSpan={5} className="muted">no receipts for this session</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
