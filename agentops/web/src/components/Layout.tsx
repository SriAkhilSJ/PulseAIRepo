import React from "react";
import { Chip } from "./bits";
import type { Health } from "../lib/types";

const NAV = [
  ["#/", "Overview", "◈"],
  ["#/sessions", "Sessions", "≣"],
  ["#/context", "Context Health", "◍"],
  ["#/usage", "Usage & Cost", "◔"],
  ["#/approvals", "Approvals", "✓"],
  ["#/errors", "Errors & SLOs", "⚠"],
  ["#/settings", "Settings", "⚙"],
] as const;

export default function Layout({
  route, health, live, children,
}: {
  route: string; health: Health | null; live: boolean; children: React.ReactNode;
}) {
  const active = (href: string) =>
    href === "#/" ? route === "#/" || route === "" || route === "#" : route.startsWith(href);
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <img src="/logo.png" alt="CrusorAI logo" />
          <span className="word"><span className="chrome">Crusor</span>AI</span>
          <span className="tag">AgentOps</span>
        </div>
        <nav className="nav">
          {NAV.map(([href, label, ico]) => (
            <a key={href} href={href} className={active(href) ? "on" : ""}>
              <span className="ico">{ico}</span>
              {label}
            </a>
          ))}
        </nav>
        <div className="foot">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span className={`livedot ${live ? "" : "off"}`} />
            <span>{live ? "live stream connected" : "stream offline"}</span>
          </div>
          {health?.data_source === "demo" && <div style={{ marginBottom: 6 }}><Chip tone="demo">DEMO DATA</Chip></div>}
          <div className="mono">{health ? `sinks: ${health.journal.available ? "journal✓" : "journal✗"} ${health.receipts.available ? "receipts✓" : "receipts✗"}` : "connecting…"}</div>
          <div className="mono" style={{ marginTop: 4 }}>CrusorAI AgentOps v{health?.version ?? "…"}</div>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}
