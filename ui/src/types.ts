export type Surface = "agent" | "manager" | "tools";
export type Theme = "dark" | "light";
export type DemoStage = "idle" | "streaming" | "approval" | "verifying" | "verified" | "denied";
export type ToolState = "queued" | "running" | "passed" | "approval" | "failed";

export interface ToolRun {
  id: string;
  /** Exact bridge/runtime tool name, e.g. run_terminal or edit_file. */
  toolName?: string;
  name: string;
  target: string;
  detail: string;
  state: ToolState;
  duration?: string;
  statusText?: string;
  /** UI Lab override; production defaults come from the renderer catalog. */
  defaultOpen?: boolean;
}

export interface SessionSummary {
  id: string;
  title: string;
  branch: string;
  state: "running" | "queued" | "completed" | "attention";
  elapsed: string;
  additions: number;
  deletions: number;
  children?: SessionSummary[];
}
