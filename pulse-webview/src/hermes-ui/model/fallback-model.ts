// The tool-card model. Port of hermes-agent's
// `components/assistant-ui/tool/fallback-model` (@ a9c783f2) onto Pulse's
// backend: the exported surface, the precedence rules, and the clamps are
// upstream's; the tool tables and result keys are Pulse's, read from
// `src/tools/` so a card can never describe a field the agent never emitted.
//
// Upstream's file also carries per-tool renderers for surfaces Pulse does not
// ship (cronjob, image generation, pet, MoA). Those are deliberately absent —
// see PROVENANCE for the exclusion list rather than a silently dead branch.

import { firstStringField, capitalize } from '../lib/text';
import { isFileEditTool } from '../lib/tool-render-class';
import { clampForDisplay, contextValue, formatDurationSeconds, isRecord, numberValue, parseMaybeObject, prettyJson, unwrapToolPayload } from './format';
import { findFirstUrl, isPreviewableTarget, looksLikePath, looksLikeUrl } from './targets';
import type { CountMetric, SearchResultRow, ToolMeta, ToolPart, ToolStatus, ToolTone, ToolView } from './types';

export * from './format';
export * from './targets';
export * from './types';
export { isCardTool, isFileEditTool, isSilentTool } from '../lib/tool-render-class';

export interface DiffLineStats {
  added: number;
  removed: number;
}

export function countDiffLineStats(diff: string): DiffLineStats {
  let added = 0;
  let removed = 0;

  for (const line of diff.split('\n')) {
    if (line.startsWith('+') && !line.startsWith('+++')) {
      added += 1;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      removed += 1;
    }
  }

  return { added, removed };
}

export function fileEditPath(args: Record<string, unknown>, result: Record<string, unknown>): string {
  return (
    firstStringField(args, ['path', 'file', 'filepath', 'file_path']) ||
    firstStringField(result, ['path', 'file', 'filepath', 'resolved_path', 'file_path']) ||
    htmlPathFromInlineDiff(firstStringField(result, ['inline_diff', 'diff']))
  );
}

export function fileEditBasename(path: string): string {
  const normalized = (path ?? '').replace(/\\/g, '/').trim();

  return normalized.split('/').filter(Boolean).pop() || normalized;
}

function numericField(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key];

  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** `read_file` receipts are `NN| content` — recover the line window it shows. */
function readFileLineLabel(args: Record<string, unknown>, result: Record<string, unknown>): string {
  const offset = numericField(args, 'offset');
  const limit = numericField(args, 'limit');

  if (offset === undefined && limit === undefined) {
    return '';
  }

  const content = firstStringField(result, ['content']);

  if (offset !== undefined && offset > 0) {
    if (limit === undefined || limit <= 1) {
      return `L${offset}`;
    }

    return `L${offset}-${offset + limit - 1}`;
  }

  const lines = content
    .split('\n')
    .map(line => /^(\d+)\|/.exec(line)?.[1])
    .filter((line): line is string => Boolean(line))
    .map(Number);

  if (lines.length === 0) {
    return '';
  }

  const start = lines[0] as number;
  const end = lines[lines.length - 1] as number;

  return start === end ? `L${start}` : `L${start}-${end}`;
}

function shellCommand(args: Record<string, unknown>): string {
  return firstStringField(args, ['command', 'code']);
}

// ---------------------------------------------------------------------------
// Per-tool presentation
// ---------------------------------------------------------------------------

type MetaMap = Record<string, ToolMetaSpec>;

interface ToolMetaSpec {
  icon?: string;
  tone?: ToolTone;
  done?: string;
  pending?: string;
  pendingAction?: string;
}

