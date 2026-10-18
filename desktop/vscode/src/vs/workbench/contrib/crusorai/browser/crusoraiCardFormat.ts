/*---------------------------------------------------------------------------------------------
 * Card-content formatting, ported from hermes desktop (owner 2026-09-09:
 * "resolve the gaps fully — mimic exact wireframes"). Pure functions, no DOM —
 * the same discipline as hermes' changed-files.ts ("Pure derivation… No
 * React/DOM") and lib/ansi.ts ("returns a flat array of styled segments").
 * The renderer paints; this file decides WHAT is painted.
 *--------------------------------------------------------------------------------------------*/

// ── hermes lib/ansi.ts ──────────────────────────────────────────────────────
// Minimal ANSI SGR parser for terminal output inside tool cards. Only the SGR
// codes that show up in practice (color, bold, reset); cursor motions and
// other CSI sequences are consumed so they never leak into the transcript.

export type CrusorAnsiColor =
	| 'black' | 'red' | 'green' | 'yellow' | 'blue' | 'magenta' | 'cyan' | 'white'
	| 'bright-black' | 'bright-red' | 'bright-green' | 'bright-yellow'
	| 'bright-blue' | 'bright-magenta' | 'bright-cyan' | 'bright-white';

export interface CrusorAnsiSegment {
	readonly bold: boolean;
	readonly fg: CrusorAnsiColor | null;
	readonly text: string;
}

const FG_BY_CODE: Record<number, CrusorAnsiColor> = {
	30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
	34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white',
	90: 'bright-black', 91: 'bright-red', 92: 'bright-green', 93: 'bright-yellow',
	94: 'bright-blue', 95: 'bright-magenta', 96: 'bright-cyan', 97: 'bright-white',
};

