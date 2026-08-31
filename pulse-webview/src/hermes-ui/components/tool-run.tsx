// Ported from hermes-agent `tool/fallback.tsx` :: `ToolRun`, `ToolGroupSlot`,
// `ToolRunHeader`, `useToolRun`, `splitRunItems` @ a9c783f2.
//
// The grouping rule, verbatim: a run of consecutive ACTIVITY calls collapses to
// one grey summary line ("Explored 3 files, ran 5 commands"); calls that draw
// their own surface (a diff, a question) stay cards, in place, in order. The run
// is identified by its FIRST tool call, never by its position — a live stream and
// the same turn rehydrated from history agree on which calls belong together but
// not on the indices they land at, because rehydration folds a turn into one
// bubble the live view spreads over several.

import { Fragment, type ReactNode, useMemo, useRef } from 'react';

import type { PulseApproval } from '../pulse/types';
import { summarizeToolRun } from '../model/run-summary';
import { toolPartDisclosureId } from '../model/targets';
import { isCardTool } from '../model/fallback-model';
import { APPROVAL_TOOLS } from './approval-row';
import type { ToolPart } from '../model/types';
import { useAnyToolDisclosureOpen, setToolDisclosureOpen, useToolDisclosureOpen } from '../model/tool-view';
import { cn } from '../lib/cn';
import { ScaffoldRow, SCAFFOLD_LABEL_CLASS } from './scaffold-row';
import { ApprovalContext, PulseToolRow } from './tool-card';
import { ToolRunTicker } from './run-ticker';
import type { PulseMessage, PulseMessagePart } from '../pulse/types';

export interface RunItemRun {
  end: number;
  kind: 'run';
  start: number;
}

export interface RunItemCard {
  index: number;
  kind: 'card';
}

export type RunItem = RunItemCard | RunItemRun;

/**
 * Split a range of parts into cards and the runs of activity between them.
 *
 * Order is preserved rather than sorted into "all the runs, then all the cards":
 * a turn that reads, edits, then reads again shows a summary, the diff, then a
 * second summary, in the sequence it happened. Indices are relative to the range.
 * An empty name is a part that isn't a tool call at all, which passes through as
 * its own card.
 */
export function splitRunItems(toolNames: readonly string[]): RunItem[] {
  const items: RunItem[] = [];
  let run: null | RunItemRun = null;

  toolNames.forEach((name, index) => {
    if (!name || isCardTool(name)) {
      run = null;
      items.push({ index, kind: 'card' });

      return;
    }

    if (run) {
      run.end = index;
    } else {
      run = { end: index, kind: 'run', start: index };
      items.push(run);
    }
  });

  return items;
}

function isToolPart(part: PulseMessage['content'][number]): part is ToolPart {
  return part.type === 'tool-call';
}

export interface ToolRunState {
  completedAt?: number;
  count: number;
  /** Disclosure id of each row in the run, so the run can tell when one is open. */
  entryIds: readonly string[];
  key: string;
  live: boolean;
  startedAt?: number;
  /** A call still awaiting a result that could be the one blocking on approval. */
  pendingApprovalTool: boolean;
  summary: string;
}

export function computeToolRun(parts: readonly PulseMessagePart[], messageRunning: boolean, messageId: string): ToolRunState {
  const tools: ToolPart[] = parts.filter(isToolPart);
  // Live means the turn is still working and nothing has come after this run —
  // not that some call is unresolved. Those differ in the gap between one call
  // finishing and the next arriving, which for sequential calls is most of the
  // run: falling back to past tense there unmounts the ticker and drops its reel
  // to the top instead of scrolling. The tail bound is what keeps this honest.
  const live = messageRunning && tools.length > 0;
  const timelineTools = tools;

  return {
    completedAt: timelineTools.reduce<number | undefined>(
      (latest, tool) => (tool.completedAt === undefined ? latest : latest === undefined ? tool.completedAt : Math.max(latest, tool.completedAt)),
      undefined
    ),
    count: tools.length,
    entryIds: tools.map(tool => `tool-entry:${messageId}:${toolPartDisclosureId(tool)}`),
    key: tools[0]?.toolCallId ?? '',
    live,
    startedAt: timelineTools.reduce<number | undefined>(
      (earliest, tool) => (tool.timestamp === undefined ? earliest : earliest === undefined ? tool.timestamp : Math.min(earliest, tool.timestamp)),
      undefined
    ),
    pendingApprovalTool: tools.some(tool => tool.result === undefined && APPROVAL_TOOLS.has(tool.toolName)),
    summary: summarizeToolRun(tools, live),
  };
}

/**
 * assistant-ui compares selector results with `Object.is` and calls the selector
 * on every store update, so returning a fresh object re-renders the group on
 * every text delta in the turn. The run only changes when a call arrives or one
 * finishes; cache on exactly that. Here the same discipline is a signature memo
 * over the parts array the parent already keeps referentially stable.
 */
export function useToolRun(parts: readonly PulseMessagePart[], messageRunning: boolean, messageId: string): ToolRunState {
  const cache = useRef<null | { signature: string; value: ToolRunState }>(null);
  const tools: ToolPart[] = parts.filter(isToolPart);
  const signature = tools
    .map(tool => `${tool.toolCallId}:${tool.result === undefined ? 0 : 1}:${tool.timestamp ?? ''}:${tool.completedAt ?? ''}`)
    .concat(String(messageRunning && parts.length === tools.length))
    .join('|');

  if (cache.current?.signature !== signature) {
    cache.current = { signature, value: computeToolRun(parts, messageRunning, messageId) };
  }

  return cache.current.value;
}

