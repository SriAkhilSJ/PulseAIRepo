// Crusor's backend contract, in the shape the ported UI consumes.
//
// The transcript is NOT invented here: every field maps onto something Crusor
// actually emits — the AG-UI stream the Copilot Runtime proxies
// (RUN_STARTED / STEP_STARTED / STATE_SNAPSHOT / TOOL_CALL_* / RUN_FINISHED)
// and the bridge protocol v2 event names in src/bridge/protocol_v2.json
// (turn_started, token, reasoning, tool_call_start, tool_call_end,
// plan_updated, verification_updated, safety_request, subagent_updated,
// runtime_degraded, turn_done, turn_failed). Both shapes normalize into this
// one model so the CopilotKit tier and the desktop fork render from one
// source of truth.

import type { ToolPart } from '../model/types';

export type CrusorToolCallPart = ToolPart;

export interface CrusorTextPart {
  text: string;
  type: 'text';
}

export type CrusorMessagePart = CrusorTextPart | CrusorToolCallPart;

export interface CrusorMessage {
  content: CrusorMessagePart[];
  createdAt?: number;
  id: string;
  role: 'assistant' | 'system' | 'user';
  /** Present when the assistant turn ended abnormally — the transcript must
   *  say so instead of rendering a confident-looking half answer. */
  failure?: string;
}

export interface CrusorPlanStep {
  detail?: string;
  status: 'failed' | 'pending' | 'running' | 'skipped' | 'done';
  title: string;
}

/** One entry of Crusor's `ApprovalQueue` (src/dashboard/event_bus.py): the
 *  bridge republishes it as `safety_request`, and the reply frame is
 *  `{kind:"safety_reply", tool_id, approved, always_allow}`. `diff` is the
 *  proposed patch the graph publishes WITH the request, so the reviewer sees
 *  what they are approving rather than only a warning string. */
export interface CrusorApproval {
  alwaysAllow?: boolean;
  args?: unknown;
  created_at?: number;
  diff?: { path?: string; patch?: string };
  /** `tool.approval.request` carries the graph's guard warning verbatim. */
  reason: string;
  toolCallId?: string;
  toolName: string;
}

export interface CrusorSubAgent {
  id: string;
  status: 'failed' | 'running' | 'queued' | 'done';
  summary?: string;
  task: string;
  description?: string;
  agentName?: string;
  childThreadId?: string;
  parentSessionId?: string;
  toolCalls?: number;
  background?: boolean;
}

export interface CrusorRunState {
  /** Turn-level liveness: the composer's Stop button and the status line read
   *  the same value, so they can never disagree about whether we are working. */
  busy: boolean;
  degraded?: string;
  mode?: string;
  plan: CrusorPlanStep[];
  planGoal?: string;
  provider?: string;
  model?: string;
  step?: string;
  subagents: CrusorSubAgent[];
  turnStartedAt?: number;
  verification?: { detail?: string; status: 'failed' | 'not-run' | 'passed' | 'running'; title?: string }[];
}

export interface CrusorTranscript {
  approvals: CrusorApproval[];
  messages: CrusorMessage[];
  run: CrusorRunState;
}

export const EMPTY_TRANSCRIPT: CrusorTranscript = {
  approvals: [],
  messages: [],
  run: { busy: false, plan: [], subagents: [], verification: [] },
};
