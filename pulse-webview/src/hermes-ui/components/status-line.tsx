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
// Pulse deviation: upstream reads per-session atoms through `useSessionView()`
// (the fork runs many transcripts at once). This tier has one transcript per
// tree, so the same signals arrive as props on `RunSignals`.

import { useEffect, useState, type ReactNode } from 'react';

import { activitySignature, toolNarratesWait, TURN_QUIET_S } from '../model/turn-activity';
import { toolPresentVerb } from '../model/run-summary';
import { formatElapsed, useElapsedSeconds } from '../model/activity-timer';
import type { PulseMessagePart, PulseRunState } from '../pulse/types';
import { cn } from '../lib/cn';
import { StableText } from './stable-text';
import { SCAFFOLD_LABEL_CLASS, SCAFFOLD_META_CLASS } from './scaffold-row';

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
    <div aria-label={label} aria-live="polite" className={cn('pulse-scaffold-status', className)} data-conversation-scaffold="" role="status">
      {children}
    </div>
  );
}

function Pulse() {
  return <span aria-hidden className="pulse-scaffold-pulse" />;
}

function HintText({ children }: { children: ReactNode }) {
  return <span className={cn(SCAFFOLD_LABEL_CLASS, 'pulse-shimmer', 'pulse-scaffold-hint')}>{children}</span>;
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
    <ScaffoldStatus data-slot="aui_response-loading" label={hint || 'Pulse is working'}>
      <Pulse />
      {hint && <HintText>{hint}</HintText>}
      <span className={SCAFFOLD_META_CLASS}>
        <StableText>{formatElapsed(elapsed)}</StableText>
      </span>
    </ScaffoldStatus>
  );
}

export interface TurnActivityIndicatorProps {
  content: readonly PulseMessagePart[];
  messageRunning: boolean;
  run: PulseRunState;
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
    <ScaffoldStatus data-slot="aui_turn-activity" label={hint || 'Pulse is working'}>
      <Pulse />
      {hint && <HintText>{hint}</HintText>}
      <span className={SCAFFOLD_META_CLASS}>
        <StableText>{formatElapsed(elapsed)}</StableText>
      </span>
    </ScaffoldStatus>
  );
}

/** Pulse-only surface (plan_updated / verification_updated / runtime_degraded
 *  frames have no upstream counterpart in this file): the run's plan and its
 *  verification ledger, as scaffold lines, so "done" is always the claim the
 *  checks back rather than a sentence the model wrote about itself. */
export function RunStatusPanel({ run }: { run: PulseRunState }) {
  if (run.plan.length === 0 && (run.verification?.length ?? 0) === 0 && !run.degraded) {
    return null;
  }

  return (
    <div className="pulse-run-status" data-conversation-scaffold="" data-slot="pulse-run-status">
      {run.plan.length > 0 && (
        <ol className="pulse-run-status__plan">
          {run.plan.map((step, index) => (
            <li className={`pulse-run-status__step pulse-run-status__step--${step.status}`} key={index}>
              <span>{step.title}</span>
              {step.detail && <span className={SCAFFOLD_META_CLASS}>{step.detail}</span>}
            </li>
          ))}
        </ol>
      )}
      {(run.verification?.length ?? 0) > 0 && (
        <div className="pulse-run-status__checks">
          {run.verification?.map((check, index) => (
            <span className={`pulse-run-status__check pulse-run-status__check--${check.status}`} key={index} title={check.detail}>
              {check.title}
            </span>
          ))}
        </div>
      )}
      {run.degraded && <p className="pulse-run-status__degraded">{run.degraded}</p>}
    </div>
  );
}
