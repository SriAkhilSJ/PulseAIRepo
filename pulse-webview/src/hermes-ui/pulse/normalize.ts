// The one place the ported UI meets Pulse's backend.
//
// `transcriptFromMessages` folds AG-UI / CopilotKit messages (assistant text +
// tool calls whose results land by mutation, plus agent `state`) into the
// Hermes view model. `reducePulseEvent` replays bridge-protocol-v2 frames over
// a transcript, which is what the desktop fork's renderer feeds and what this
// tier receives when the runtime proxies raw events. Both produce the same
// shape, so a component never has to know which transport it came from.

import type { PulseApproval, PulseMessage, PulseMessagePart, PulsePlanStep, PulseRunState, PulseTranscript } from './types';
import { EMPTY_TRANSCRIPT } from './types';
import type { ToolPart } from '../model/types';

type Rec = Record<string, unknown>;

function rec(value: unknown): Rec {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Rec) : {};
}

function str(source: unknown, keys: readonly string[]): string {
  const record = rec(source);

  for (const key of keys) {
    const value = record[key];

    if (typeof value === 'string' && value) {
      return value;
    }
  }

  return '';
}

/** Pulse tool results arrive as strings (JSON or text) or objects; the model
 *  keeps the raw value so `parseMaybeObject` can decide, exactly as upstream. */
function resultValue(value: unknown): unknown {
  return value === undefined ? undefined : value;
}

export function toolPartFromCall(call: unknown, result: unknown, isError = false): ToolPart {
  const record = rec(call);
  const fn = rec(record.function);

  return {
    args: record.arguments ?? (typeof fn.arguments === 'string' ? fn.arguments : (record.args ?? fn.args ?? '')),
    isError: isError || undefined,
    result: resultValue(result),
    toolCallId: str(record, ['tool_id', 'id', 'tool_call_id', 'toolCallId']) || undefined,
    toolName: str(record, ['name', 'tool_name', 'tool']) || str(fn, ['name']) || 'tool',
    type: 'tool-call',
  };
}

/** AG-UI / CopilotKit message list → transcript. Tool results are matched by
 *  tool_call_id from the following `role: 'tool'` messages, the same pairing
 *  rule Pulse's own receipt path uses (a start without an end stays `running`). */
export function transcriptFromMessages(messages: readonly unknown[], state?: unknown, running = false): PulseTranscript {
  const results = new Map<string, { isError: boolean; result: unknown }>();

  for (const raw of messages) {
    const message = rec(raw);

    if (str(message, ['role']) !== 'tool') {
      continue;
    }

    const id = str(message, ['tool_call_id', 'toolCallId', 'id']);

    if (id) {
      results.set(id, { isError: Boolean(message.error) || str(message, ['name']).length === 0 && false, result: message.content });
    }
  }

  const turns: PulseMessage[] = [];

  for (const raw of messages) {
    const message = rec(raw);
    const role = str(message, ['role']);

    if (role !== 'user' && role !== 'assistant' && role !== 'system') {
      continue;
    }

    const content: PulseMessagePart[] = [];
    const text = str(message, ['content', 'text']);

    if (text) {
      content.push({ text, type: 'text' });
    }

    const calls = Array.isArray(message.toolCalls) ? message.toolCalls : [];

    for (const call of calls) {
      const part = toolPartFromCall(call, undefined);
      const settled = part.toolCallId ? results.get(part.toolCallId) : undefined;

      content.push(settled ? { ...part, isError: settled.isError || undefined, result: settled.result } : part);
    }

    turns.push({
      content,
      createdAt: typeof message.timestamp === 'number' ? message.timestamp : undefined,
      id: str(message, ['id']) || `m-${turns.length}`,
      role: role as PulseMessage['role'],
    });
  }

  return {
    approvals: [],
    messages: turns,
    run: runStateFromAgent(state ?? {}, running),
  };
}

function runStateFromAgent(stateValue: unknown, running: boolean): PulseRunState {
  const state = rec(stateValue);
  const plan: PulsePlanStep[] = Array.isArray(state.plan)
    ? (state.plan as unknown[]).map(step => ({
        detail: str(step, ['detail', 'why', 'description']),
        status: planStatus(str(step, ['status', 'state'])),
        title: str(step, ['title', 'step', 'description', 'goal']) || 'Plan step',
      }))
    : [];

  return {
    busy: running,
    mode: str(state, ['execution_mode', 'mode']) || undefined,
    plan,
    planGoal: str(state, ['plan_goal']) || undefined,
    provider: str(state, ['provider']) || undefined,
    model: str(state, ['model']) || undefined,
    step: str(state, ['current_step', 'step']) || undefined,
    subagents: Array.isArray(state.subagents)
      ? (state.subagents as unknown[]).map(agent => ({
          id: str(agent, ['id', 'agent_id']) || `sub-${String(agent)}`.slice(0, 8),
          status: (['failed', 'running', 'queued', 'done'] as const).includes(planStatus(str(agent, ['status'])) as never)
            ? (planStatus(str(agent, ['status'])) as PulseRunState['subagents'][number]['status'])
            : 'queued',
          summary: str(agent, ['summary', 'result']) || undefined,
          task: str(agent, ['task', 'goal', 'title']) || 'Subtask',
        }))
      : [],
    verification: Array.isArray(state.verification)
      ? (state.verification as unknown[]).map(check => ({
          detail: str(check, ['detail', 'output', 'evidence']),
          status: verifyStatus(str(check, ['status', 'result'])),
          title: str(check, ['title', 'check', 'name']) || 'Check',
        }))
      : [],
  };
}