/**
 * The one grey line that stands in for a run of tool calls — "Explored 3 files,
 * ran 5 commands". Live, it narrates in the present tense above the ticker and
 * offers no toggle, since there is nothing settled to unfold yet.
 */
function ToolRunHeader({ live, onToggle, open, summary }: { live: boolean; onToggle?: () => void; open: boolean; summary: string }) {
  return (
    <div data-conversation-scaffold="" data-tool-summary="">
      <ScaffoldRow onToggle={onToggle} open={open}>
        <span className={cn(SCAFFOLD_LABEL_CLASS, 'pulse-tool-run-summary', live && 'pulse-shimmer')}>{summary}</span>
      </ScaffoldRow>
    </div>
  );
}

export interface ToolRunProps {
  approval?: PulseApproval;
  children: ReactNode;
  message: PulseMessage;
  messageRunning: boolean;
  parts: readonly PulseMessagePart[];
}

/**
 * One run of consecutive activity calls, headed by the line that summarizes it.
 *
 * Live, the run is a summary plus the one-line ticker. Settled, the summary is
 * the whole of it until the user opens it.
 */
export function ToolRun({ approval, children, message, messageRunning, parts }: ToolRunProps) {
  const run = useToolRun(parts, messageRunning, message.id);
  const disclosureId = `tool-run:${run.key}`;
  const persistedOpen = useToolDisclosureOpen(disclosureId, false);
  const rowOpen = useAnyToolDisclosureOpen(run.entryIds);

  // A lone call is already its own one-line summary; heading it with a second
  // line would say the same thing twice.
  if (run.count < 2) {
    return <>{children}</>;
  }

  // Two things a one-line window can't hold. An approval is a question the user
  // has to answer, and expanded output is one they went looking for — both would
  // tick straight past, or be sliced to a single line, as the run keeps going.
  // Either one hands the run back its full height until the run settles and the
  // row can be reached through the summary instead.
  const blocked = Boolean(approval) && run.pendingApprovalTool;
  const unfurled = blocked || rowOpen;
  const expanded = run.live ? unfurled : persistedOpen;

  return (
    <div className="pulse-tool-run" data-slot="tool-block" data-tool-group="">
      <ToolRunHeader
        live={run.live}
        onToggle={run.live ? undefined : () => setToolDisclosureOpen(disclosureId, !expanded)}
        open={expanded}
        summary={run.summary}
      />
      {run.live && ! unfurled && <ToolRunTicker>{children}</ToolRunTicker>}
      {expanded && <div className="pulse-tool-run__rows">{children}</div>}
    </div>
  );
}

export type ApprovalChoice = 'always' | 'once' | 'session' | 'deny';

export interface PulseToolGroupProps {
  approval?: PulseApproval;
  message: PulseMessage;
  messageRunning: boolean;
  respond?: (choice: ApprovalChoice) => void;
}

/**
 * Render an assistant message's tool-call parts: cards in place, activity in
 * runs. This is `ToolGroupSlot` with the assistant-ui indirection removed — the
 * range is the whole message rather than a slice of a part index, and the row
 * index is kept in step with `message.content` so a text part still occupies its
 * slot (upstream relies on the same alignment: an empty tool name is a part that
 * isn't a call at all and passes through as its own card).
 */
export function PulseToolGroup({ approval, message, messageRunning, respond }: PulseToolGroupProps) {
  const toolNames = useMemo(() => message.content.map(part => (part.type === 'tool-call' ? part.toolName : '')), [message.content]);
  const items = useMemo(() => splitRunItems(toolNames), [toolNames]);
  const rows: ReactNode[] = useMemo(
    () =>
      message.content.map((part, index) =>
        part.type === 'tool-call' ? (
          <PulseToolRow key={`row-${String(index)}`} messageRunning={messageRunning} messageId={message.id} part={part} />
        ) : null
      ),
    [message.content, message.id, messageRunning]
  );

  return (
    <ApprovalContext.Provider value={{ approval, respond }}>
      <div className="pulse-tool-group">{items.map(renderItem(rows, items, { approval, message, messageRunning }))}</div>
    </ApprovalContext.Provider>
  );
}

function renderItem(
  rows: ReactNode[],
  _items: readonly RunItem[],
  ctx: { approval?: PulseApproval; message: PulseMessage; messageRunning: boolean }
) {
  // Joined rather than returned as an array: a fresh array per render re-renders
  // the whole group on every text delta in the turn.
  return (item: RunItem) =>
    item.kind === 'card' ? (
      <Fragment key={`card:${item.index}`}>{rows[item.index]}</Fragment>
    ) : (
      <ToolRun
        approval={ctx.approval}
        key={`run:${item.start}`}
        message={ctx.message}
        messageRunning={ctx.messageRunning}
        parts={ctx.message.content.slice(item.start, item.end + 1)}
      >
        {rows.slice(item.start, item.end + 1)}
      </ToolRun>
    );
}