const TOOL_META: MetaMap = {
  read_file: { icon: 'file', tone: 'file', done: 'Read' },
  list_files: { icon: 'list', tone: 'file', done: 'Listed' },
  search_code: { icon: 'search', tone: 'default', done: 'Searched' },
  write_file: { icon: 'file-add', tone: 'file', done: 'Created' },
  edit_file: { icon: 'edit', tone: 'file', done: 'Edited' },
  copy_file: { icon: 'copy', tone: 'file', done: 'Copied' },
  run_terminal: { icon: 'terminal', tone: 'terminal', done: 'Ran' },
  execute_code: { icon: 'terminal', tone: 'terminal', done: 'Ran code' },
  start_terminal: { icon: 'terminal', tone: 'terminal', done: 'Started process' },
  check_terminal: { icon: 'terminal', tone: 'terminal', done: 'Checked process' },
  read_terminal_output: { icon: 'output', tone: 'terminal', done: 'Read output' },
  stop_terminal: { icon: 'debug-stop', tone: 'terminal', done: 'Stopped process' },
  list_terminal_processes: { icon: 'list', tone: 'terminal', done: 'Listed processes' },
  cleanup_terminal_processes: { icon: 'trash', tone: 'terminal', done: 'Cleaned processes' },
  typecheck_workspace: { icon: 'check', tone: 'default', done: 'Typechecked' },
  verify_ui_workspace: { icon: 'check', tone: 'browser', done: 'Verified UI' },
  verify_ui_routes: { icon: 'check', tone: 'browser', done: 'Verified routes' },
  scaffold_nextjs: { icon: 'add', tone: 'file', done: 'Scaffolded' },
  web_search: { icon: 'search', tone: 'web', done: 'Searched web' },
  web_fetch: { icon: 'globe', tone: 'web', done: 'Fetched' },
  session_search: { icon: 'history', tone: 'agent', done: 'Searched sessions' },
  delegate_to_subagent: { icon: 'rocket', tone: 'agent', done: 'Delegated' },
  delegate_to_subagent_batch: { icon: 'rocket', tone: 'agent', done: 'Delegated batch' },
  ask_user: { icon: 'question', tone: 'agent', done: 'Asked' },
  think: { icon: 'brain', tone: 'agent', done: 'Thought' },
  verify: { icon: 'check', tone: 'agent', done: 'Verified' },
  display_pulse_task: { icon: 'pulse', tone: 'pulse', done: 'Showed task card' },
  discover_host_capabilities: { icon: 'symbol-method', tone: 'agent', done: 'Discovered editor tools' },
  invoke_host_capability: { icon: 'zap', tone: 'agent', done: 'Used editor tool' },
};

Object.assign(TOOL_META, ...['click', 'evaluate', 'hover', 'navigate', 'screenshot', 'select', 'snapshot', 'type'].map(action => ({
  [`browser_${action}`]: {
    icon: action === 'screenshot' ? 'file-media' : 'globe',
    tone: 'browser',
    done: capitalize(action),
  },
})));

const DEFAULT_META: ToolMetaSpec = { icon: 'tools', tone: 'default' };

const PREFIX_META: { icon?: string; prefix: string; tone: ToolTone }[] = [
  { prefix: 'browser_', icon: 'globe', tone: 'browser' },
  { prefix: 'web_', icon: 'globe', tone: 'web' },
  { prefix: 'terminal_', icon: 'terminal', tone: 'terminal' },
];

function titleForTool(name: string): string {
  const normalized = name.replace(/^browser_/, '').replace(/^web_/, '');

  return normalized.split('_').filter(Boolean).map(capitalize).join(' ') || name;
}

export function toolMeta(name: string): ToolMeta {
  const known = TOOL_META[name];

  if (known) {
    const title = titleForTool(name);

    return {
      done: known.done ?? title,
      icon: known.icon,
      pending: known.pending ?? `${title}…`,
      pendingAction: known.pending ?? `Running ${title.toLowerCase()}`,
      tone: known.tone ?? 'default',
    };
  }

  const prefix = PREFIX_META.find(entry => name.startsWith(entry.prefix));
  const title = titleForTool(name);

  return {
    done: title,
    icon: prefix?.icon ?? DEFAULT_META.icon,
    pending: `${title}…`,
    pendingAction: `Running ${title.toLowerCase()}`,
    tone: prefix?.tone ?? DEFAULT_META.tone ?? 'default',
  };
}

// ---------------------------------------------------------------------------
// Result counts — "12 matches", "3 files"
// ---------------------------------------------------------------------------

const COUNT_FIELD_KEYS = [
  'count',
  'matches',
  'results_count',
  'num_results',
  'total',
  'files',
  'lines',
  'items',
  'hits',
  'documents',
  'rows',
] as const;

