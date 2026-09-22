// Crusor binding for the ported transcript. Two transports, one view model:
//
//   1. `agent` (CopilotKit) — the CopilotKit tier. `useAgent()` gives the AG-UI
//      message list + `state` + `isRunning`; `transcriptFromMessages` folds them.
//      Stop maps to `agent.abortRun()`, which Crusor's graph already treats as a
//      turn cancel (`src/runtime/turn_control.py`).
//   2. `frames` — bridge protocol v2 frames, replayed through `reduceCrusorEvent`.
//      A host that embeds this webview (the desktop fork's iframe) pushes frames
//      with `postMessage({source:'crusor-bridge', frame})`; nothing in the fork has
//      to know about these components, which is what makes pin-parity possible
//      without editing the fork.
//
// The hook is deliberately NOT what the tests exercise: `useCrusorTranscript`
// below takes the agent-shaped object as a parameter, so a jsdom test can drive
// the whole UI with a fake agent and zero provider — no runtime, no key, no
// tokens. `useCrusorThread` is the thin CopilotKit wrapper around it.

import { useAgent } from '@copilotkit/react-core/v2';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { emptyTranscript, reduceCrusorEvent, transcriptFromMessages } from './normalize';
import type { CrusorApproval, CrusorTranscript } from './types';
import type { RunSignals } from '../components/status-line';

/** The subset of `AbstractAgent` this UI reads. Structural, so a test can hand in
 *  a stub and the real agent satisfies it by shape. */
export interface CrusorAgentLike {
  addMessage?: (message: { content: string; id: string; role: 'user' }) => void;
  messages: readonly unknown[];
  runAgent?: () => Promise<unknown> | void;
  state?: unknown;
  isRunning?: boolean;
  abortRun?: () => void;
  pendingInterrupts?: readonly unknown[];
  subscribe?: (subscriber: { onEvent?: (params: { event: unknown }) => void }) => { unsubscribe: () => void };
}

export interface UseCrusorTranscriptOptions {
  agent?: CrusorAgentLike | null;
  /** Frames to replay on mount, oldest first (test/host-driven sessions). */
  initialFrames?: readonly unknown[];
  /** Listen for `postMessage({source:'crusor-bridge', frame})` from the host. */
  listenForBridgeFrames?: boolean;
}

export interface UseCrusorTranscriptResult {
  transcript: CrusorTranscript;
  signals: RunSignals;
  pendingApproval?: CrusorApproval;
  /** Replay one bridge frame — the same path the host's postMessage takes. */
  applyFrame: (frame: unknown) => void;
  /** Answer a pending approval. Notifies the host; the queue on the backend is
   *  the authority, and a decision nobody accepts is reported, not faked. */
  respondApproval: (choice: 'always' | 'once' | 'session' | 'deny', approval?: CrusorApproval) => void;
  submit: (text: string) => void;
  stop: () => void;
  sessionId: string;
  isChild: boolean;
  parentSessionId?: string;
  navigateToSession?: (id: string) => void;
}

function interruptToApproval(value: unknown): CrusorApproval | undefined {
  if (!value || typeof value !== 'object') {
    return undefined;
  }

  const interrupt = value as Record<string, unknown>;
  const toolName = typeof interrupt.tool === 'string' ? interrupt.tool : typeof interrupt.name === 'string' ? interrupt.name : '';
  const reason = typeof interrupt.message === 'string' ? interrupt.message : typeof interrupt.reason === 'string' ? interrupt.reason : '';

  if (!toolName && !reason) {
    return undefined;
  }

  return {
    args: interrupt.args ?? interrupt.tool_args,
    reason: reason || 'The agent is waiting for you before it continues.',
    toolCallId: typeof interrupt.id === 'string' ? interrupt.id : typeof interrupt.tool_call_id === 'string' ? interrupt.tool_call_id : undefined,
    toolName: toolName || 'action',
  };
}

