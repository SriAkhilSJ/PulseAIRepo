// Ported from hermes-agent `thread/status.tsx` :: `StatusRow` (the local one),
// `HintText`, `useStatusHint`, `ResponseLoadingIndicator`, `TurnActivityIndicator`
// @ a9c783f2 (270 lines).
//
// The tail activity row. The pre-first-token spinner goes away once content
// flows, but a turn keeps working through gaps it produces nothing during —
// between one tool result landing and the next call arriving, while the provider
// thinks, while a sealed bubble waits on the next one. So this row follows the
// SAME busy signal the composer does, and times every gap from the moment the
// turn LAST showed something rather than from its own mount. What it doesn't do
// is double-narrate: a tool call in flight already carries its own row and timer.
//
// Crusor deviation: upstream reads per-session atoms through `useSessionView()`
// (the fork runs many transcripts at once). This tier has one transcript per
// tree, so the same signals arrive as props on `RunSignals`.

import { useEffect, useState, type ReactNode } from 'react';

import { activitySignature, toolNarratesWait, TURN_QUIET_S } from '../model/turn-activity';
import { toolPresentVerb } from '../model/run-summary';
import { formatElapsed, useElapsedSeconds } from '../model/activity-timer';
import type { CrusorMessagePart, CrusorRunState } from '../crusor/types';
import { cn } from '../lib/cn';
import { StableText } from './stable-text';
import { SCAFFOLD_LABEL_CLASS, SCAFFOLD_META_CLASS } from './scaffold-row';
import { StatusPulse } from './status-pulse';

// Long enough that a tool whose arguments arrive in a few frames never gets to
// strobe a label, short enough that a real wait is named almost immediately.
export const DRAFTING_REVEAL_MS = 200;

export interface RunSignals {
  busy: boolean;
  /** Compaction is in flight — it outranks every other hint. */
  compacting?: boolean;
  /** A question the user is answering: the turn is paused on them, not working,
   *  so don't resurrect the thinking timer while they decide. */
  awaitingInput?: boolean;
  /** Epoch ms this turn began, or undefined between turns. */
  turnStartedAt?: number;
}

/** A status line is scaffolding like any other — "Editing" while the model drafts
 *  a call is the same kind of line as "Explored 3 files" once it has run, and
 *  reads as one continuous column only if it shares their type and colour. */
export function ScaffoldStatus({ children, className, label }: { children: ReactNode; className?: string; label: string }) {
  return (
    <div aria-label={label} aria-live="polite" className={cn('crusor-scaffold-status', className)} data-conversation-scaffold="" role="status">
      {children}
    </div>
  );
}

function Crusor() {
  return <StatusPulse aria-hidden className="crusor-scaffold-crusor" kind="opacity" />;
}

function HintText({ children }: { children: ReactNode }) {
  return <span className={cn(SCAFFOLD_LABEL_CLASS, 'crusor-scaffold-hint')}>{children}</span>;
}

/** What to call the wait, if it deserves a name. Compaction outranks a draft —
 *  it's rarer, slower, and explains a transcript that looks like it reset. */
export function useStatusHint(compacting: boolean | undefined, hintName: string): string {
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    setRevealed(false);

    if (!hintName) {
      return;
    }

    const id = window.setTimeout(() => setRevealed(true), DRAFTING_REVEAL_MS);

    return () => window.clearTimeout(id);
  }, [hintName]);

  if (compacting) {
    return COMPACTION_LABEL;
  }

  return revealed && hintName ? toolPresentVerb(hintName) : '';
}

export const COMPACTION_LABEL = 'Summarizing thread';

export function ResponseLoadingIndicator({ step, signals }: { signals: RunSignals; step?: string }) {
  const hint = useStatusHint(signals.compacting, step ?? '');
  const elapsed = useElapsedSeconds(true, undefined, signals.turnStartedAt);

  return (
    <ScaffoldStatus data-slot="aui_response-loading" label={hint || 'Crusor is working'}>
      <Crusor />
      {hint && <HintText>{hint}</HintText>}
      <span className={SCAFFOLD_META_CLASS}>
        <StableText>{formatElapsed(elapsed)}</StableText>
      </span>
    </ScaffoldStatus>
  );
}

export interface TurnActivityIndicatorProps {
  content: readonly CrusorMessagePart[];
  messageRunning: boolean;
  run: CrusorRunState;
  signals: RunSignals;
}