const COUNT_ARRAY_KEYS = ['results', 'items', 'matches', 'files', 'documents', 'sources', 'rows'] as const;
const COUNT_EXCLUDED_KEYS = new Set(['duration_s', 'exit_code', 'status_code']);

const COUNT_NOUN_BY_ARRAY: Record<string, string> = {
  results: 'results',
  items: 'items',
  matches: 'matches',
  files: 'files',
  documents: 'documents',
  sources: 'sources',
  rows: 'rows',
};

const DEFAULT_COUNT_NOUN_BY_TOOL: Record<string, string> = {
  search_code: 'matches',
  list_files: 'files',
  web_search: 'results',
  session_search: 'sessions',
};

function countFromUnknown(value: unknown): null | number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.length;
  }

  if (typeof value === 'string') {
    const lines = value.split('\n').filter(line => line.trim());

    return lines.length > 1 ? lines.length : null;
  }

  return null;
}

function singularizeNoun(noun: string): string {
  if (noun.endsWith('ies')) {
    return `${noun.slice(0, -3)}y`;
  }

  if (noun.endsWith('ses') || noun.endsWith('xes')) {
    return noun.slice(0, -2);
  }

  return noun.endsWith('s') && !noun.endsWith('ss') ? noun.slice(0, -1) : noun;
}

function pluralizeNoun(noun: string, count: number): string {
  if (count === 1) {
    return singularizeNoun(noun);
  }

  return noun.endsWith('s') ? noun : `${noun}s`;
}

export function formatCountLabel(metric: CountMetric): string {
  return `${metric.count.toLocaleString()} ${pluralizeNoun(metric.noun, metric.count)}`;
}

function countMetric(count: number, noun: string): CountMetric {
  return { count, noun };
}

function fallbackCountNoun(toolName: string): string {
  return DEFAULT_COUNT_NOUN_BY_TOOL[toolName] ?? 'results';
}

function normalizeMetricForTool(toolName: string, metric: CountMetric): CountMetric {
  const noun = metric.noun === 'line' || metric.noun === 'lines' ? (toolName === 'read_file' ? 'lines' : metric.noun) : metric.noun;

  return countMetric(metric.count, noun);
}

function countFromRecord(record: Record<string, unknown>, fallbackNoun: string): CountMetric | null {
  for (const key of COUNT_FIELD_KEYS) {
    if (COUNT_EXCLUDED_KEYS.has(key)) {
      continue;
    }

    const value = record[key];

    if (Array.isArray(value)) {
      return countMetric(value.length, COUNT_NOUN_BY_ARRAY[key] ?? fallbackNoun);
    }

    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
      return countMetric(value, COUNT_NOUN_BY_ARRAY[key] ?? fallbackNoun);
    }
  }

  for (const key of COUNT_ARRAY_KEYS) {
    const value = record[key];

    if (Array.isArray(value) && value.length) {
      return countMetric(value.length, COUNT_NOUN_BY_ARRAY[key] ?? fallbackNoun);
    }
  }

  return null;
}

function countFromText(value: string, fallbackNoun: string): CountMetric | null {
  const match = /(\d+)\s+([A-Za-z_]+)/.exec(value);

  if (!match) {
    return null;
  }

  const noun = (match[2] ?? '').toLowerCase();

  return countMetric(Number(match[1]), noun || fallbackNoun);
}

export function toolResultCount(part: ToolPart, args: Record<string, unknown>, result: Record<string, unknown>): CountMetric | null {
  void args;
  const fallbackNoun = fallbackCountNoun(part.toolName);
  const fromRecord = countFromRecord(result, fallbackNoun);

  if (fromRecord) {
    return normalizeMetricForTool(part.toolName, fromRecord);
  }

  const unwrapped = unwrapToolPayload(result);
  const direct = countFromUnknown(unwrapped);

  if (direct !== null) {
    return normalizeMetricForTool(part.toolName, countMetric(direct, fallbackNoun));
  }

  const summaryText = firstStringField(result, ['summary', 'message', 'detail']) || fallbackDetailText(args, result);

  const textMetric = countFromText(summaryText, fallbackNoun);

  return textMetric ? normalizeMetricForTool(part.toolName, textMetric) : null;
}

// ---------------------------------------------------------------------------
// Text hygiene
// ---------------------------------------------------------------------------

