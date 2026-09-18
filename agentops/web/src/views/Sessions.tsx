import React, { useMemo, useState } from "react";
import { useApi } from "../lib/api";
import { Chip, statusTone } from "../components/bits";
import { fmtNum, fmtUsd, timeAgo, shortId } from "../lib/format";
import type { Session } from "../lib/types";

export default function Sessions() {
  const { data, error } = useApi<{ sessions: Session[] }>("/api/sessions?limit=200");
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    let rs = data?.sessions ?? [];
    if (status !== "all") rs = rs.filter((r) => r.status === status);
    if (q) rs = rs.filter((r) => r.session_id.includes(q) || (r.workspace || "").includes(q));
    return rs;
  }, [data, status, q]);

  return (
    <>
      <div className="pagehead">
        <h1>Sessions</h1>
        <span className="sub">every agent session journaled by the runtime (S2)</span>
      </div>
      <div className="toolbar">
        <div className="seg">
          {["all", "active", "idle", "failed"].map((s) => (
            <button key={s} className={status === s ? "on" : ""} onClick={() => setStatus(s)}>{s}</button>
          ))}
        </div>
        <input type="search" placeholder="filter by session id / workspace…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted num">{rows.length} sessions</span>
      </div>
      {error && <div className="err-msg">{error}</div>}
      <div className="card" style={{ padding: 0 }}>
        <table className="tbl">
          <thead>
            <tr><th>session</th><th>status</th><th>mode</th><th>turns</th><th>events</th><th>tokens</th><th>cost</th><th>workspace</th><th>last activity</th></tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr className="clickable" key={x.session_id} onClick={() => { location.hash = `#/sessions/${x.session_id}`; }}>
                <td className="mono">{shortId(x.session_id, 18)}</td>
                <td><Chip tone={statusTone(x.status)}>{x.status}</Chip></td>
                <td className="muted">{x.mode}</td>
                <td className="num">{x.turns}</td>
                <td className="num">{x.events}</td>
                <td className="num">{fmtNum(x.tokens)}</td>
                <td className="num">{fmtUsd(x.cost_usd)}</td>
                <td className="muted mono" title={x.workspace}>{shortId(x.workspace.split("/").pop() || x.workspace, 14)}</td>
                <td className="muted">{timeAgo(x.last_at)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={9} className="muted">no sessions match</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