export function TurnActivityIndicator({ content, messageRunning, run, signals }: TurnActivityIndicatorProps) {
  const activity = activitySignature(content);
  // Timestamp of the last visible progress, held from the moment the quiet spell
  // qualifies. Holding the TIMESTAMP (not a boolean) is what lets the timer read
  // "quiet for 12s" rather than the age of this component, which is the whole
  // turn so far.
  const [quietSince, setQuietSince] = useState<number | undefined>(undefined);
  const hint = useStatusHint(signals.compacting, run.step ?? '');
  // A tool run at the tail already narrates the wait — its summary counts the
  // calls, its ticker names the current one, and it carries its own timer. A
  // second spinner under that adds a line and says nothing new.
  const toolNarrating = toolNarratesWait(content);
  // Streaming counts as working too, and it leads busy by a flush on the first
  // turn of a fresh chat — so the row can't wait for the store to catch up.
  const working = signals.busy || messageRunning;
  const active = working && !signals.awaitingInput && !toolNarrating && (Boolean(hint) || quietSince !== undefined);

  useEffect(() => {
    setQuietSince(undefined);

    const seenAt = Date.now();
    const id = window.setTimeout(() => setQuietSince(seenAt), TURN_QUIET_S * 1000);

    return () => window.clearTimeout(id);
  }, [activity]);

  // Compaction owns the whole turn, so it keeps counting from the turn's start;
  // anything else counts from the moment the turn last produced something.
  const elapsed = useElapsedSeconds(active, undefined, signals.compacting ? signals.turnStartedAt : (quietSince ?? signals.turnStartedAt));

  if (!active) {
    return null;
  }

  return (
    <ScaffoldStatus data-slot="aui_turn-activity" label={hint || 'Crusor is working'}>
      <Crusor />
      {hint && <HintText>{hint}</HintText>}
      <span className={SCAFFOLD_META_CLASS}>
        <StableText>{formatElapsed(elapsed)}</StableText>
      </span>
    </ScaffoldStatus>
  );
}

/** Crusor-only surface (plan_updated / verification_updated / runtime_degraded
 *  frames have no upstream counterpart in this file): the run's plan and its
 *  verification ledger, as scaffold lines, so "done" is always the claim the
 *  checks back rather than a sentence the model wrote about itself.
 *
 *  Plan mode — Hermes desktop parity + collapsable dropdown (user request):
 *  - Collapsable header with progress count (e.g. "Plan: 3/8 • Turbojet engine")
 *  - Dropdown caret on right (DisclosureRow style)
 *  - Expanded: ol with status glyphs (○ pending, ◐ running, ● done, ✕ failed, ⊘ skipped)
 *  - Matches screenshot: scaffold list with circles, collapsable
 */

function planGlyph(status: string): string {
  switch (status) {
    case 'done': return '✓';
    case 'running': return '◐';
    case 'failed': return '✕';
    case 'skipped': return '⊘';
    default: return '○';
  }
}

