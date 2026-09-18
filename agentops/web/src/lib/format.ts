export const fmtNum = (n: number | null | undefined): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(Math.round(n));
};

export const fmtUsd = (n: number | null | undefined): string => {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (n === 0) return "$0";
  if (n < 0.01) return "$" + n.toFixed(4);
  if (n < 1) return "$" + n.toFixed(3);
  return "$" + n.toFixed(2);
};

export const fmtDur = (s: number | null | undefined): string => {
  if (s === null || s === undefined || Number.isNaN(s)) return "—";
  if (s < 1) return (s * 1000).toFixed(0) + "ms";
  if (s < 60) return s.toFixed(1) + "s";
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
};

export const fmtPct = (x: number | null | undefined): string =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : (x * 100).toFixed(1) + "%";

export const timeAgo = (epochS: number): string => {
  const d = Date.now() / 1000 - epochS;
  if (d < 5) return "just now";
  if (d < 60) return `${Math.round(d)}s ago`;
  if (d < 3600) return `${Math.round(d / 60)}m ago`;
  if (d < 86400) return `${(d / 3600).toFixed(1)}h ago`;
  return `${(d / 86400).toFixed(1)}d ago`;
};

export const fmtClock = (epochS: number): string =>
  new Date(epochS * 1000).toLocaleTimeString([], { hour12: false });

export const fmtDate = (isoTs: string): string => {
  const d = new Date(isoTs);
  return Number.isNaN(d.getTime()) ? isoTs : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
};

export const shortId = (id: string, n = 10): string => (id && id.length > n ? id.slice(0, n) + "…" : id);

export const deltaPct = (cur: number | null, prev: number | null): { text: string; cls: string } => {
  if (cur === null || prev === null || prev === 0) return { text: "—", cls: "flat" };
  const d = ((cur - prev) / prev) * 100;
  if (Math.abs(d) < 0.5) return { text: "±0%", cls: "flat" };
  return { text: `${d > 0 ? "+" : ""}${d.toFixed(0)}%`, cls: d > 0 ? "up" : "down" };
};
