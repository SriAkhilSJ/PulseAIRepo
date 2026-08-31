// Ported from hermes-agent `components/chat/diff-lines.tsx` @ a9c783f2 — the
// parse plus the COLOR-ONLY renderer. Upstream has two renderers over one
// parse: `SyntaxDiff` (Shiki-highlighted change content) and `DiffLines` (the
// fallback used when there is no language, the payload is over the highlight
// budget, or Shiki is still loading). This tier ships no Shiki dependency, so
// every diff takes the fallback path; the parse, the header-stripping rule and
// the tint classes are unchanged, which is what the tests lock down.

import { useMemo, type ReactNode } from 'react';

import { cn } from '../lib/cn';

export type DiffKind = 'add' | 'context' | 'remove';

export interface DiffLine {
  kind: DiffKind;
  newNo?: number;
  oldNo?: number;
  text: string;
}

interface ParsedHunk {
  lines: Array<{ kind: DiffKind; text: string }>;
  newStart: number;
  oldStart: number;
}

/** Tint + 2px gutter accent per change kind. Text color is included because the
 *  plain renderer is the only renderer here (upstream omits it on the Shiki
 *  path so syntax colors win, layering only background + border). */
export const DIFF_KIND_TINT: Record<DiffKind, string> = {
  add: 'pulse-diff-line--add',
  context: 'pulse-diff-line--context',
  remove: 'pulse-diff-line--remove',
};

const DIFF_HEADER_PREFIXES = ['diff --git', 'index ', '--- ', '+++ ', 'similarity ', 'rename ', 'new file', 'deleted file'];

export function diffKind(line: string): DiffKind {
  if (line.startsWith('+') && !line.startsWith('+++')) {
    return 'add';
  }

  if (line.startsWith('-') && !line.startsWith('---')) {
    return 'remove';
  }

  return 'context';
}

/** Drop the leading +/-/space gutter so changes read by color alone, keeping the
 *  rest of the indentation intact. */
export function stripDiffMarker(line: string): string {
  if (diffKind(line) !== 'context' || line.startsWith(' ')) {
    return line.slice(1);
  }

  return line;
}

function isArrowHeaderLine(line: string): boolean {
  const trimmed = line.trim();

  return trimmed.includes('→') && /^\S.*→\s*\S+$/.test(trimmed) && !/^[+\-@]/.test(trimmed);
}

/** Exported for tests. */
export function stripDiffFileHeaders(diff: string): string {
  const lines = diff.split('\n');
  let start = 0;

  for (; start < lines.length; start += 1) {
    const line = lines[start] as string;

    if (line.startsWith('@@')) {
      break;
    }

    if (line.trim() === '' || isArrowHeaderLine(line) || DIFF_HEADER_PREFIXES.some(prefix => line.startsWith(prefix))) {
      continue;
    }

    break;
  }

  return lines.slice(start).join('\n');
}

function parseHunks(diff: string): ParsedHunk[] {
  const hunks: ParsedHunk[] = [];
  let active: null | ParsedHunk = null;

  for (const line of stripDiffFileHeaders(diff).split('\n')) {
    if (line.startsWith('@@')) {
      const match = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);

      if (!match) {
        active = null;

        continue;
      }

      active = { lines: [], newStart: Number(match[2]), oldStart: Number(match[1]) };
      hunks.push(active);

      continue;
    }

    if (!active || line.startsWith('\\')) {
      continue;
    }

    active.lines.push({ kind: diffKind(line), text: stripDiffMarker(line) });
  }

  return hunks;
}

/**
 * Cleaned diff → renderable lines: file-headers + `@@` hunks dropped (a blank
 * separator kept between hunks), markers stripped, kind recorded. Old/new line
 * numbers are tracked from each `@@ -a,b +c,d @@` header so a caller that wants
 * a gutter can render them; the blank separator carries none.
 */
export function parseDiff(diff: string): DiffLine[] {
  const hunks = parseHunks(diff);

  if (hunks.length === 0) {
    // Fallback for unexpected non-hunk payloads.
    return stripDiffFileHeaders(diff)
      .split('\n')
      .map(line => ({ kind: diffKind(line), text: stripDiffMarker(line) }));
  }

  const out: DiffLine[] = [];
  let emitted = false;
  let oldNo = 1;
  let newNo = 1;

  for (const hunk of hunks) {
    oldNo = hunk.oldStart;
    newNo = hunk.newStart;

    if (emitted) {
      out.push({ kind: 'context', text: '' });
    }

    for (const line of hunk.lines) {
      const entry: DiffLine = { kind: line.kind, text: line.text };

      if (line.kind === 'add') {
        entry.newNo = newNo++;
      } else if (line.kind === 'remove') {
        entry.oldNo = oldNo++;
      } else {
        entry.oldNo = oldNo++;
        entry.newNo = newNo++;
      }

      out.push(entry);
      emitted = true;
    }
  }

  return out;
}

export function DiffBody({ lines }: { lines: DiffLine[] }) {
  return (
    <>
      {lines.map((line, index) => (
        <span className={cn('pulse-diff-line', DIFF_KIND_TINT[line.kind])} key={`${index}-${line.text}`}>
          {line.text || ' '}
        </span>
      ))}
    </>
  );
}

/** The panel the tool card mounts for a file edit. Bleeds out of the card body's
 *  padding so tints/borders run flush to the card edges, and scrolls compactly
 *  like a code block (`max-h-[12rem]`). */
export function FileDiffPanel({ className, diff, path }: { className?: string; diff: string; path?: string }) {
  const lines = useMemo(() => parseDiff(diff), [diff]);

  return (
    <div className={cn('pulse-diff-box', className)} data-slot="file-diff-panel" title={path || undefined}>
      <DiffBody lines={lines} />
    </div>
  );
}

/** `+N −M` pair, as the changed-files rows and the tool title use it. Upstream
 *  springs the integer with Motion; this tier renders the number directly, so
 *  the digits come from the same count with the same sign and spacing. */
export function DiffCount({ added, className, removed }: { added: number; className?: string; removed: number }) {
  return (
    <span className={cn('pulse-diff-count', className)}>
      {added > 0 && <span className="pulse-diff-count__add">+{added}</span>}
      {removed > 0 && <span className="pulse-diff-count__remove">−{removed}</span>}
    </span>
  );
}

/** Numbered variant for the review pane (upstream's `showLineNumbers` path). */
export function DiffLinesWithGutter({ lines }: { lines: DiffLine[] }): ReactNode {
  return (
    <>
      {lines.map((line, index) => (
        <span className={cn('pulse-diff-line', 'pulse-diff-line--numbered', DIFF_KIND_TINT[line.kind])} key={`${index}-${line.text}`}>
          <span className="pulse-diff-line__no">{line.kind === 'add' ? line.newNo : line.oldNo}</span>
          {line.text || ' '}
        </span>
      ))}
    </>
  );
}
