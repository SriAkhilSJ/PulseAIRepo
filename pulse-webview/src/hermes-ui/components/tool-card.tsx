// Ported from hermes-agent `tool/fallback.tsx` :: `ToolEntry` (+ `ToolGlyph`,
// `ToolTitle`, `TerminalTranscript`, `SearchResultsList`, `ToolPayloadDisclosure`,
// `leadingStatus`, the section-class constants) @ a9c783f2.
//
// One row of transcript scaffolding for a single tool call: a header line that
// says what happened, an expandable body that carries the payload, and the two
// rules that make the row honest — a completed file edit with no diff is hidden
// rather than shown as a dead duplicate, and everything painted is clamped while
// Copy keeps the full output.
//
// Deviations, all deliberate and documented in PROVENANCE.md:
//   - No assistant-ui store: `part` + `messageRunning` come from props, so the
//     row is renderable with zero runtime (that is what the jsdom test does).
//   - No side-diff channel (`$toolInlineDiff`), no per-tool diff stream: the diff
//     comes from the tool result only.
//   - No codicon/Shiki: the leading cell carries the status glyph, the diff uses
//     the color-only renderer.
//   - `recordPreviewArtifact` (composer status stack) is not ported: this tier has
//     no composer store, so a previewable target renders as a link instead.

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

import type { PulseApproval } from '../pulse/types';
import { clampForDisplay, prettyJson } from '../model/format';
import {
  buildToolView,
  countDiffLineStats,
  inlineDiffFromResult,
  isFileEditTool,
  looksRedundant,
  stripInlineDiffChrome,
  toolCopyPayload,
  toolPartDisclosureId,
} from '../model/fallback-model';
import type { ToolPart, ToolStatus } from '../model/types';
import { isPreviewableTarget } from '../model/targets';
import { useElapsedSeconds } from '../model/activity-timer';
import { useToolDisclosureOpen, useToolRowDismissed, useToolViewMode, setToolDisclosureOpen, dismissToolRow } from '../model/tool-view';
import { cn } from '../lib/cn';
import { DisclosureRow } from './disclosure-row';
import { DiffCount, FileDiffPanel } from './diff-lines';
import { SCAFFOLD_LABEL_CLASS, SCAFFOLD_META_CLASS } from './scaffold-row';
import { ApprovalRow, approvalBlocksTool } from './approval-row';
import { StableText } from './stable-text';

const TOOL_SECTION_LABEL_CLASS = 'pulse-tool-section-label';
// Inset scroll surface for any detail body. The expanded tool row owns the
// border; the payload itself is just clipped raw text.
const TOOL_SECTION_SURFACE_CLASS = 'pulse-tool-section-surface';
const TOOL_SECTION_PRE_CLASS = cn(TOOL_SECTION_SURFACE_CLASS, 'pulse-tool-section-pre');
// Raw args/result dump — reference material, so a notch smaller than a body.
const TOOL_PAYLOAD_PRE_CLASS = cn(TOOL_SECTION_SURFACE_CLASS, 'pulse-tool-section-pre', 'pulse-tool-section-payload');
const TOOL_EXPANDED_SHELL_CLASS = 'pulse-tool-block--open';

/** Whether this row is rendered inside a run (grouped) rather than as its own
 *  card. Inside a group each row still owns its own chrome (timer / copy /
 *  approval), so the value is `false` there too — the context exists so an
 *  EMBEDDED surface (a delegate card relaying a child's rows) can opt its rows
 *  out of the shell. */
export const ToolEmbedContext = createContext(false);

export type ApprovalResponder = (choice: 'always' | 'once' | 'session' | 'deny') => void;
export const ApprovalContext = createContext<{ approval?: PulseApproval; respond?: ApprovalResponder }>({});

function leadingStatus(isPending: boolean, status: ToolStatus): ToolStatus | undefined {
  if (isPending) {
    return 'running';
  }

  return status === 'success' ? undefined : status;
}

