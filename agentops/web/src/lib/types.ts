export type Session = {
  session_id: string; started_at: number; last_at: number; events: number; turns: number;
  failures: number; workspace: string; mode: string; status: "active" | "idle" | "failed";
  cost_usd: number | null; tokens: number | null; model: string | null;
};
export type TraceEvent = {
  seq: number; event_id: string; created_at: number; event_type: string; session_id: string;
  turn_id: string | null; workspace_id: string | null; tool_call_id: string | null; payload: any;
};
export type ToolCall = {
  tool_call_id: string; name: string; intent_at: number | null; result_at: number | null;
  args: any; status: string | null; content_preview: string | null; duration_s?: number;
};
export type TurnReceipt = {
  turn: string; model: string; provider: string; tokens: { input: number; output: number; cache: number };
  cost_usd: number; duration_s: number; tool_calls: number; completed: boolean; error: string;
  mode: string; task_type: string;
};
export type Trace = { session_id: string; events: TraceEvent[]; turns: any[]; tools: ToolCall[]; receipts: TurnReceipt[] };
export type Kpis = {
  current: { turns: number; tokens: number; cost_usd: number; completion: number | null; p95_latency_s: number | null };
  previous: { turns: number; tokens: number; cost_usd: number; completion: number | null; p95_latency_s: number | null };
  window_days: number;
};
export type SeriesPoint = { day: string; turns: number; tokens: number; cost_usd: number; errors: number };
export type SummaryRow = {
  key: string; turns: number; tokens: number; cache_tokens: number; cost_usd: number;
  errors: number; avg_duration_s: number; cache_hit_ratio: number;
};
export type ToolStat = { tool: string; calls: number; failures: number; avg_latency_s: number | null };
export type ErrorRow = { ts: string; session: string; turn: string; model: string; mode: string; error: string; tool_calls: number };
export type RuntimeReceipt = { ts: string; session: string; kind: string; detail: any };
export type Health = {
  product: string; version: string; status: string; data_source: "demo" | "live";
  journal: { path: string; available: boolean }; receipts: { path: string; available: boolean };
  auth_required: boolean; time: number;
};
