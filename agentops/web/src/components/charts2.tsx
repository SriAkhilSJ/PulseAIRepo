import React from "react";

/** Radial gauge (context-window usage etc.), chrome-on-black. */
export const Gauge = ({ value, label, warn = 75 }: { value: number | null; label: string; warn?: number }) => {
  const v = value === null || Number.isNaN(value) ? 0 : Math.max(0, Math.min(100, value));
  const r = 42, c = 2 * Math.PI * r;
  const color = v > warn ? "var(--err)" : v > warn - 15 ? "var(--warn)" : "var(--ok)";
  return (
    <div style={{ textAlign: "center" }}>
      <svg width="110" height="110" viewBox="0 0 110 110">
        <circle cx="55" cy="55" r={r} fill="none" stroke="var(--panel-2)" strokeWidth="9" />
        <circle
          cx="55" cy="55" r={r} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 55 55)"
          style={{ transition: "stroke-dasharray .6s ease" }}
        />
        <text x="55" y="52" textAnchor="middle" fill="var(--text)" fontSize="20" fontWeight="650" className="num">
          {value === null ? "—" : v.toFixed(0) + "%"}
        </text>
        <text x="55" y="70" textAnchor="middle" fill="var(--muted)" fontSize="9.5" letterSpacing="1">
          {label.toUpperCase()}
        </text>
      </svg>
    </div>
  );
};

/** Individuals control chart [PDF §4.4]: line + X̄ ± A₂R̄ band, out-of-control dots red. */
export const ControlChart = ({ points, mean, ucl, lcl, fmt, h = 130 }: {
  points: { label: string; value: number | null; ooc: boolean }[];
  mean: number | null; ucl: number | null; lcl: number | null;
  fmt: (n: number) => string; h?: number;
}) => {
  const w = 560;
  if (!points.length || mean === null) return <div className="muted">not enough data for control limits (≥3 points)</div>;
  const vals = points.map((p) => p.value ?? 0);
  const top = Math.max(ucl ?? 0, ...vals) * 1.12 || 1;
  const bot = 0;
  const x = (i: number) => (i / Math.max(points.length - 1, 1)) * (w - 40) + 34;
  const y = (v: number) => h - 18 - ((v - bot) / (top - bot)) * (h - 30);
  const line = points.map((p, i) => `${x(i)},${y(p.value ?? 0)}`).join(" ");
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ maxWidth: w }}>
      <rect x="34" y={y(ucl ?? 0)} width={w - 40} height={Math.max(0, y(lcl ?? 0) - y(ucl ?? 0))} fill="rgba(185,185,194,0.06)" />
      {[{ v: ucl, t: "UCL" }, { v: mean, t: "X̄" }, { v: lcl, t: "LCL" }].map(({ v, t }) =>
        v === null ? null : (
          <g key={t}>
            <line x1="34" x2={w - 6} y1={y(v)} y2={y(v)} stroke="var(--border-2)" strokeDasharray={t === "X̄" ? "" : "4 4"} />
            <text x="2" y={y(v) + 3} fill="var(--muted)" fontSize="9">{t}</text>
          </g>
        ),
      )}
      <polyline points={line} fill="none" stroke="var(--chrome-2)" strokeWidth="1.6" />
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.value ?? 0)} r={p.ooc ? 4 : 2.4} fill={p.ooc ? "var(--err)" : "var(--chrome-1)"}>
          <title>{`${p.label}: ${fmt(p.value ?? 0)}${p.ooc ? " — OUT OF CONTROL" : ""}`}</title>
        </circle>
      ))}
      <text x={x(points.length - 1)} y={h - 4} textAnchor="end" fill="var(--muted)" fontSize="9">
        {points[points.length - 1]?.label}
      </text>
      <text x="34" y={h - 4} fill="var(--muted)" fontSize="9">{points[0]?.label}</text>
    </svg>
  );
};