function statusGlyph(status: ToolStatus | undefined): ReactNode {
  if (status === 'running') {
    return (
      <span aria-label="running" className="pulse-tool-glyph pulse-tool-glyph--running" role="img">
        ◌
      </span>
    );
  }

  if (status === 'error') {
    return (
      <span aria-label="failed" className="pulse-tool-glyph pulse-tool-glyph--error" role="img">
        !
      </span>
    );
  }

  if (status === 'warning') {
    return (
      <span aria-label="warning" className="pulse-tool-glyph pulse-tool-glyph--warning" role="img">
        ▲
      </span>
    );
  }

  return null;
}

function ToolGlyph({ legendary, status }: { legendary?: boolean; status?: ToolStatus }) {
  const node = statusGlyph(status);

  return node ? <span className={cn('pulse-tool-glyph-wrap', legendary && 'pulse-tool-glyph-wrap--legendary')}>{node}</span> : null;
}

function ToolTitle({
  isPending,
  legendary,
  status,
  title,
  titleAction,
}: {
  isPending: boolean;
  legendary?: boolean;
  status: ToolStatus;
  title: string;
  titleAction?: { prefix?: string; suffix?: string; text: string };
}) {
  return (
    <span
      className={cn(
        SCAFFOLD_LABEL_CLASS,
        'pulse-fade-text',
        isPending && 'pulse-tool-title--pending',
        status === 'error' && 'pulse-tool-title--error',
        status === 'warning' && 'pulse-tool-title--warning',
        legendary && !isPending && 'pulse-tool-title--legendary'
      )}
    >
      {isPending && titleAction ? (
        <>
          {titleAction.prefix}
          <span className="pulse-shimmer">{titleAction.text}</span>
          {titleAction.suffix}
        </>
      ) : (
        title
      )}
    </span>
  );
}

interface TerminalTranscriptProps {
  command?: string;
  exitCode?: number;
}

function TerminalTranscript({ command, exitCode }: TerminalTranscriptProps) {
  if (!command && exitCode === undefined) {
    return null;
  }

  return (
    <div className="pulse-terminal-transcript">
      {command && (
        <code className="pulse-terminal-transcript__command">
          <span aria-hidden className="pulse-terminal-transcript__prompt">
            ${' '}
          </span>
          {command}
        </code>
      )}
      {exitCode !== undefined && (
        <span className={cn('pulse-terminal-transcript__exit', exitCode === 0 ? 'pulse-terminal-transcript__exit--ok' : 'pulse-terminal-transcript__exit--fail')}>
          <StableText>{`exit ${String(exitCode)}`}</StableText>
        </span>
      )}
    </div>
  );
}