const INLINE_CODE_SPLIT_RE = /(`[^`\n]+`)/g;
const CITATION_MARKER_RE = /(?<=[\p{L}\p{N})\].,!?:;"'”’])\[(?:\d+(?:\s*,\s*\d+)*)\](?!\()/gu;
const BACKTICK_NOISE_RE = /`{3,}/g;

export function looksRedundant(title: string, detail: string): boolean {
  if (!detail) {
    return true;
  }

  const norm = (input: string) => input.toLowerCase().replace(/\s+/g, ' ').trim();

  return norm(title) === norm(detail);
}

export function cleanVisibleText(text: string): string {
  return text
    .split(INLINE_CODE_SPLIT_RE)
    .map(part =>
      part.startsWith('`')
        ? part
        : part
            .replace(BACKTICK_NOISE_RE, '')
            .replace(CITATION_MARKER_RE, '')
            .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_match, label: string, href: string) => `${label} ${href}`),
    )
    .join('');
}

function stripAnsi(value: string): string {
  return value.replace(new RegExp(`${String.fromCharCode(27)}\\[[0-9;]*m`, 'g'), '');
}

export function stripInlineDiffChrome(value: string): string {
  return value
    ? stripAnsi(value)
        .replace(/^\s*┊\s*review diff\s*\n/i, '')
        .trim()
    : '';
}

function htmlPathFromInlineDiff(value: string): string {
  const cleaned = stripInlineDiffChrome(value);

  for (const match of cleaned.matchAll(/(?:^|\s)(?:[ab]\/)?([^\s]+\.html?)(?=\s|$)/gi)) {
    const candidate = match[1]?.trim();

    if (candidate) {
      return candidate;
    }
  }

  return '';
}

export function inlineDiffFromResult(result: unknown): string {
  const record = parseMaybeObject(result);

  for (const key of ['inline_diff', 'diff']) {
    const value = record[key];

    if (typeof value === 'string' && value.trim()) {
      return stripInlineDiffChrome(value);
    }
  }

  return '';
}

function stripDividerLines(value: string): string {
  return value
    .split('\n')
    .filter(line => !/^[-=]{3,}\s*$/.test(line.trim()))
    .join('\n')
    .trim();
}

function minimalValueSummary(value: unknown): string {
  if (value == null) {
    return '';
  }

  if (typeof value === 'string') {
    return value;
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  return '';
}

function fallbackDetailText(args: unknown, result: unknown): string {
  const record = parseMaybeObject(result);

  for (const key of ['output', 'content', 'text', 'stdout', 'error', 'message', 'summary']) {
    const direct = minimalValueSummary(record[key]);

    if (direct) {
      return direct;
    }
  }

  const argsRecord = parseMaybeObject(args);
  const command = firstStringField(argsRecord, ['command', 'code', 'query', 'url', 'path']);

  if (command) {
    return command;
  }

  return result === undefined ? '' : prettyJson(result);
}

function collectResultItems(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }

  if (!isRecord(value)) {
    return [];
  }

  for (const key of ['results', 'items', 'matches', 'documents', 'sources', 'data']) {
    const candidate = value[key];

    if (Array.isArray(candidate)) {
      return candidate;
    }
  }

  return [];
}

export function extractSearchResults(result: unknown, limit = 6): SearchResultRow[] {
  return collectResultItems(result)
    .slice(0, limit)
    .map(row => {
      const record = parseMaybeObject(row);

      return {
        snippet: firstStringField(record, ['snippet', 'content', 'body', 'text']),
        title: firstStringField(record, ['title', 'name', 'url']) || 'result',
        url: firstStringField(record, ['url', 'href', 'link']),
      };
    })
    .filter(row => row.title);
}

// ---------------------------------------------------------------------------
// Status, error, subtitle, detail
// ---------------------------------------------------------------------------

export function toolErrorText(part: ToolPart, result: Record<string, unknown>): string {
  if (part.isError) {
    return firstStringField(result, ['error', 'message', 'detail']) || 'Tool reported an error.';
  }

  const explicit = firstStringField(result, ['error']);

  if (explicit) {
    return explicit;
  }

  const status = String(result.status ?? '').toLowerCase();

  if (status && !/ok|success|passed|complete|done/.test(status) && /fail|error|denied|blocked|cancel|timeout/.test(status)) {
    return firstStringField(result, ['message', 'detail', 'reason']) || `status: ${status}`;
  }

  return '';
}

