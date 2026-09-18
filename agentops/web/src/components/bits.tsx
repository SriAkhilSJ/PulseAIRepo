import React from "react";

export const Chip = ({ tone, children }: { tone: "ok" | "warn" | "err" | "info" | "mut" | "demo"; children: React.ReactNode }) => (
  <span className={`chip ${tone}`}>
    {tone !== "demo" && <span className="dot" />}
    {children}
  </span>
);

export const statusTone = (s: string) => (s === "active" ? "ok" : s === "failed" ? "err" : s === "idle" ? "mut" : "info") as any;

export const KpiCard = ({
  label, value, delta, deltaCls = "flat", spark, chrome = true,
}: {
  label: string; value: string; delta?: string; deltaCls?: string; spark?: number[]; chrome?: boolean;
}) => (
  <div className="card kpi">
    <div className="label">{label}</div>
    <div className={`value num ${chrome ? "chrome" : ""}`}>{value}</div>
    {delta && <div className={`delta num ${deltaCls}`}>{delta} vs prev</div>}
    {spark && spark.length > 1 && <Sparkline data={spark} />}
  </div>
);

export const Sparkline = ({ data, w = 150, h = 34 }: { data: number[]; w?: number; h?: number }) => {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * (w - 2) + 1;
    const y = h - 3 - ((v - min) / span) * (h - 8);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline points={pts.join(" ")} fill="none" stroke="url(#chromeGrad)" strokeWidth="1.8" />
      <defs>
        <linearGradient id="chromeGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#7c7c86" />
          <stop offset="1" stopColor="#f5f5f7" />
        </linearGradient>
      </defs>
      <circle cx={pts[pts.length - 1].split(",")[0]} cy={pts[pts.length - 1].split(",")[1]} r="2.4" fill="#f5f5f7" />
    </svg>
  );
};

export const HBars = ({ rows, fmt }: { rows: { label: string; value: number; sub?: string }[]; fmt: (n: number) => string }) => {
  const max = Math.max(...rows.map((r) => r.value), 1e-9);
  return (
    <div>
      {rows.slice(0, 8).map((r) => (
        <div className="hbar" key={r.label}>
          <div className="mono" title={r.label}>{r.label.length > 18 ? r.label.slice(0, 17) + "…" : r.label}</div>
          <div className="track"><div className="fill" style={{ width: `${(r.value / max) * 100}%` }} /></div>
          <div className="val">{fmt(r.value)}</div>
        </div>
      ))}
      {rows.length === 0 && <div className="muted">no data</div>}
    </div>
  );
};