function SearchResultsList({ hits }: { hits: Array<{ snippet?: string; title: string; url?: string }> }) {
  return (
    <ol className="pulse-search-hits">
      {hits.map((hit, index) => {
        const key = `${hit.url || hit.title}-${index}`;
        const body = (
          <>
            <span className="pulse-search-hits__title">{hit.title}</span>
            {hit.snippet && <span className="pulse-search-hits__snippet">{hit.snippet}</span>}
            {hit.url && <span className="pulse-search-hits__url">{hit.url}</span>}
          </>
        );

        return (
          <li key={key}>
            {hit.url ? (
              <a href={hit.url} rel="noreferrer noopener" target="_blank">
                {body}
              </a>
            ) : (
              body
            )}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Technical-mode raw payload, behind a chevron disclosure. Collapsed by default
 * — in technical mode every tool row carries one, and expanding them all buries
 * the transcript.
 */
function ToolPayloadDisclosure({ args, result }: { args: unknown; result: unknown }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="pulse-tool-payload">
      <button aria-expanded={open} className="pulse-tool-payload__toggle" onClick={() => setOpen(value => !value)} type="button">
        raw payload <span className={cn('pulse-tool-payload__caret', open && 'pulse-tool-payload__caret--open')}>▾</span>
      </button>
      {open && (
        <>
          <p className={TOOL_SECTION_LABEL_CLASS}>args</p>
          <pre className={TOOL_PAYLOAD_PRE_CLASS}>{clampForDisplay(prettyJson(args))}</pre>
          <p className={TOOL_SECTION_LABEL_CLASS}>result</p>
          <pre className={TOOL_PAYLOAD_PRE_CLASS}>{clampForDisplay(prettyJson(result))}</pre>
        </>
      )}
    </div>
  );
}

export interface PulseToolRowProps {
  part: ToolPart;
  /** Id of the message this row was rendered in — the disclosure id is scoped to
   *  it so the same call replayed in another turn keeps its own open/closed. */
  messageId: string;
  messageRunning?: boolean;
  /** Live stream stamps, when the transport carries them. */
  completedAt?: number;
  timestamp?: number;
}

export function PulseToolRow({ completedAt, messageRunning = false, messageId, part, timestamp }: PulseToolRowProps) {
  const statusCopy = { dismiss: 'Dismiss' };
  const embedded = useContext(ToolEmbedContext);
  const { approval, respond } = useContext(ApprovalContext);
  const toolViewMode = useToolViewMode();

  // `ToolFallback` rebuilds the `part` wrapper each render, defeating the memos
  // below and re-running buildToolView (full JSON.stringify of result) on every
  // stream delta — the freeze on big `/learn` runs. Re-derive a stable part from
  // the referentially-stable args/result so the memos hold across deltas.
  const { args, isError, result, toolCallId, toolName } = part;

  const stablePart = useMemo<ToolPart>(
    () => ({ args, completedAt, isError, result, timestamp, toolCallId, toolName, type: 'tool-call' }),
    [args, completedAt, isError, result, timestamp, toolCallId, toolName]
  );

  const disclosureId = `tool-entry:${messageId}:${toolPartDisclosureId(stablePart)}`;
  const dismissed = useToolRowDismissed(disclosureId);
  const isPending = messageRunning && result === undefined;
  const inlineDiff = stripInlineDiffChrome(inlineDiffFromResult(result)) || undefined;
  const isFileEdit = isFileEditTool(toolName);
  const defaultOpen = Boolean(inlineDiff);
  const open = useToolDisclosureOpen(disclosureId, defaultOpen);
  const canDismiss = !isPending && !embedded;
  const elapsed = useElapsedSeconds(isPending, `tool:${disclosureId}`);

  // Stale parts (no result, but message stopped running) get a synthetic empty
  // result so buildToolView treats them as completed-no-output. Keyed on
  // stablePart so it recomputes only when this tool's data changes.
  const view = useMemo(() => {
    const p = !isPending && result === undefined ? { ...stablePart, result: {} } : stablePart;

    return buildToolView(p, inlineDiff);
  }, [inlineDiff, isPending, result, stablePart]);

  const detailSections = useMemo(() => {
    if (!view.detail) {
      return { body: '', summary: '' };
    }

    if (view.status !== 'error') {
      return { body: view.detail, summary: '' };
    }

    const chunks = view.detail
      .split(/\n\s*\n+/)
      .map(chunk => chunk.trim())
      .filter(Boolean);

    const [summary = '', ...rest] = chunks;
    const subtitleNorm = (view.subtitle || '').trim().toLowerCase();
    const summaryDuplicatesSubtitle = summary && summary.toLowerCase() === subtitleNorm;

    if (summaryDuplicatesSubtitle) {
      return { body: rest.join('\n\n').trim(), summary: '' };
    }

    return { body: rest.join('\n\n').trim(), summary };
  }, [view.detail, view.status, view.subtitle]);

  // `looksRedundant` normalizes the FULL (uncapped) detail payload — a read_file
  // / run_terminal result can be huge. Memoize on the view fields so it
  // recomputes only when this tool's content changes, not on every parent
  // re-render (tool rows re-render on every stream tick of the running message).
  const detailMatchesSubtitle = useMemo(() => looksRedundant(view.subtitle, view.detail), [view.subtitle, view.detail]);
  const detailMatchesTitle = useMemo(() => looksRedundant(view.title, view.detail), [view.title, view.detail]);

  const showDetail =
    !view.inlineDiff &&
    (Boolean(view.stdout || view.stderr) ||
      (view.status === 'error' && Boolean(detailSections.summary || detailSections.body)) ||
      (view.status !== 'error' && Boolean(view.detail) && !detailMatchesTitle && !detailMatchesSubtitle));

  const renderDetailAsCode =
    view.status !== 'error' && (part.toolName === 'run_terminal' || part.toolName === 'execute_code' || part.toolName === 'read_file');

  const hasSearchHits = Boolean(view.searchHits?.length);
  const searchResultsLabel = part.toolName === 'web_search' ? 'Search results' : view.detailLabel;

  const hasExpandableContent = Boolean(
    view.imageUrl ||
      view.inlineDiff ||
      showDetail ||
      hasSearchHits ||
      view.stdout ||
      view.stderr ||
      view.terminalCommand ||
      view.terminalExitCode !== undefined ||
      toolViewMode === 'technical'
  );

  // copyAction reads the uncapped view.detail; clampForDisplay below only bounds
  // what's painted, so the row's Copy button still yields the full output.
  const copyAction = useMemo(() => toolCopyPayload(stablePart, view), [stablePart, view]);

  const diffStats = useMemo(() => (isFileEdit && view.inlineDiff ? countDiffLineStats(view.inlineDiff) : null), [isFileEdit, view.inlineDiff]);

  const showDiffStats = !isPending && Boolean(diffStats && (diffStats.added > 0 || diffStats.removed > 0));

  // The header trailing slot only carries the live duration timer while the tool
  // is running. The copy control used to live here too, but an invisible-yet
  // clickable button straddling the caret/duration made the disclosure caret hard
  // to hit; Copy now lives in the expanded body's top-right, where it can't
  // fight the caret for the right edge.
  const trailing = !embedded ? (
    <span className="pulse-tool-trailing">
      {isPending && (
        <span className={SCAFFOLD_META_CLASS}>
          <StableText>{`${elapsed}s`}</StableText>
        </span>
      )}
    </span>
  ) : undefined;

  // Once a turn has settled, a hover/focus-revealed dismiss lets the user clear
  // a completed/failed row that would otherwise sit at the tail of the chat. It
  // goes in the in-flow `action` slot (not `trailing`) so it can't overlap the
  // disclosure caret's hit-target.
  const dismissAction = canDismiss ? (
    <button
      aria-label={statusCopy.dismiss}
      className="pulse-tool-dismiss"
      onClick={event => {
        event.stopPropagation();
        dismissToolRow(disclosureId);
      }}
      title={statusCopy.dismiss}
      type="button"
    >
      ×
    </button>
  ) : undefined;

  const blockedOnApproval = approvalBlocksTool(approval, part.toolName, part.toolCallId) && result === undefined;

  if (dismissed && !blockedOnApproval) {
    return null;
  }

  // A completed file edit with no diff to review is a bare, unexpandable row.
  // This is almost always a `write_file` create after a reload: only a patch
  // persists its diff in the tool result, so creates rehydrate diff-less and read
  // like dead duplicates of the real diff row. Hide them — but keep in-flight
  // writes (activity) and failures (errors) visible.
  if (isFileEdit && !isPending && view.status !== 'error' && !view.inlineDiff) {
    return null;
  }

  // A run in product mode hides the raw terminal echo; technical mode shows the
  // payload dump instead. Same rule as upstream's terminal special-case.
  const showTerminalTranscript = part.toolName === 'run_terminal' && toolViewMode !== 'technical';
  const previewTarget = view.previewTarget && isPreviewableTarget(view.previewTarget) ? view.previewTarget : undefined;

  return (
    <div
      className={cn('pulse-tool-block', open && TOOL_EXPANDED_SHELL_CLASS)}
      data-conversation-scaffold=""
      data-file-edit={isFileEdit && open ? '' : undefined}
      data-slot="tool-block"
      data-tool-open={open ? '' : undefined}
      data-tool-row=""
    >
      <div className={cn(open && 'pulse-tool-block__head--open')}>
        <DisclosureRow
          action={dismissAction}
          onToggle={hasExpandableContent ? () => setToolDisclosureOpen(disclosureId, !open) : undefined}
          open={open}
          trailing={trailing}
        >
          <span className="pulse-tool-head" title={isFileEdit && view.subtitle ? view.subtitle : undefined}>
            <ToolGlyph status={leadingStatus(isPending, view.status)} />
            <ToolTitle isPending={isPending} status={view.status} title={view.title} titleAction={view.titleAction ? { ...view.titleAction } : undefined} />
            {!isPending && view.countLabel && <span className={SCAFFOLD_META_CLASS}>{view.countLabel}</span>}
            {showDiffStats && diffStats && <DiffCount added={diffStats.added} removed={diffStats.removed} />}
            {!isFileEdit && !isPending && view.durationLabel && <span className={SCAFFOLD_META_CLASS}>{view.durationLabel}</span>}
          </span>
        </DisclosureRow>
      </div>
      {blockedOnApproval && approval && respond && <ApprovalRow approval={approval} onRespond={respond} />}
      {open && (
        <div className="pulse-tool-body">
          {copyAction.text && (
            <CopyButton className="pulse-tool-copy" label={copyAction.label || 'Copy output'} text={copyAction.text} />
          )}
          {previewTarget && (
            <a className="pulse-tool-preview-link" href={previewTarget} rel="noreferrer noopener" target="_blank">
              Open preview
            </a>
          )}
          {showTerminalTranscript && <TerminalTranscript command={view.terminalCommand} exitCode={view.terminalExitCode} />}
          {view.imageUrl && (
            <div className="pulse-tool-image">
              <img alt="tool output" className="pulse-tool-image__img" src={view.imageUrl} />
            </div>
          )}
          {hasSearchHits && view.searchHits && (
            <div className="pulse-tool-section">
              {view.searchQuery && (
                <p className="pulse-tool-search-query">
                  <span className="pulse-tool-search-query__label">Search</span>
                  <span>{view.searchQuery}</span>
                </p>
              )}
              {searchResultsLabel && <p className={TOOL_SECTION_LABEL_CLASS}>{searchResultsLabel}</p>}
              <SearchResultsList hits={view.searchHits} />
            </div>
          )}
          {view.inlineDiff && <FileDiffPanel className="pulse-tool-diff" diff={view.inlineDiff} path={isFileEdit ? view.subtitle : undefined} />}
          {showDetail && toolViewMode !== 'technical' && (
            <div className="pulse-tool-section">
              {view.status === 'error' ? (
                detailSections.summary || detailSections.body ? (
                  <div className="pulse-tool-error">
                    {detailSections.summary && <p className="pulse-tool-error__summary">{detailSections.summary}</p>}
                    {detailSections.body && <pre className={cn(TOOL_SECTION_PRE_CLASS, 'pulse-tool-error__body')}>{clampForDisplay(detailSections.body)}</pre>}
                  </div>
                ) : null
              ) : view.stdout || view.stderr ? (
                // Stdout + stderr split: render both as labeled blocks. stderr is
                // intentionally NOT painted as an error — many CLIs log
                // informational output there.
                <>
                  {view.detailLabel && <p className={TOOL_SECTION_LABEL_CLASS}>{view.detailLabel}</p>}
                  {view.stdout && (
                    <div className="pulse-tool-stream">
                      {view.stderr && <p className={TOOL_SECTION_LABEL_CLASS}>stdout</p>}
                      <pre className={cn(TOOL_SECTION_PRE_CLASS, 'pulse-tool-stream__out')}>{clampForDisplay(view.stdout)}</pre>
                    </div>
                  )}
                  {view.stderr && (
                    <div className={cn('pulse-tool-stream', view.stdout && 'pulse-tool-stream--second')}>
                      <p className={TOOL_SECTION_LABEL_CLASS}>stderr</p>
                      <pre className={cn(TOOL_SECTION_PRE_CLASS, 'pulse-tool-stream__err')}>{clampForDisplay(view.stderr)}</pre>
                    </div>
                  )}
                </>
              ) : (
                <>
                  {view.detailLabel && <p className={TOOL_SECTION_LABEL_CLASS}>{view.detailLabel}</p>}
                  <pre className={cn(TOOL_SECTION_PRE_CLASS, renderDetailAsCode ? 'pulse-tool-detail--code' : 'pulse-tool-detail--prose')}>
                    {clampForDisplay(view.detail)}
                  </pre>
                </>
              )}
            </div>
          )}
          {toolViewMode === 'technical' && <ToolPayloadDisclosure args={part.args} result={part.result} />}
        </div>
      )}
    </div>
  );
}

export function CopyButton({ className, label, text }: { className?: string; label: string; text: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      className={cn('pulse-tool-copy', className)}
      onClick={() => {
        navigator.clipboard?.writeText(text).catch(() => undefined);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      }}
      title={label}
      type="button"
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}