export function toolStatus(part: ToolPart, resultRecord: Record<string, unknown>): ToolStatus {
  if (part.result === undefined && !part.isError) {
    return 'running';
  }

  const error = toolErrorText(part, resultRecord);

  if (error) {
    const exitCode = numericField(resultRecord, 'exit_code');

    return exitCode === undefined || exitCode !== 0 ? 'error' : 'warning';
  }

  const exitCode = numericField(resultRecord, 'exit_code');

  if (exitCode !== undefined && exitCode !== 0) {
    return 'warning';
  }

  return 'success';
}

function durationLabel(resultRecord: Record<string, unknown>): string | undefined {
  const seconds = numberValue(resultRecord.duration_s ?? resultRecord.duration ?? resultRecord.elapsed_s);

  if (seconds === null) {
    return undefined;
  }

  const label = formatDurationSeconds(seconds);

  return label || undefined;
}

function toolPreviewTarget(toolName: string, args: Record<string, unknown>, result: Record<string, unknown>): string {
  const url = firstStringField(args, ['url']) || firstStringField(result, ['url']);

  if (url && (isPreviewableTarget(url) || looksLikeUrl(url))) {
    return url;
  }

  const path = fileEditPath(args, result);

  if (path && (looksLikePath(path) || /\.html?$/i.test(path)) && (isFileEditTool(toolName) || toolName.startsWith('browser_'))) {
    return path;
  }

  return findFirstUrl(result) || '';
}

function toolSubtitle(part: ToolPart, args: Record<string, unknown>, result: Record<string, unknown>): string {
  switch (part.toolName) {
    case 'read_file': {
      const label = readFileLineLabel(args, result);
      const path = firstStringField(args, ['path', 'file', 'file_path']);

      return [fileEditBasename(path), label].filter(Boolean).join(' · ');
    }
    case 'run_terminal':
    case 'execute_code':
      return '';
    default: {
      const path = firstStringField(args, ['path', 'file', 'file_path', 'directory']);

      if (path) {
        return fileEditBasename(path);
      }

      const query = firstStringField(args, ['query', 'pattern', 'search_term', 'url', 'goal', 'task']);

      return query ? clampForDisplay(query.replace(/\s+/g, ' ').trim(), 80) : '';
    }
  }
}

export function toolDetailLabel(toolName: string): string {
  if (toolName.startsWith('browser_')) {
    return 'Page';
  }

  if (toolName === 'web_search' || toolName === 'session_search') {
    return 'Results';
  }

  if (isFileEditTool(toolName)) {
    return 'Change';
  }

  return 'Result';
}

function toolDetailText(part: ToolPart, args: Record<string, unknown>, result: Record<string, unknown>): string {
  if (part.toolName === 'run_terminal' || part.toolName === 'execute_code') {
    const merged = [firstStringField(result, ['stdout']), firstStringField(result, ['stderr']), firstStringField(result, ['output'])]
      .filter(Boolean)
      .join('\n');

    return clampForDisplay(merged || fallbackDetailText(args, result));
  }

  if (part.toolName === 'browser_snapshot') {
    const snapshot = firstStringField(result, ['snapshot', 'content', 'text']) || fallbackDetailText(args, result);

    return clampForDisplay(snapshot);
  }

  if (isFileEditTool(part.toolName)) {
    const diff = inlineDiffFromResult(result);

    return clampForDisplay(diff || firstStringField(result, ['message', 'summary']) || fallbackDetailText(args, result));
  }

  return clampForDisplay(fallbackDetailText(args, result));
}

export interface ToolTitleParts {
  action?: { prefix: string; suffix: string; text: string };
  title: string;
}

function titlePartsFromAction(title: string, action?: string): ToolTitleParts {
  if (!action) {
    return { title };
  }

  return { action: { prefix: '', suffix: '', text: action }, title };
}

function dynamicTitle(part: ToolPart, args: Record<string, unknown>, result: Record<string, unknown>, base: ToolTitleParts): ToolTitleParts {
  const count = toolResultCount(part, args, result);

  if (!count || !base.title || base.title.endsWith('…')) {
    return base;
  }

  return { ...base, title: `${base.title} ${formatCountLabel(count)}` };
}

