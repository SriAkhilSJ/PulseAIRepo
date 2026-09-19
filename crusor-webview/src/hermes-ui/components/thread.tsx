// Ported from hermes-agent `thread/index.tsx` (631) + `thread/assistant-message.tsx`
// + `thread/list.tsx` (the React half) @ a9c783f2, reduced to the mechanisms that
// survive without assistant-ui: turn grouping, the DOM render page, the live
// tail exemption, stick-to-bottom, the timeline rail, and per-message part
// rendering.
//
// Deviations, all recorded in src/prompts/hermes/PROVENANCE.md:
//   - no `use-stick-to-bottom` / virtualizer: a plain "scroll if the user was
//     already at the bottom" rule, plus `content-visibility` on off-tail groups;
//   - no `MessageRenderBoundary`: this tier has no per-turn error boundary, so a
//     throwing renderer takes the transcript down in dev rather than a bubble —
//     the fork keeps its own boundary;
//   - no i18n, no Codicons, no Shiki (see tool-card / markdown-text).

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';

/** jsdom has no `CSS.escape`; ids here are tool/message ids, so escaping the two
 *  characters that could break the attribute selector is enough everywhere. */
function attrEscape(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

import { contentHasVisibleText, deriveToolParts, messageContentText } from '../model/content';
import { deriveTimelineEntries, sameTimelineEntries, activeTimelineIndex, type TimelineEntry } from '../model/timeline-data';
import { firstVisibleGroupIndex, groupsFromMessages, liveTailStart, RENDER_BUDGET, FIRST_PAINT_BUDGET, BACKFILL_STEP } from '../model/render-budget';
import type { CrusorApproval, CrusorMessage, CrusorRunState, CrusorTranscript } from '../crusor/types';
import { cn } from '../lib/cn';
import { ChangedFilesCard } from './changed-files-card';
import { EmptyState } from './empty-state';
import { MarkdownText } from './markdown-text';
import { resolveShowEarlierAction, TranscriptWindowProvider, useTranscriptWindow } from './transcript-window';
import { CrusorToolGroup, type ApprovalChoice } from './tool-run';
import { ResponseLoadingIndicator, RunStatusPanel, TurnActivityIndicator, type RunSignals } from './status-line';

export function CrusorUserMessage({ message }: { message: CrusorMessage }) {
  const text = messageContentText(message.content);

  return (
    <div className="crusor-user-message" data-message-role="user" data-slot="crusor-user-message">
      <p className="crusor-user-message__text">{text}</p>
    </div>
  );
}

export function CrusorSystemMessage({ message }: { message: CrusorMessage }) {
  return (
    <div className="crusor-system-message" data-slot="crusor-system-message">
      {messageContentText(message.content)}
    </div>
  );
}

export interface CrusorAssistantMessageProps {
  approval?: CrusorApproval;
  isLatest: boolean;
  message: CrusorMessage;
  respond?: (choice: ApprovalChoice) => void;
  reviewAction?: (path: string) => void;
  run: CrusorRunState;
  signals: RunSignals;
}

export function CrusorAssistantMessage({ approval, isLatest, message, respond, reviewAction, run, signals }: CrusorAssistantMessageProps) {
  const textParts = message.content.filter(part => part.type === 'text');
  const hasText = textParts.some(part => contentHasVisibleText([part]));
  const running = isLatest && signals.busy;

  return (
    <div className="crusor-assistant-message" data-message-role="assistant" data-slot="crusor-assistant-message">
      {message.content.some(part => part.type === 'tool-call') && (
        <CrusorToolGroup approval={approval} message={message} messageRunning={running} respond={respond} />
      )}
      {hasText && (
        <div className="crusor-assistant-message__text">
          {textParts.map((part, index) => (
            <MarkdownText key={index}>{part.text}</MarkdownText>
          ))}
        </div>
      )}
      {message.failure && <p className="crusor-assistant-message__failure">{message.failure}</p>}
      {isLatest && <ChangedFilesCard parts={deriveToolParts(message)} reviewAction={reviewAction} />}
      {isLatest && <RunStatusPanel run={run} />}
      {isLatest && (
        <TurnActivityIndicator content={message.content} messageRunning={running} run={run} signals={signals} />
      )}
    </div>
  );
}

/** The pre-first-token row: nothing of this turn has painted yet. */
function TurnPending({ signals, step }: { signals: RunSignals; step?: string }) {
  return <ResponseLoadingIndicator signals={signals} step={step} />;
}

export interface CrusorAgentThreadProps {
  className?: string;
  composer?: ReactNode;
  emptyState?: ReactNode;
  olderAvailable?: boolean;
  onExpandWindow?: () => void;
  reviewAction?: (path: string) => void;
  transcript: CrusorTranscript;
  signals: RunSignals;
  approvalRespond?: (choice: ApprovalChoice, approval: CrusorApproval) => void;
}

export function CrusorAgentThread({
  approvalRespond,
  className,
  composer,
  emptyState,
  olderAvailable = false,
  onExpandWindow,
  reviewAction,
  signals,
  transcript,
}: CrusorAgentThreadProps) {
  const messages = transcript.messages;
  const groups = useMemo(() => groupsFromMessages(messages), [messages]);
  // First paint spends a small budget (the turn(s) visible after scroll-to-bottom),
  // then backfills the rest in interruptible steps — a session switch must not
  // pay for the whole page in one synchronous commit.
  const [budget, setBudget] = useState(FIRST_PAINT_BUDGET);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);
  const offsetsRef = useRef<Array<number | null>>([]);
  const entriesRef = useRef<TimelineEntry[]>([]);
  const [activeEntry, setActiveEntry] = useState(0);

  useEffect(() => {
    if (budget >= RENDER_BUDGET) {
      return;
    }

    const id = window.setTimeout(() => setBudget(value => Math.min(RENDER_BUDGET, value + BACKFILL_STEP)), 120);

    return () => window.clearTimeout(id);
  }, [budget]);

  // Reset the page when the session changes, so switching to a short transcript
  // does not inherit a page sized for the long one.
  const sessionKey = messages[0]?.id ?? '';

  useEffect(() => {
    setBudget(FIRST_PAINT_BUDGET);
  }, [sessionKey]);

  const firstVisible = useMemo(() => firstVisibleGroupIndex(groups, budget, MIN_VISIBLE_GROUPS_FLOOR), [groups, budget]);
  const tailStart = useMemo(() => liveTailStart(groups), [groups]);
  const hiddenCount = firstVisible;
  const showEarlier = resolveShowEarlierAction(hiddenCount, olderAvailable);
  const windowValue = useMemo(() => ({ expandWindow: () => onExpandWindow?.(), olderAvailable }), [olderAvailable, onExpandWindow]);

  // Stick to bottom: follows Hermes — only auto-scroll if user was at bottom (80px)
  // Uses rAF to coalesce thrash from streaming tokens.
  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= 80;
  }, []);

  useLayoutEffect(() => {
    const el = scrollerRef.current;
    if (!el || !atBottomRef.current) return;
    const raf = requestAnimationFrame(() => {
      if (atBottomRef.current && el) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(raf);
  }, [messages, budget]);

  // Timeline rail entries are derived from the SAME message list; the array is
  // reused while it describes the same rail, so an unchanged transcript costs
  // zero re-renders.
  const derived = deriveTimelineEntries(messages.map(message => ({ id: message.id, role: message.role, text: messageContentText(message.content) })));
  const entries = sameTimelineEntries(entriesRef.current, derived) ? entriesRef.current : derived;

  if (entries !== entriesRef.current) {
    entriesRef.current = entries;
  }

  const measureOffsets = useCallback(() => {
    const root = scrollerRef.current;
    if (!root) return;
    requestAnimationFrame(() => {
      if (!scrollerRef.current) return;
      const top = scrollerRef.current.getBoundingClientRect().top;
      offsetsRef.current = entries.map(entry => {
        const node = scrollerRef.current!.querySelector<HTMLElement>(`[data-turn-id="${attrEscape(entry.id)}"]`);
        return node ? node.getBoundingClientRect().top - top + scrollerRef.current!.scrollTop : null;
      });
      setActiveEntry(activeTimelineIndex(offsetsRef.current));
    });
  }, [entries]);

  useEffect(() => {
    measureOffsets();
    const root = scrollerRef.current;
    if (!root) return;
    const ro = new ResizeObserver(() => measureOffsets());
    ro.observe(root);
    return () => ro.disconnect();
  }, [measureOffsets]);

  const jumpTo = useCallback(
    (id: string) => {
      const root = scrollerRef.current;
      const node = root?.querySelector<HTMLElement>(`[data-turn-id="${attrEscape(id)}"]`);

      if (root && node) {
        atBottomRef.current = false;
        root.scrollTo({ behavior: 'smooth', top: node.offsetTop - 8 });
      }
    },
    []
  );

  const pendingApproval = transcript.approvals[0];
  const body: ReactNode =
    messages.length === 0 ? (
      <>{emptyState ?? <EmptyState title="Crusor is ready. Ask it to change something.">Nothing has been said in this session yet.</EmptyState>}</>
    ) : (
      <div className="crusor-thread__list">
        {showEarlier !== 'null' && (
          <button
            className="crusor-thread__show-earlier"
            onClick={() => {
              if (showEarlier === 'dom') {
                setBudget(value => value + BACKFILL_STEP);
              } else {
                windowValue.expandWindow();
              }
            }}
            type="button"
          >
            Show earlier
          </button>
        )}
        {groups.map((group, index) => {
          if (index < firstVisible) {
            return null;
          }

          const indices = group.kind === 'turn' ? group.indices : [group.index];
          const isLiveTail = index >= tailStart;

          return (
            <div
              className={cn('crusor-thread__group', isLiveTail ? 'crusor-thread__group--live' : 'crusor-thread__group--virtualized')}
              data-group-id={group.id}
              data-turn-id={group.id}
              key={`${group.id}:${String(indices[0])}`}
            >
              {indices.map(messageIndex => {
                const message = messages[messageIndex] as CrusorMessage;

                if (message.role === 'user') {
                  return <CrusorUserMessage key={message.id} message={message} />;
                }

                if (message.role === 'system') {
                  return <CrusorSystemMessage key={message.id} message={message} />;
                }

                return (
                  <CrusorAssistantMessage
                    approval={pendingApproval}
                    isLatest={messageIndex === messages.length - 1}
                    key={message.id}
                    message={message}
                    respond={approvalRespond ? choice => approvalRespond(choice, pendingApproval as CrusorApproval) : undefined}
                    reviewAction={reviewAction}
                    run={transcript.run}
                    signals={signals}
                  />
                );
              })}
            </div>
          );
        })}
        {messages[messages.length - 1]?.role !== 'assistant' && signals.busy && <TurnPending signals={{ ...signals, turnStartedAt: transcript.run.turnStartedAt }} step={transcript.run.step} />}
      </div>
    );

  return (
    <TranscriptWindowProvider value={windowValue}>
      <div className={cn('crusor-thread', className)} data-slot="crusor-agent-thread">
        {entries.length > 1 && (
          <nav aria-label="Conversation timeline" className="crusor-timeline">
            {entries.map((entry, index) => (
              <button
                aria-current={index === activeEntry ? 'true' : undefined}
                className="crusor-timeline__dot"
                key={entry.id}
                onClick={() => jumpTo(entry.id)}
                title={entry.preview}
                type="button"
              >
                <span className="crusor-timeline__label">{entry.preview}</span>
              </button>
            ))}
          </nav>
        )}
        <div className="crusor-thread__scroller" onScroll={onScroll} ref={scrollerRef} tabIndex={0}>
          {body}
        </div>
        {composer}
      </div>
    </TranscriptWindowProvider>
  );
}

/** Never page back below this many whole turns, however heavy they are. */
const MIN_VISIBLE_GROUPS_FLOOR = 8;

export { useTranscriptWindow };
