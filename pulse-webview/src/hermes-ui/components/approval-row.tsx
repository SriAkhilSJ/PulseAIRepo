// Ported from hermes-agent `tool/approval.tsx` @ a9c783f2 (456 lines), reduced
// to what Pulse's backend can actually answer.
//
// Upstream's binding rule is kept verbatim in spirit: the strip is rendered by
// the pending tool row, POSITIONAL rather than command-matched, because the
// gateway's tool.start payload carries no structured args. Pulse is stricter —
// `ApprovalQueue` keys requests by tool_id, so `PulseApproval.toolCallId` lets
// a row claim its own request and fall back to the single pending one.
//
// Choices are Pulse's, not the gateway's: `approval_queue.resolve(tool_id,
// approved, always_allow, session_id)` is a boolean with a sticky flag, so the
// canonical `once|session|always|deny` menu collapses to Run / Allow for this
// session (always_allow) / Reject, and "always allow forever" — which upstream
// hides when the backend reports `allowPermanent: false` — is not offered at all
// rather than offered and ignored.

import { useCallback, useEffect, useState, type ReactNode } from 'react';

import type { PulseApproval } from '../pulse/types';
import { cn } from '../lib/cn';

/** Tools whose pending call can be the one blocking on approval. Upstream's set
 *  is `terminal|execute_code|patch|write_file`; Pulse's guarded surface is the
 *  mutation set chat_graph gates (`write_file, edit_file, copy_file,
 *  scaffold_nextjs`) plus the two shells it routes through the danger guard. */
export const APPROVAL_TOOLS = new Set(['run_terminal', 'execute_code', 'write_file', 'edit_file', 'copy_file', 'scaffold_nextjs']);

export type ApprovalChoice = 'always' | 'once' | 'session' | 'deny';

const isMac = typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.userAgent);

export interface ApprovalRowProps {
  approval: PulseApproval;
  /** Sends the decision. Pulse's bridge frame is
   *  `{kind: "safety_reply", tool_id, approved, always_allow}`. */
  onRespond: (choice: ApprovalChoice) => void;
  /** The proposed patch, published WITH the request (`diff` payload) — the
   *  reason this tier can show a real diff where upstream shows a command line. */
  children?: ReactNode;
}

/** Inline approval strip under the row that raised it. Deliberately does not
 *  repeat the command: the row above already shows it. */
export function ApprovalRow({ approval, children, onRespond }: ApprovalRowProps) {
  const [submitting, setSubmitting] = useState<null | ApprovalChoice>(null);
  const [showCommand, setShowCommand] = useState(false);
  const busy = submitting !== null;
  const command = commandFromArgs(approval.args);
  const hasCommand = command.trim().length > 0;

  const respond = useCallback(
    (choice: ApprovalChoice) => {
      if (busy) {
        return;
      }

      setSubmitting(choice);

      try {
        onRespond(choice);
      } finally {
        // The transcript removes the request when the resolved frame lands; this
        // only unsticks the strip if that round trip is a no-op (already answered
        // elsewhere, e.g. the keyboard path).
        window.setTimeout(() => setSubmitting(null), 400);
      }
    },
    [busy, onRespond]
  );

  // ⌘/Ctrl+Enter → Run, Esc → Reject.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        respond('once');
      } else if (event.key === 'Escape') {
        event.preventDefault();
        respond('deny');
      }
    };

    window.addEventListener('keydown', onKeyDown, true);

    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [respond]);

  return (
    <div className="pulse-approval" data-slot="tool-approval-inline" role="group">
      <div className="pulse-approval__bar">
        <span className="pulse-approval__warning" title={approval.reason}>
          {approval.reason}
        </span>
        <button
          className="pulse-approval__run"
          disabled={busy}
          onClick={() => respond('once')}
          type="button"
        >
          {submitting === 'once' ? '…' : 'Run'}
          {submitting !== 'once' && <span className="pulse-approval__key">{isMac ? '⌘⏎' : 'Ctrl⏎'}</span>}
        </button>
        <button
          className="pulse-approval__session"
          disabled={busy}
          onClick={() => respond('session')}
          type="button"
        >
          Allow for session
        </button>
        <button
          className="pulse-approval__deny"
          disabled={busy}
          onClick={() => respond('deny')}
          type="button"
        >
          {submitting === 'deny' ? '…' : 'Reject'}
          {submitting !== 'deny' && <span className="pulse-approval__key">Esc</span>}
        </button>
        {hasCommand && (
          <button
            aria-expanded={showCommand}
            className="pulse-approval__expand"
            onClick={() => setShowCommand(value => !value)}
            type="button"
          >
            Command <span className={cn('pulse-approval__caret', showCommand && 'pulse-approval__caret--open')}>▾</span>
          </button>
        )}
      </div>
      {showCommand && hasCommand && <pre className="pulse-approval__command">{command.trim()}</pre>}
      {children}
    </div>
  );
}

/** The one truncated line the strip can reveal in full — same reason upstream
 *  reads it from the event payload instead of the tool row. */
export function commandFromArgs(args: unknown): string {
  if (typeof args === 'string') {
    return args;
  }

  if (!args || typeof args !== 'object') {
    return '';
  }

  const record = args as Record<string, unknown>;

  for (const key of ['command', 'cmd', 'code', 'path', 'file_path', 'url', 'goal']) {
    const value = record[key];

    if (typeof value === 'string' && value) {
      return value;
    }
  }

  return '';
}

/** Whether a row is the one a pending approval is waiting on. Exported for the
 *  run header, which has to stop collapsing to a one-line ticker while a row is
 *  blocked on the user. */
export function approvalBlocksTool(approval: PulseApproval | undefined, toolName: string, toolCallId?: string): boolean {
  if (!approval || !APPROVAL_TOOLS.has(toolName)) {
    return false;
  }

  return !approval.toolCallId || !toolCallId || approval.toolCallId === toolCallId;
}