export function toolCopyPayload(part: ToolPart, view: ToolView): { label: string; text: string } {
  const label = view.detailLabel || 'Result';
  const body = view.detail || view.inlineDiff || prettyJson(part.args);

  return { label, text: `${part.toolName}\n\n${label}:\n${body}`.trim() };
}

/** Fold one tool call into the card the transcript paints. */
export function buildToolView(part: ToolPart, inlineDiff?: string): ToolView {
  const argsRecord = parseMaybeObject(part.args);
  const resultRecord = parseMaybeObject(part.result);
  const meta = toolMeta(part.toolName);
  const status = toolStatus(part, resultRecord);
  // Skip residual error-heuristic text once status is success: a stale isError
  // envelope over a landed write must not foul the subtitle.
  const error = status === 'success' ? '' : toolErrorText(part, resultRecord);

  const baseTitle = part.result === undefined ? meta.pending : meta.done;
  const titleParts = dynamicTitle(part, argsRecord, resultRecord, titlePartsFromAction(baseTitle, part.result === undefined ? meta.pendingAction : undefined));
  const title = titleParts.title;
  const titleEnriched = title !== baseTitle;
  const baseSubtitle = error || toolSubtitle(part, argsRecord, resultRecord);

  const keepSubtitleWithTitle = part.toolName === 'run_terminal' || part.toolName === 'execute_code' || (isFileEditTool(part.toolName) && Boolean(baseSubtitle.trim()));
  const subtitle = titleEnriched && !error && !keepSubtitleWithTitle ? '' : baseSubtitle;

  const detailBody = stripDividerLines(toolDetailText(part, argsRecord, resultRecord));
  const detail = error ? [error, detailBody].filter(Boolean).filter((value, index, list) => list.findIndex(entry => entry.trim() === value.trim()) === index).join('\n\n') : detailBody;

  const searchHits = part.toolName === 'web_search' && status !== 'error' ? extractSearchResults(part.result) : undefined;
  const searchQuery = part.toolName === 'web_search' ? firstStringField(argsRecord, ['search_term', 'query']) || contextValue(argsRecord) : '';
  const resultCount = status === 'error' ? null : toolResultCount(part, argsRecord, resultRecord);

  // Shell/code tools surface stdout and stderr as separate labeled streams:
  // many CLIs use stderr for informational messages (npm progress, git hints),
  // so stderr is deliberately not painted destructively.
  const rendersAnsi = part.toolName === 'run_terminal' || part.toolName === 'execute_code';
  const stdout = rendersAnsi ? firstStringField(resultRecord, ['stdout']) : '';
  const stderrRaw = rendersAnsi ? firstStringField(resultRecord, ['stderr']) : '';
  const hasSplitStreams = rendersAnsi && (Boolean(stdout) || Boolean(stderrRaw));

  return {
    countLabel: resultCount ? formatCountLabel(resultCount) : undefined,
    detail,
    detailLabel: error ? 'Error details' : toolDetailLabel(part.toolName),
    durationLabel: durationLabel(resultRecord),
    icon: meta.icon,
    imageUrl: rendersAnsi ? '' : firstStringField(resultRecord, ['image_path', 'path']),
    inlineDiff: inlineDiff ?? (isFileEditTool(part.toolName) ? inlineDiffFromResult(part.result) : ''),
    previewTarget: toolPreviewTarget(part.toolName, argsRecord, resultRecord) || undefined,
    rendersAnsi: rendersAnsi || undefined,
    searchQuery: searchQuery || undefined,
    searchHits: searchHits?.length ? searchHits : undefined,
    stderr: hasSplitStreams ? stderrRaw || undefined : undefined,
    terminalCommand: part.toolName === 'run_terminal' || part.toolName === 'execute_code' ? shellCommand(argsRecord) || undefined : undefined,
    terminalExitCode: part.toolName === 'run_terminal' ? numericField(resultRecord, 'exit_code') : undefined,
    stdout: hasSplitStreams ? stdout || undefined : undefined,
    status,
    subtitle,
    title,
    titleAction: titleParts.action,
    tone: meta.tone,
  };
}