function planStatus(value: string): PulsePlanStep['status'] {
  const lower = (value || '').toLowerCase();

  if (/fail|error|denied|blocked/.test(lower)) {
    return 'failed';
  }

  if (/done|complete|pass|success|verified/.test(lower)) {
    return 'done';
  }

  if (/run|progress|active/.test(lower)) {
    return 'running';
  }

  if (/skip/.test(lower)) {
    return 'skipped';
  }

  return 'pending';
}

function verifyStatus(value: string): NonNullable<PulseRunState['verification']>[number]['status'] {
  const lower = (value || '').toLowerCase();

  if (/fail|error/.test(lower)) {
    return 'failed';
  }

  if (/pass|success|ok|true/.test(lower)) {
    return 'passed';
  }

  if (/run|progress/.test(lower)) {
    return 'running';
  }

  return 'not-run';
}

// =========================================================================
// Bridge protocol v2 replay
// =========================================================================

/** Apply one Pulse bridge frame to a transcript, returning a new one.
 *  Unknown frames are ignored rather than fatal — the protocol is additive and
 *  a newer agent must not blank an older webview. */
/**
 * Pulse's protocol v2 frames are FLAT: `BridgeServer._project_event` emits
 * `{type, event_id, timestamp, session_id, turn_id, workspace_id, ...fields}` —
 * `tool_id`, `name`, `arguments`, `status`, `result`, `warning`, `diff` all sit at
 * the top level, and `plan_updated` / `verification_updated` / `subagent_updated`
 * are `{...base, ...payload}` too. A nested `{type, payload}` is still accepted
 * because the durable journal writes that shape before projection, and `payload`
 * loses to a top-level key whenever both are present.
 */
function frameFields(frame: unknown): { name: string; fields: Rec } {
  const event = rec(frame);
  const name = str(event, ['type', 'event']);
  const { type: _type, event: _event, payload: payloadValue, data: dataValue, ...rest } = event;

  return { fields: { ...rec(payloadValue ?? dataValue), ...rest }, name };
}