export function useCrusorTranscript({ agent = null, initialFrames, listenForBridgeFrames = true }: UseCrusorTranscriptOptions = {}): UseCrusorTranscriptResult {
  const [frames, setFrames] = useState<readonly unknown[]>(() => (initialFrames ? [...initialFrames] : []));
  const [agentTick, setAgentTick] = useState(0);
  const [localDecisions, setLocalDecisions] = useState<Record<string, 'always' | 'deny' | 'once' | 'session'>>({});
  const lastSignature = useRef('');
  const [sessionId, setSessionId] = useState('default');
  const [parentMap, setParentMap] = useState<Map<string, string>>(new Map());
  const [childParentId, setChildParentId] = useState<string | undefined>(undefined);

  const applyFrame = useCallback((frame: unknown) => {
    setFrames(current => [...current, frame]);
  }, []);

  useEffect(() => {
    if (!listenForBridgeFrames || typeof window === 'undefined') {
      return;
    }

    const onMessage = (event: MessageEvent) => {
      const data = event.data as { frame?: unknown; source?: string } | null;

      if (!data || data.source !== 'crusor-bridge') {
        return;
      }

      applyFrame(data.frame);
    };

    const onNavigate = (event: Event) => {
      try {
        const ce = event as CustomEvent<{ sessionId: string }>;
        const sid = ce.detail?.sessionId;
        if (sid) {
          // For webview, navigation is just updating sessionId if host wants
          // Emit to parent as well
          window.parent?.postMessage?.({ source: 'crusor-ui', frame: { type: 'navigate', session_id: sid } }, '*');
        }
      } catch {}
    };

    window.addEventListener('message', onMessage);
    window.addEventListener('crusorai:navigate-to-session' as any, onNavigate);

    return () => {
      window.removeEventListener('message', onMessage);
      window.removeEventListener('crusorai:navigate-to-session' as any, onNavigate);
    };
  }, [applyFrame]);

  // Re-render on whatever the agent publishes. Upstream leans on assistant-ui
  // store throttling (`throttleMs` on useAgent); this tier coalesces by
  // signature so an identical message list never re-renders the transcript.
  useEffect(() => {
    if (!agent?.subscribe) {
      return;
    }

    const { unsubscribe } = agent.subscribe({
      onEvent: ({ event }) => {
        const signature = JSON.stringify((event as { type?: unknown })?.type ?? '');

        if (signature === lastSignature.current) {
          return;
        }

        lastSignature.current = signature;
        setAgentTick(value => value + 1);
      },
    });

    return () => unsubscribe();
  }, [agent]);

  const transcript = useMemo<CrusorTranscript>(() => {
    const base = agent ? transcriptFromMessages(agent.messages ?? [], agent.state, Boolean(agent.isRunning)) : emptyTranscript();
    let next = base;

    for (const frame of frames) {
      next = reduceCrusorEvent(next, frame);
    }

    // An interrupt the runtime published as "awaiting user" is an approval in
    // every sense the UI cares about, even though Crusor only enables the
    // approval channel on bridge sessions.
    const interruptApproval = agent ? interruptToApproval((agent.pendingInterrupts ?? [])[0]) : undefined;

    if (interruptApproval && next.approvals.length === 0) {
      next = { ...next, approvals: [interruptApproval] };
    }

    if (Object.keys(localDecisions).length > 0) {
      const pending = next.approvals.filter(approval => !approval.toolCallId || !localDecisions[approval.toolCallId]);

      next = { ...next, approvals: pending };
    }

    return next;
  }, [agent, agentTick, frames, localDecisions]);

  // Derive session meta from frames (OpenCode parity: parentMap)
  useEffect(() => {
    let curSid = sessionId;
    let curParentMap = new Map(parentMap);
    let curChildParent = childParentId;
    let changed = false;

    for (const frame of frames) {
      try {
        const f: any = frame as any;
        const payload = f.payload ?? f;
        const type = f.type ?? payload.type;
        if (type === 'session_info' || type === 'turn_started' || type === 'turn_done') {
          const sid = payload.session_id || payload.thread_id || payload.sessionId;
          if (sid && sid !== curSid) {
            curSid = sid;
            changed = true;
          }
        }
        if (type === 'subagent_updated' || type === 'subagent_list') {
          const list = type === 'subagent_list' ? (payload.subagents || []) : [payload];
          for (const item of list) {
            const childId = item.child_thread_id || item.childThreadId || item.subagent_id || item.id;
            const parentId = item.parent_session_id || item.parentSessionId || curSid;
            if (childId && parentId && !curParentMap.has(childId)) {
              curParentMap.set(childId, parentId);
              changed = true;
            }
          }
        }
      } catch {}
    }

    if (curParentMap.has(curSid)) {
      const parent = curParentMap.get(curSid);
      if (parent !== curChildParent) {
        curChildParent = parent;
        changed = true;
      }
    } else if (curSid.startsWith('sub-') && curChildParent === undefined) {
      curChildParent = 'parent';
      changed = true;
    } else if (!curParentMap.has(curSid) && !curSid.startsWith('sub-') && curChildParent !== undefined) {
      curChildParent = undefined;
      changed = true;
    }

    if (changed) {
      setSessionId(curSid);
      setParentMap(curParentMap);
      setChildParentId(curChildParent);
    }
  }, [frames, sessionId, parentMap, childParentId]);

  const respondApproval = useCallback(
    (choice: 'always' | 'once' | 'session' | 'deny', approval?: CrusorApproval) => {
      const approved = choice !== 'deny';
      const frame = {
        type: 'safety_reply',
        approved,
        always_allow: choice === 'always' || choice === 'session',
        tool_id: approval?.toolCallId,
      };

      // The host (fork shell, dev harness, test) owns delivery to the bridge
      // process: Crusor's approval queue is stdio-backed, so the browser cannot
      // reach it directly. Both channels are offered because a fork may prefer
      // either.
      if (typeof window !== 'undefined') {
        window.parent?.postMessage?.({ source: 'crusor-ui', frame }, '*');
        window.dispatchEvent(new CustomEvent('crusor:safety_reply', { detail: frame }));
      }

      if (approval?.toolCallId) {
        setLocalDecisions(current => ({ ...current, [approval.toolCallId as string]: choice }));
      }
    },
    []
  );

  const submit = useCallback(
    (text: string) => {
      const value = text.trim();

      if (!value || !agent?.addMessage) {
        return;
      }

      // Child lock: don't submit if child
      if (childParentId || sessionId.startsWith('sub-') || parentMap.has(sessionId)) {
        return;
      }

      agent.addMessage({ content: value, id: `user-${String(Date.now())}`, role: 'user' });
      void agent.runAgent?.();
    },
    [agent, childParentId, sessionId, parentMap]
  );

  const stop = useCallback(() => {
    agent?.abortRun?.();
  }, [agent]);

  const signals = useMemo<RunSignals>(
    () => ({
      awaitingInput: transcript.approvals.length > 0,
      busy: transcript.run.busy || Boolean(agent?.isRunning),
      turnStartedAt: transcript.run.turnStartedAt,
    }),
    [agent, transcript.approvals.length, transcript.run.busy, transcript.run.turnStartedAt]
  );

  const isChild = !!(childParentId || sessionId.startsWith('sub-') || parentMap.has(sessionId));

  const navigateToSession = useCallback((id: string) => {
    try {
      const ev = new CustomEvent('crusorai:navigate-to-session', { detail: { sessionId: id } });
      window.dispatchEvent(ev);
      window.parent?.postMessage?.({ source: 'crusor-ui', frame: { type: 'navigate', session_id: id } }, '*');
    } catch {}
  }, []);

  return {
    agent: agent ?? null,
    applyFrame,
    pendingApproval: transcript.approvals[0],
    respondApproval,
    signals,
    stop,
    submit,
    transcript,
    sessionId,
    isChild,
    parentSessionId: childParentId,
    navigateToSession,
  } as UseCrusorTranscriptResult;
}

