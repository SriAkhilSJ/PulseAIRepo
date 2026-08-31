// Pulse's backend contract, in the shape the ported UI consumes.
//
// The transcript is NOT invented here: every field maps onto something Pulse
// actually emits — the AG-UI stream the Copilot Runtime proxies
// (RUN_STARTED / STEP_STARTED / STATE_SNAPSHOT / TOOL_CALL_* / RUN_FINISHED)
// and the bridge protocol v2 event names in src/bridge/protocol_v2.json
// (turn_started, token, reasoning, tool_call_start, tool_call_end,
// plan_updated, verification_updated, safety_request, subagent_updated,
// runtime_degraded, turn_done, turn_failed). Both shapes normalize into this
// one model so the CopilotKit tier and the desktop fork render from one
// source of truth.

import type { ToolPart } from '../model/types';

export type PulseToolCallPart = ToolPart;

export interface PulseTextPart {
  text: string;
  type: 'text';
}

export type PulseMessagePart = PulseTextPart | PulseToolCallPart;

export interface PulseMessage {
  content: PulseMessagePart[];
  createdAt?: number;
  id: string;
  role: 'assistant' | 'system' | 'user';
  /** Present when the assistant turn ended abnormally — the transcript must
   *  say so instead of rendering a confident-looking half answer. */
  failure?: string;
}

export interface PulsePlanStep {
  detail?: string;
  status: 'failed' | 'pending' | 'running' | 'skipped' | 'done';
  title: string;
}

/** One entry of Pulse's `ApprovalQueue` (src/dashboard/event_bus.py): the
 *  bridge republishes it as `safety_request`, and the reply frame is
 *  `{kind:"safety_reply", tool_id, approved, always_allow}`. `diff` is the
 *  proposed patch the graph publishes WITH the request, so the reviewer sees
 *  what they are approving rather than only a warning string. */
export interface PulseApproval {
  alwaysAllow?: boolean;
  args?: unknown;
  created_at?: number;
  diff?: { path?: string; patch?: string };
  /** `tool.approval.request` carries the graph's guard warning verbatim. */
  reason: string;
  toolCallId?: string;
  toolName: string;
}

export interface PulseSubAgent {
  id: string;
  status: 'failed' | 'running' | 'queued' | 'done';
  summary?: string;
  task: string;
}

export interface PulseRunState {
  /** Turn-level liveness: the composer's Stop button and the status line read
   *  the same value, so they can never disagree about whether we are working. */
  busy: boolean;
  degraded?: string;
  mode?: string;
  plan: PulsePlanStep[];
  planGoal?: string;
  provider?: string;
  model?: string;
  step?: string;
  subagents: PulseSubAgent[];
  turnStartedAt?: number;
  verification?: { detail?: string; status: 'failed' | 'not-run' | 'passed' | 'running'; title?: string }[];
}

export interface PulseTranscript {
  approvals: PulseApproval[];
  messages: PulseMessage[];
  run: PulseRunState;
}

export const EMPTY_TRANSCRIPT: PulseTranscript = {
  approvals: [],
  messages: [],
  run: { busy: false, plan: [], subagents: [], verification: [] },
};