export function reducePulseEvent(transcript: PulseTranscript, frame: unknown): PulseTranscript {
  const { fields: payload, name } = frameFields(frame);
  const next: PulseTranscript = { ...transcript, messages: [...transcript.messages], run: { ...transcript.run } };
  const tail = (): PulseMessage => {
    const last = next.messages[next.messages.length - 1];

    if (last && last.role === 'assistant') {
      return last;
    }

    const created: PulseMessage = { content: [], id: `turn-${next.messages.length}`, role: 'assistant' };

    next.messages.push(created);

    return created;
  };
  const replaceTail = (message: PulseMessage) => {
    next.messages[next.messages.length - 1] = message;
  };

  switch (name) {
    case 'turn_started': {
      next.run.busy = true;
      const ts = payload.timestamp ?? payload.ts;

      next.run.turnStartedAt = typeof ts === 'number' ? ts * (ts < 1e12 ? 1000 : 1) : Date.now();
      next.messages.push({ content: [], id: str(payload, ['turn_id', 'id']) || `turn-${next.messages.length}`, role: 'assistant' });

      break;
    }
    case 'token': {
      const message = tail();
      const text = str(payload, ['text', 'token', 'delta']);
      const parts = [...message.content];
      const last = parts[parts.length - 1];

      if (last && last.type === 'text') {
        parts[parts.length - 1] = { text: last.text + text, type: 'text' };
      } else if (text) {
        parts.push({ text, type: 'text' });
      }

      replaceTail({ ...message, content: parts });
      break;
    }
    case 'tool_call_start': {
      const message = tail();
      const part = toolPartFromCall(payload, undefined);

      replaceTail({ ...message, content: [...message.content, part] });
      break;
    }
    case 'tool_call_end': {
      for (let i = next.messages.length - 1; i >= 0; i -= 1) {
        const message = next.messages[i] as PulseMessage;
        const id = str(payload, ['tool_id', 'tool_call_id', 'id']);

        const index = message.content.findIndex(part => part.type === 'tool-call' && (part.toolCallId === id || !id));

        if (index === -1) {
          continue;
        }

        const part = message.content[index] as ToolPart;
        const failed = /fail|error|denied|cancel/.test(str(payload, ['status', 'state']));

        replaceTailMessage(next, i, {
          ...message,
          content: message.content.map((entry, entryIndex) =>
            entryIndex === index ? ({ ...part, isError: failed || undefined, result: resultValue(payload.result ?? payload.output ?? payload) } as ToolPart) : entry,
          ),
        });
        break;
      }

      break;
    }
    case 'plan_updated': {
      next.run.plan = Array.isArray(payload.steps)
        ? (payload.steps as unknown[]).map(step => ({
            detail: str(step, ['detail', 'why']),
            status: planStatus(str(step, ['status'])),
            title: str(step, ['title', 'text', 'description', 'goal']) || 'Plan step',
          }))
        : next.run.plan;
      next.run.planGoal = str(payload, ['goal']) || next.run.planGoal;
      break;
    }
    case 'verification_updated': {
      next.run.verification = Array.isArray(payload.checks)
        ? (payload.checks as unknown[]).map(check => ({
            detail: str(check, ['detail', 'output']),
            status: verifyStatus(str(check, ['status', 'result'])),
            title: str(check, ['title', 'name']) || 'Check',
          }))
        : next.run.verification;
      break;
    }
    case 'safety_request': {
      // Keys are Pulse's own: `ApprovalQueue.request()` returns
      // {id, session_id, tool_name, tool_args, diff, status, always_allow,
      // created_at} and chat_graph adds `warning` + `thread_id`.
      const diff = rec(payload.diff);
      const approval: PulseApproval = {
        alwaysAllow: typeof payload.always_allow === 'boolean' ? payload.always_allow : undefined,
        args: payload.arguments ?? payload.tool_args ?? payload.args,
        created_at: typeof payload.created_at === 'number' ? payload.created_at : undefined,
        diff: diff.path || diff.patch || diff.inline_diff ? {
          patch: str(diff, ['patch', 'inline_diff', 'diff']),
          path: str(diff, ['path', 'file_path']),
        } : undefined,
        reason: str(payload, ['warning', 'reason', 'message']) || 'The agent wants to run a guarded action.',
        toolCallId: str(payload, ['tool_id', 'id', 'tool_call_id']) || undefined,
        toolName: str(payload, ['name', 'tool_name', 'tool']) || 'action',
      };

      // Resolved approvals must not linger: the queue drops them, and a stale
      // bar would offer a decision that can no longer change anything.
      next.approvals = approval.toolCallId
        ? [...next.approvals.filter(entry => entry.toolCallId !== approval.toolCallId), approval]
        : [...next.approvals, approval];
      break;
    }
    case 'safety_resolved':
    case 'tool_approval_resolved': {
      const id = str(payload, ['tool_id', 'id', 'tool_call_id']);

      next.approvals = id ? next.approvals.filter(entry => entry.toolCallId !== id) : [];
      break;
    }
    case 'subagent_updated': {
      const id = str(payload, ['id', 'agent_id', 'subagent_id']) || `sub-${next.run.subagents.length}`;
      const existing = next.run.subagents.find(agent => agent.id === id);
      const updated = {
        id,
        status: (planStatus(str(payload, ['status'])) === 'done' ? 'done' : planStatus(str(payload, ['status']))) as PulseRunState['subagents'][number]['status'],
        summary: str(payload, ['summary', 'result']) || existing?.summary,
        task: str(payload, ['task', 'goal']) || existing?.task || 'Subtask',
      };

      next.run.subagents = existing ? next.run.subagents.map(agent => (agent.id === id ? updated : agent)) : [...next.run.subagents, updated];
      break;
    }
    case 'reasoning': {
      const message = tail();

      replaceTail({ ...message, content: [...message.content, { text: str(payload, ['text', 'reasoning']), type: 'text' }] });
      break;
    }
    case 'runtime_degraded': {
      next.run.degraded = str(payload, ['reason', 'message']) || 'A capability is unavailable and was reported honestly.';
      break;
    }
    case 'turn_done': {
      next.run.busy = false;
      break;
    }
    case 'turn_failed': {
      next.run.busy = false;

      const message = tail();

      replaceTail({ ...message, failure: str(payload, ['error', 'reason']) || 'The turn ended without a verified result.' });
      break;
    }
    case 'session_info': {
      // `session_resume` answers with the projected journal, oldest first — the
      // same reducer, applied in order, so a resumed session paints exactly what
      // the live one did. It folds into the INCOMING transcript, not the frame's
      // own copy: a resume replaces the transcript rather than appending to it.
      const events = Array.isArray(payload.events) ? (payload.events as unknown[]) : [];
      let replayed: PulseTranscript = transcript;

      for (const entry of events) {
        replayed = reducePulseEvent(replayed, entry);
      }

      const status = rec(payload.agent_status);

      if (Object.keys(status).length > 0) {
        replayed = {
          ...replayed,
          run: { ...replayed.run, model: str(status, ['model']) || replayed.run.model, provider: str(status, ['provider']) || replayed.run.provider },
        };
      }

      return replayed;
    }
    default:
      return transcript;
  }

  return next;
}

function replaceTailMessage(transcript: PulseTranscript, index: number, message: PulseMessage): void {
  transcript.messages[index] = message;
}

/** An empty session still needs the identity-shaped affordances the fork shows. */
export function emptyTranscript(): PulseTranscript {
  return { ...EMPTY_TRANSCRIPT, approvals: [], messages: [], run: { ...EMPTY_TRANSCRIPT.run, plan: [], subagents: [], verification: [] } };
}