function agentColor(name: string): string {
  const palette = ['#0b6bcb', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
  let hash = 0;
  for (let i = 0; i < (name||'').length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return palette[hash % palette.length];
}

export function RunStatusPanel({ run }: { run: CrusorRunState }) {
  // User request 2026-09-12: plan checklist makes chat box small, todo list UI
  // already displays perfectly via tool cards. Hide the scaffold plan panel
  // entirely to maximize chat composer space. Keep verification/degraded if
  // needed, but plan list itself is removed.
  // If you need it back: set CRUSORAI_SHOW_PLAN_PANEL=1 or revert this file.
  const showPlan = (() => {
    try {
      const v = (typeof window !== 'undefined' ? (window as any).__CRUSORAI_SHOW_PLAN_PANEL__ : undefined);
      if (typeof v === 'string') return v.toLowerCase() in { '1': 1, 'true': 1, 'yes': 1, 'on': 1 } as any;
    } catch {}
    return false; // default hidden per user request
  })();

  const hasSubagents = (run.subagents?.length ?? 0) > 0;
  const hasVerification = (run.verification?.length ?? 0) > 0;
  const hasDegraded = !!run.degraded;

  if (!showPlan) {
    if (!hasVerification && !hasDegraded && !hasSubagents) {
      return null;
    }
    return (
      <div className="crusor-run-status crusor-run-status--dropdown" data-conversation-scaffold="" data-slot="crusor-run-status">
        {hasSubagents && (
          <div className="crusor-run-status__subagents" style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
            {run.subagents.map((sa: any, idx: number) => {
              const color = agentColor(sa.agentName || sa.task || 'agent');
              const running = sa.status === 'running' || sa.status === 'queued';
              const sessionId = sa.childThreadId || sa.id;
              return (
                <div
                  key={sessionId || idx}
                  data-component="task-tool-card"
                  data-testid="task-tool-card"
                  style={{ ['--task-agent-color' as any]: color, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff', cursor: sessionId ? 'pointer' : 'default' } as any}
                  onClick={sessionId ? () => {
                    try {
                      const ev = new CustomEvent('crusorai:navigate-to-session', { detail: { sessionId } });
                      window.dispatchEvent(ev);
                    } catch {}
                  } : undefined}
                  title={sa.task}
                >
                  <span style={{ color, fontSize: 12 }}>{running ? '◍' : '●'}</span>
                  <span style={{ fontWeight: 600, textTransform: 'capitalize', color, fontSize: 12 }}>{sa.agentName || 'general'}</span>
                  <span style={{ fontSize: 12, color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                    {sa.description || sa.task}{sa.background ? ' (background)' : ''}{sa.toolCalls ? ` · ${sa.toolCalls} calls` : ''}
                  </span>
                  {sessionId && <span style={{ fontSize: 11, opacity: 0.6 }}>↗</span>}
                </div>
              );
            })}
          </div>
        )}
        {hasVerification && (
          <div className="crusor-run-status__checks">
            {run.verification?.map((check, index) => (
              <span className={`crusor-run-status__check crusor-run-status__check--${check.status}`} key={index} title={check.detail}>
                {check.title}
              </span>
            ))}
          </div>
        )}
        {run.degraded && <p className="crusor-run-status__degraded">{run.degraded}</p>}
      </div>
    );
  }

  const [open, setOpen] = useState(() => {
    const hasRunning = run.plan.some(s => s.status === 'running');
    const allDone = run.plan.length > 0 && run.plan.every(s => s.status === 'done' || s.status === 'skipped');
    return hasRunning || !allDone;
  });

  useEffect(() => {
    if (run.plan.some(s => s.status === 'running')) setOpen(true);
  }, [run.plan]);

  if (run.plan.length === 0 && (run.verification?.length ?? 0) === 0 && !run.degraded) {
    return null;
  }

  const doneCount = run.plan.filter(s => s.status === 'done').length;
  const totalCount = run.plan.length;
  const progressLabel = totalCount > 0 ? `${doneCount}/${totalCount}` : '';

  return (
    <div className="crusor-run-status crusor-run-status--dropdown" data-conversation-scaffold="" data-slot="crusor-run-status">
      {run.plan.length > 0 && (
        <div className="crusor-run-status__dropdown">
          <button
            aria-expanded={open}
            className="crusor-run-status__dropdown-header"
            onClick={() => setOpen(v => !v)}
            type="button"
          >
            <span className="crusor-run-status__dropdown-title">
              <span className="crusor-run-status__dropdown-icon">▤</span>
              <span>Plan</span>
              {progressLabel && <span className="crusor-run-status__dropdown-count">{progressLabel}</span>}
              {run.planGoal && <span className="crusor-run-status__dropdown-goal" title={run.planGoal}>• {run.planGoal.slice(0, 60)}</span>}
            </span>
            <span className="crusor-run-status__dropdown-caret" data-open={open ? 'true' : 'false'}>▾</span>
          </button>
          {open && (
            <ol className="crusor-run-status__plan crusor-run-status__plan--expanded">
              {run.plan.map((step, index) => (
                <li className={`crusor-run-status__step crusor-run-status__step--${step.status}`} key={index} title={step.detail || step.title}>
                  <span className="crusor-run-status__step-glyph">{planGlyph(step.status)}</span>
                  <span className="crusor-run-status__step-title">{step.title}</span>
                  {step.detail && <span className={SCAFFOLD_META_CLASS}>{step.detail}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
      {(run.verification?.length ?? 0) > 0 && (
        <div className="crusor-run-status__checks">
          {run.verification?.map((check, index) => (
            <span className={`crusor-run-status__check crusor-run-status__check--${check.status}`} key={index} title={check.detail}>
              {check.title}
            </span>
          ))}
        </div>
      )}
      {run.degraded && <p className="crusor-run-status__degraded">{run.degraded}</p>}
    </div>
  );
}