// CSI = ESC '[' params 'final'. Only SGR (final 'm') is applied; other finals
// are matched and consumed so they don't leak into the rendered text.
const CSI_RE = /\x1b\[([\d;]*)([\x40-\x7e])/g;
// Other escapes (single-char OSC/SS3 etc.) — stripped silently.
const OTHER_ESCAPE_RE = /\x1b[@-Z\\-_]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;

export function hasAnsiCodes(input: string): boolean {
	return /\x1b\[/.test(input);
}

export function stripAnsi(input: string): string {
	if (!input) { return input; }
	return input.replace(OTHER_ESCAPE_RE, '').replace(CSI_RE, '');
}

export function parseAnsi(input: string): CrusorAnsiSegment[] {
	if (!input) { return []; }
	const cleaned = input.replace(OTHER_ESCAPE_RE, '');

	const segments: CrusorAnsiSegment[] = [];
	let cursor = 0;
	let bold = false;
	let fg: CrusorAnsiColor | null = null;

	const pushText = (text: string) => {
		if (!text) { return; }
		const last = segments[segments.length - 1];
		if (last && last.bold === bold && last.fg === fg) {
			segments[segments.length - 1] = { bold, fg, text: last.text + text };
			return;
		}
		segments.push({ bold, fg, text });
	};

	CSI_RE.lastIndex = 0;
	let match: RegExpExecArray | null;
	while ((match = CSI_RE.exec(cleaned)) !== null) {
		const start = match.index;
		if (start > cursor) { pushText(cleaned.slice(cursor, start)); }
		if (match[2] === 'm') {
			const codes = match[1].split(';').map(part => (part === '' ? 0 : Number(part)))
				.filter(value => Number.isFinite(value));
			for (let i = 0; i < codes.length; i += 1) {
				const code = codes[i];
				if (code === 0) { bold = false; fg = null; }
				else if (code === 1) { bold = true; }
				else if (code === 22) { bold = false; }
				else if (code === 39) { fg = null; }
				else if (code in FG_BY_CODE) { fg = FG_BY_CODE[code]; }
				else if (code === 38) {
					// 256-color / truecolor — skip the trailing args we don't render.
					if (codes[i + 1] === 5) { i += 2; }
					else if (codes[i + 1] === 2) { i += 4; }
				}
			}
		}
		cursor = CSI_RE.lastIndex;
	}
	if (cursor < cleaned.length) { pushText(cleaned.slice(cursor)); }
	return segments;
}

// ── hermes diff-lines.tsx: the unified-diff grammar ─────────────────────────
// File-headers + `@@` hunk noise and the `+/-` gutter are DROPPED — changes
// read by tint color + a 2px gutter accent.

export type CrusorDiffKind = 'add' | 'context' | 'remove';

export interface CrusorDiffLine {
	readonly kind: CrusorDiffKind;
	readonly text: string;
	readonly newNo?: number;
	readonly oldNo?: number;
}

const DIFF_HEADER_PREFIXES = [
	'diff --git', 'index ', '--- ', '+++ ',
	'similarity ', 'rename ', 'new file', 'deleted file',
];

function isArrowHeaderLine(line: string): boolean {
	const trimmed = line.trim();
	return trimmed.includes('→') && /^\S.*→\s*\S+$/.test(trimmed) && !/^[+\-@]/.test(trimmed);
}

/** hermes stripDiffFileHeaders: strip the header zone up to the first hunk. */
export function stripDiffFileHeaders(diff: string): string {
	const lines = diff.split('\n');
	let start = 0;
	for (; start < lines.length; start += 1) {
		const line = lines[start];
		if (line.startsWith('@@')) { break; }
		if (line.trim() === '' || isArrowHeaderLine(line)
			|| DIFF_HEADER_PREFIXES.some(prefix => line.startsWith(prefix))) { continue; }
		break;
	}
	return lines.slice(start).join('\n');
}

function diffKind(line: string): CrusorDiffKind {
	if (line.startsWith('+') && !line.startsWith('+++')) { return 'add'; }
	if (line.startsWith('-') && !line.startsWith('---')) { return 'remove'; }
	return 'context';
}

/** Drop the leading +/-/space gutter so changes read by color alone. */
function stripDiffMarker(line: string): string {
	if (diffKind(line) !== 'context' || line.startsWith(' ')) { return line.slice(1); }
	return line;
}

/** hermes parseDiff: hunks parsed, line numbers tracked, blank separator
 *  between hunks; non-hunk payloads fall back to line-by-line kinds. */
export function parseDiff(diff: string): CrusorDiffLine[] {
	const cleaned = stripDiffFileHeaders(diff);
	const rawLines = cleaned.split('\n');
	const out: CrusorDiffLine[] = [];
	let emitted = false;
	let oldNo = 1;
	let newNo = 1;
	let active: { oldStart: number; newStart: number } | null = null;
	let inHunk = false;

	for (const line of rawLines) {
		if (line.startsWith('@@')) {
			const match = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
			if (!match) { active = null; continue; }
			if (emitted) { out.push({ kind: 'context', text: '' }); }
			active = { oldStart: Number(match[1]), newStart: Number(match[2]) };
			oldNo = active.oldStart;
			newNo = active.newStart;
			inHunk = true;
			continue;
		}
		if (!inHunk || !active || line.startsWith('\\')) { continue; }
		const kind = diffKind(line);
		const entry: CrusorDiffLine = { kind, text: stripDiffMarker(line) };
		if (kind === 'add') { (entry as { newNo?: number }).newNo = newNo++; }
		else if (kind === 'remove') { (entry as { oldNo?: number }).oldNo = oldNo++; }
		else { (entry as { oldNo?: number }).oldNo = oldNo++; (entry as { newNo?: number }).newNo = newNo++; }
		out.push(entry);
		emitted = true;
	}

	if (!emitted) {
		// Fallback for unexpected non-hunk payloads (hermes does the same).
		return rawLines.map(line => ({ kind: diffKind(line), text: stripDiffMarker(line) }));
	}
	return out;
}

/** hermes countDiffLineStats: +/- lines, git headers excluded. */
export function countDiffLineStats(diff: string): { added: number; removed: number } {
	let added = 0;
	let removed = 0;
	for (const line of diff.split('\n')) {
		if (line.startsWith('+++') || line.startsWith('---')) { continue; }
		if (line.startsWith('+')) { added += 1; }
		else if (line.startsWith('-')) { removed += 1; }
	}
	return { added, removed };
}

// ── hermes changed-files.ts: the turn's "N files changed" fold ──────────────

export interface CrusorChangedFile {
	readonly added: number;
	/** Basename, for the row label. */
	readonly name: string;
	/** Path exactly as the tool reported it. */
	readonly path: string;
	readonly removed: number;
}

interface ChangedFileToolLike {
	readonly name: string;
	readonly state: string;
	readonly arguments?: unknown;
	readonly result?: unknown;
}

function resultDiffString(result: unknown): string {
	if (typeof result === 'string') { return result; }
	if (result && typeof result === 'object') {
		const diff = (result as Record<string, unknown>)['diff'];
		if (typeof diff === 'string') { return diff; }
	}
	return '';
}

function resultPathString(args: unknown, result: unknown): string {
	for (const source of [args, result]) {
		if (source && typeof source === 'object') {
			const path = (source as Record<string, unknown>)['path'] ?? (source as Record<string, unknown>)['dest'];
			if (typeof path === 'string' && path) { return path; }
		}
	}
	return '';
}

/** One row per file the turn edited, in first-touched order, +/- summed.
 *  Only LANDED edits count: running has no result, failed changed nothing. */
export function deriveChangedFiles(tools: readonly ChangedFileToolLike[]): CrusorChangedFile[] {
	const byPath = new Map<string, { added: number; name: string; path: string; removed: number }>();
	for (const tool of tools) {
		if (!['write_file', 'edit_file', 'copy_file'].includes(tool.name)) { continue; }
		if (tool.state !== 'passed' && tool.state !== 'completed') { continue; }
		const path = resultPathString(tool.arguments, tool.result);
		if (!path) { continue; }
		// Exact counts first: the engine receipt carries
		// "(lines added: N, removed: M)" — the bounded diff PREVIEW in the
		// same result would undercount a large change (field 2026-09-10:
		// the old bare "File written: <path>" receipt counted +0 -0).
		const text = typeof tool.result === 'string' ? tool.result : '';
		const receiptStats = /lines added:\s*(\d+),\s*removed:\s*(\d+)/i.exec(text);
		let stats: { added: number; removed: number };
		if (receiptStats) {
			stats = { added: Number(receiptStats[1]), removed: Number(receiptStats[2]) };
		} else {
			const diff = resultDiffString(tool.result);
			if (!diff) { continue; }
			stats = countDiffLineStats(diff);
		}
		const existing = byPath.get(path);
		if (existing) {
			existing.added += stats.added;
			existing.removed += stats.removed;
		} else {
			const name = path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;
			byPath.set(path, { added: stats.added, name, path, removed: stats.removed });
		}
	}
	return [...byPath.values()];
}

// ── hermes fixed-row-window: bounded paint for long output ──────────────────

export interface CrusorWindowedLines {
	/** The LAST `max` lines (the live tail is what matters while streaming). */
	readonly lines: string[];
	/** How many lines were clamped away — painted, never lost (count says). */
	readonly hidden: number;
}

/** Lines are clamped for *paint*, never for correctness. */
export function windowedTailLines(text: string, max = 400): CrusorWindowedLines {
	const lines = (text ?? '').split('\n');
	if (lines.length <= max) { return { lines, hidden: 0 }; }
	return { lines: lines.slice(lines.length - max), hidden: lines.length - max };
}

// ── terminal envelope: engine's result text vs hermes' card ─────────────────
// src/tools/terminal_tools.py composes the result as
//   ["STDOUT:\n<s>"] + ["\nSTDERR:\n<e>"] + "\nExit code: N"
// hermes' terminal-output card receives raw output only — the marker lines
// are crusor's engine envelope and must never surface in the card (field
// 2026-09-09: the stale panel painted the raw envelope, and even the new
// card would have shown "STDOUT:" as body text). The Exit-code trailer is
// NOT dropped here: terminalBody parses it for the status row first.

/** True when the text carries the engine's terminal envelope signature. */
export function hasTerminalEnvelope(text: string): boolean {
	return /^STDOUT:\s*$/m.test(text ?? '') && /^Exit code: -?\d+\s*$/m.test(text ?? '');
}

/** Drop the engine's STDOUT:/STDERR: marker lines, keep the output itself. */
export function stripTerminalEnvelope(text: string): string {
	const lines = (text ?? '').split('\n');
	if (!lines.length) { return text ?? ''; }
	const enveloped = hasTerminalEnvelope(text);
	const keep = lines.filter((line, i) => {
		if (i === 0 && line.trimEnd() === 'STDOUT:') { return false; }
		if (enveloped && line.trimEnd() === 'STDERR:') { return false; }
		return true;
	});
	return keep.join('\n');
}

