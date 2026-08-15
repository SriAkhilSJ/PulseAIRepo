// Portable subset of PulseAI Bridge Protocol events consumed by the UI.
// The production v2 schema will generate/validate both Python and TypeScript contracts.

export interface EventIdentity {
  session_id: string;
  turn_id?: string;
  event_id?: string;
  timestamp?: string;
}

export type PulseEvent =
  | ({ type: "turn_started" } & EventIdentity)
  | ({ type: "token"; text: string } & EventIdentity)
  | ({ type: "reasoning"; text: string } & EventIdentity)
  | ({ type: "plan_updated"; steps: unknown[] } & EventIdentity)
  | ({ type: "tool_call_start"; tool_id: string; name: string; arguments?: unknown } & EventIdentity)
  | ({ type: "tool_call_end"; tool_id: string; status: string; result?: unknown } & EventIdentity)
  | ({ type: "safety_request"; tool_id: string; name: string; diff?: unknown } & EventIdentity)
  | ({ type: "verification_updated"; status: string; evidence?: unknown } & EventIdentity)
  | ({ type: "subagent_updated"; subagent_id: string; state: string } & EventIdentity)
  | ({ type: "telemetry"; input?: number; output?: number; cache?: number; cost?: number } & EventIdentity)
  | ({ type: "checkpoint_event"; checkpoint_hash?: string } & EventIdentity)
  | ({ type: "turn_done"; message?: string; completed: boolean } & EventIdentity)
  | ({ type: "turn_failed"; error: string; completed: false } & EventIdentity)
  | ({ type: "runtime_degraded"; reason: string } & EventIdentity)
  | ({ type: "error"; message: string; fatal?: boolean } & Partial<EventIdentity>);

export interface PulseHost {
  sendPrompt(text: string): void;
  cancel(): void;
  steer(text: string): void;
  replyToSafety(toolId: string, approved: boolean, alwaysAllow?: boolean): void;
  openDiff(toolId: string): void;
  revealFile(path: string, line?: number): void;
  restoreCheckpoint(hash: string): void;
  subscribe(listener: (event: PulseEvent) => void): () => void;
}