export type UseCrusorThreadOptions = {
  agentId?: string;
};

export interface UseCrusorThreadResult extends UseCrusorTranscriptResult {
  agent: CrusorAgentLike;
}

/**
 * CopilotKit wrapper: the agent the provider already runs for `CopilotChat` is
 * the same one this transcript reads, so the ported UI and the stock chat
 * surface can never disagree about what the turn contains.
 *
 * Requires a `CopilotKitProvider` above it — which is why every component here
 * is also usable on its own with `useCrusorTranscript({ agent: null })`. Crusor's
 * approval channel is only opened on bridge sessions today
 * (`src/bridge/__main__.py` sets `approval_channel=True`; the Copilot Runtime
 * path does not), so an approval arriving in this tier means the runtime started
 * forwarding it, and `respondApproval` hands the decision to the host rather than
 * pretending the browser can reach the queue.
 */
export function useCrusorThread({ agentId = 'crusor_agent' }: UseCrusorThreadOptions = {}): UseCrusorThreadResult {
  // `throttleMs` coalesces the streaming re-renders the way upstream's
  // assistant-ui store throttle does; updates are left at the provider default so
  // a new CopilotKit minor cannot silently change what we subscribe to.
  const { agent } = useAgent({ agentId, throttleMs: 80 });
  const transcript = useCrusorTranscript({ agent: agent as unknown as CrusorAgentLike });

  return { ...transcript, agent: agent as unknown as CrusorAgentLike };
}
