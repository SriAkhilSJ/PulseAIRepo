/**
 * Does the ported Hermes Agent UI actually render — inside Pulse?
 * ================================================================
 * Provider-free verification for `src/hermes-ui`: the pure model half is asserted
 * as data (grouping, budgets, normalization), and the React half is mounted with
 * `render()` from a synthetic transcript. Zero CopilotKit provider, zero network,
 * zero API key, zero tokens.
 *
 * The transcript these tests feed is built from PULSE's real tool names
 * (`run_terminal`, `write_file`, `read_file`, `search_code`, `web_search`) and
 * Pulse's real event shapes (bridge protocol v2 `safety_request` with
 * `tool_name`/`tool_args`/`diff`, AG-UI messages with `toolCalls[].id`), so a
 * component that only works against Hermes' backend would fail here.
 *
 * The branding guard at the bottom enforces the same rule the prompt engine
 * carries: nothing the model or the user can SEE may name the upstream vendor.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';

import {
  APPROVAL_TOOLS,
  COMPACTION_LABEL,
  EXPANDABLE_COLLAPSED_PX,
  LIVE_TAIL_PARTS,
  MAX_CHANGED_FILE_ROWS,
  RENDER_BUDGET,
  TURN_QUIET_S,
  activitySignature,
  approvalBlocksTool,
  clampForDisplay,
  commandFromArgs,
  compactPreview,
  computeToolRun,
  deriveChangedFiles,
  deriveTimelineEntries,
  emptyTranscript,
  firstVisibleGroupIndex,
  groupsFromMessages,
  isCardTool,
  isFileEditTool,
  isSilentTool,
  liveTailStart,
  messagePaintWeight,
  parseDiff,
  reducePulseEvent,
  resolveShowEarlierAction,
  sameTimelineEntries,
  splitRunItems,
  stripDiffFileHeaders,
  summarizeToolRun,
  toolNarratesWait,
  toolPresentVerb,
  transcriptFromMessages,
  PulseAgentThread,
  PulseComposer,
  PulseToolRow,
  __resetElapsedTimerRegistryForTests,
  __resetToolViewForTests,
} from '../hermes-ui';
import type { PulseMessage, PulseTranscript, ToolPart } from '../hermes-ui';

const text = (value: string) => ({ text: value, type: 'text' as const });

const tool = (
  toolName: string,
  args: unknown,
  result: unknown,
  extra: Partial<ToolPart> = {}
): ToolPart => ({
  args,
  result,
  toolCallId: `${toolName}-1`,
  toolName,
  type: 'tool-call',
  ...extra,
});

const assistant = (id: string, content: PulseMessage['content'], failure?: string): PulseMessage => ({
  content,
  failure,
  id,
  role: 'assistant',
});

const user = (id: string, value: string): PulseMessage => ({ content: [text(value)], id, role: 'user' });

beforeEach(() => {
  __resetToolViewForTests();
  __resetElapsedTimerRegistryForTests();
  globalThis.localStorage?.clear();
});

afterEach(() => {
  globalThis.localStorage?.clear();
});

describe('grouping: what collapses and what stays a card', () => {
  it('Pulse file edits are cards, activity is a run, order preserved', () => {
    const names = ['read_file', 'search_code', 'write_file', 'run_terminal', 'run_terminal'];
    const items = splitRunItems(names);

    // Two reads, then the diff card, then the two commands as their own run.
    expect(items).toEqual([
      { end: 1, kind: 'run', start: 0 },
      { index: 2, kind: 'card' },
      { end: 4, kind: 'run', start: 3 },
    ]);
  });

  it('a non-tool part is its own card and breaks a run in half', () => {
    // Upstream's rule verbatim: "An empty name is a part that isn't a tool call
    // at all, which passes through as its own card." A run of one is still a run
    // — `ToolRun` renders a lone call as itself (count < 2).
    expect(splitRunItems(['run_terminal', '', 'read_file'])).toEqual([
      { end: 0, kind: 'run', start: 0 },
      { index: 1, kind: 'card' },
      { end: 2, kind: 'run', start: 2 },
    ]);
  });

  it('classifies Pulse tools by the same rules the fork uses', () => {
    expect(isFileEditTool('write_file')).toBe(true);
    expect(isFileEditTool('edit_file')).toBe(true);
    expect(isFileEditTool('scaffold_nextjs')).toBe(true);
    expect(isFileEditTool('run_terminal')).toBe(false);
    expect(isCardTool('ask_user')).toBe(true);
    expect(isCardTool('edit_file')).toBe(true);
    expect(isSilentTool('think')).toBe(true);
  });

  it('summarizes a run by category, narrating the live call in the present tense', () => {
    const tools = [tool('read_file', { path: 'a.py' }, 'x'), tool('run_terminal', { command: 'ls' }, 'y')];

    // Settled: one explore names its target ("Explored a.py"), a settled command
    // counts instead ("ran 1 command") — upstream's stated exception for `run`.
    expect(summarizeToolRun(tools, false)).toBe('Explored a.py, ran 1 command');
    expect(summarizeToolRun([tools[0] as ToolPart, tools[0] as ToolPart], false)).toBe('Explored 2 files');
    // Live: the pending call is the one narrated, and it leads.
    const live = [tool('read_file', { path: 'a.py' }, 'x'), tool('run_terminal', { command: 'ls' }, undefined)];
    const summary = summarizeToolRun(live, true);

    // Live clause names the target ("running ls"), the settled one counts.
    expect(summary).toBe('Explored a.py, running ls');
  });

  it('names each Pulse tool category with a present-tense verb', () => {
    // The verb is per CATEGORY (upstream `CATEGORY_COPY[toolCategory(name)].present`),
    // so a Pulse tool never inherits a Hermes-only label.
    expect(toolPresentVerb('run_terminal')).toMatch(/running/i);
    expect(toolPresentVerb('execute_code')).toMatch(/running/i);
    expect(toolPresentVerb('read_file')).toMatch(/exploring/i);
    expect(toolPresentVerb('write_file')).toMatch(/editing/i);
    expect(toolPresentVerb('search_code')).toMatch(/exploring/i);
  });
});

describe('render budget: priced by what mounts, not by payload', () => {
  const withParts = (parts: PulseMessage['content']) => assistant('m1', parts);

  it('a settled read costs one collapsed row; a diff pays for its lines', () => {
    const collapsed = messagePaintWeight(withParts([tool('read_file', { path: 'a' }, 'x')]).content);
    const diff = messagePaintWeight(
      withParts([tool('edit_file', { path: 'a' }, { inline_diff: '--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new' })]).content
    );

    expect(collapsed).toBe(1);
    expect(diff).toBeGreaterThan(1);
  });

  it('a silent tool costs nothing at all', () => {
    expect(messagePaintWeight([tool('think', {}, {})] as unknown as PulseMessage['content'])).toBe(1);
  });

  it('walks newest-first and keeps whole turns, floored by turn count', () => {
    const groups = groupsFromMessages([
      user('u1', 'do it'),
      assistant('a1', [text('one'.repeat(9000))]),
      user('u2', 'again'),
      assistant('a2', [text('two')]),
    ]);

    expect(groups).toHaveLength(2);
    expect(groups[0]!.kind).toBe('turn');

    // A budget of zero keeps the last group only; MIN_VISIBLE_GROUPS floors it.
    expect(firstVisibleGroupIndex(groups, 0, 0)).toBe(1);
    expect(firstVisibleGroupIndex(groups, 0, 2)).toBe(0);
    expect(firstVisibleGroupIndex(groups, RENDER_BUDGET)).toBe(0);
  });

  it('the live tail is a weight window clamped to [2, 6] groups', () => {
    const groups = groupsFromMessages([user('u1', 'a'), assistant('a1', [text('b')]), user('u2', 'c'), assistant('a2', [text('d')])]);

    expect(liveTailStart(groups, LIVE_TAIL_PARTS)).toBe(0);
    expect(liveTailStart([], LIVE_TAIL_PARTS)).toBe(0);
  });

  it('"show earlier" spends the DOM page before the store window', () => {
    expect(resolveShowEarlierAction(3, false)).toBe('dom');
    expect(resolveShowEarlierAction(0, true)).toBe('window');
    expect(resolveShowEarlierAction(0, false)).toBe('null');
  });
});

describe('turn activity: quiet gaps, not double narration', () => {
  it('signatures change only on visible growth', () => {
    const before = activitySignature([text('hello'), tool('read_file', { path: 'a' }, undefined)]);
    const after = activitySignature([text('hello'), tool('read_file', { path: 'a' }, 'result')]);

    expect(before).not.toBe(after);
    expect(activitySignature([text('hello')])).toBe(activitySignature([text('hello')]));
  });

  it('a run of tools narrates its own wait; a silent tool does not', () => {
    expect(toolNarratesWait([tool('run_terminal', { command: 'ls' }, undefined)] as never)).toBe(true);
    expect(toolNarratesWait([tool('think', {}, undefined)] as never)).toBe(false);
    expect(TURN_QUIET_S).toBe(2);
  });
});

describe('timeline rail', () => {
  it('skips injected process notifications and previews the real prompts', () => {
    const entries = deriveTimelineEntries([
      { id: 'u1', role: 'user', text: 'fix the failing test in src/graphs/chat_graph.py and verify it passes again' },
      { id: 'a1', role: 'assistant', text: 'ok' },
      { id: 'u2', role: 'user', text: '[IMPORTANT: background task finished]' },
      { id: 'u3', role: 'user', text: '   ' },
    ]);

    expect(entries).toHaveLength(1);
    expect(entries[0]!.preview.length).toBeLessThanOrEqual(120);
    expect(entries[0]!.preview).toMatch(/fix the failing test/);
    expect(sameTimelineEntries(entries, entries)).toBe(true);
  });
});

describe('changed-files card', () => {
  it('folds every edit into one row per file, with summed stats', () => {
    const patch = '--- a/src/a.py\n+++ b/src/a.py\n@@ -1,2 +1,2 @@\n-old\n+new\n';
    const files = deriveChangedFiles([
      tool('write_file', { path: '/repo/src/a.py' }, { inline_diff: patch }),
      tool('edit_file', { path: '/repo/src/a.py' }, { inline_diff: patch }),
      tool('read_file', { path: '/repo/src/a.py' }, 'nope'),
    ]);

    expect(files).toHaveLength(1);
    expect(files[0]).toMatchObject({ added: 2, name: 'a.py', path: '/repo/src/a.py', removed: 2 });
  });

  it('ignores running and failed calls: a turn only claims what landed', () => {
    expect(deriveChangedFiles([tool('edit_file', { path: 'a.py' }, undefined)])).toEqual([]);
    expect(deriveChangedFiles([tool('edit_file', { path: 'a.py' }, { error: 'denied' }, { isError: true })])).toEqual([]);
  });

  it('caps the visible rows at about five', () => {
    expect(MAX_CHANGED_FILE_ROWS).toBe(5);
  });
});

describe('diff rendering', () => {
  it('drops git headers and hunk markers, keeps line numbers in order', () => {
    const diff = ['diff --git a/x b/x', 'index 123..456 100644', '--- a/x', '+++ b/x', '@@ -10,2 +10,2 @@', ' ctx', '-old', '+new'].join('\n');

    expect(stripDiffFileHeaders(diff).startsWith('@@')).toBe(true);

    const lines = parseDiff(diff);

    expect(lines.map(line => line.kind)).toEqual(['context', 'remove', 'add']);
    expect(lines[1]).toMatchObject({ kind: 'remove', oldNo: 11 });
    expect(lines[2]).toMatchObject({ kind: 'add', newNo: 11 });
  });

  it('clamps what it paints without touching what gets copied', () => {
    const huge = 'x'.repeat(25_000);
    const clamped = clampForDisplay(huge);

    expect(clamped.length).toBeLessThan(huge.length);
    expect(clamped).toContain('more characters truncated');
    expect(compactPreview('one  two\nthree', 100)).toBe('one two three');
    expect(compactPreview('one  two\nthree', 10)).toBe('one two t…');
  });
});

describe('Pulse transcript normalization', () => {
  it('pairs AG-UI tool results by tool_call_id and leaves a start unresolved', () => {
    const messages = [
      { id: 'u1', role: 'user', content: 'run the tests' },
      {
        id: 'a1',
        role: 'assistant',
        content: 'on it',
        toolCalls: [
          { id: 'call_1', function: { name: 'run_terminal', arguments: '{"command":"pytest -q"}' } },
          { id: 'call_2', function: { name: 'read_file', arguments: '{"path":"src/tests/test_x.py"}' } },
        ],
      },
      { id: 't1', role: 'tool', tool_call_id: 'call_1', content: '{"stdout":"57 passed","exit_code":0}' },
    ];

    const transcript = transcriptFromMessages(messages, { plan: [{ title: 'verify', status: 'running' }] }, true);
    const parts = transcript.messages[1]!.content;
    const first = parts[1] as ToolPart;
    const second = parts[2] as ToolPart;

    expect(first.toolName).toBe('run_terminal');
    expect(first.result).toContain('57 passed');
    expect(second.result).toBeUndefined();
    expect(transcript.run.busy).toBe(true);
    expect(transcript.run.plan[0]).toMatchObject({ status: 'running', title: 'verify' });
  });

  it('replays bridge protocol v2 frames into the same shape', () => {
    let state = emptyTranscript();

    // Exactly what `BridgeServer._project_event` puts on the wire: flat fields,
    // `tool_id` / `name` / `arguments` / `status` / `result` at the top level.
    state = reducePulseEvent(state, { type: 'turn_started', turn_id: 't1', session_id: 's1', timestamp: 1000 });
    state = reducePulseEvent(state, { type: 'token', text: 'Reading ' });
    state = reducePulseEvent(state, { type: 'token', text: 'the file' });
    state = reducePulseEvent(state, { type: 'tool_call_start', tool_id: 'c1', name: 'read_file', arguments: { path: 'a.py' } });
    state = reducePulseEvent(state, { type: 'tool_call_end', tool_id: 'c1', name: 'read_file', status: 'completed', result: { content: '1|code' } });
    state = reducePulseEvent(state, { type: 'plan_updated', goal: 'fix it', steps: [{ title: 'reproduce', status: 'done' }] });
    state = reducePulseEvent(state, { type: 'verification_updated', checks: [{ title: 'pytest', status: 'passed' }] });
    state = reducePulseEvent(state, { type: 'turn_done' });

    const message = state.messages[0]!;

    expect(message.id).toBe('t1');
    expect((message.content[0] as { text: string }).text).toBe('Reading the file');
    const call = message.content[1] as ToolPart;

    expect(call.toolName).toBe('read_file');
    expect(call.toolCallId).toBe('c1');
    expect(call.result).toEqual({ content: '1|code' });
    expect(state.run.busy).toBe(false);
    expect(state.run.planGoal).toBe('fix it');
    expect(state.run.verification).toEqual([{ detail: '', status: 'passed', title: 'pytest' }]);
  });

  it('reads Pulse approval keys and drops the request when it resolves', () => {
    let state = reducePulseEvent(emptyTranscript(), {
      type: 'safety_request',
      tool_id: 'call_9',
      session_id: 's1',
      name: 'write_file',
      arguments: { path: 'src/a.py', content: 'x' },
      diff: { path: 'src/a.py', patch: '--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b' },
      warning: 'Writes outside the workspace need approval',
    });

    expect(state.approvals[0]).toMatchObject({
      reason: 'Writes outside the workspace need approval',
      toolCallId: 'call_9',
      toolName: 'write_file',
    });
    expect(state.approvals[0]!.diff?.patch).toContain('+++ b');

    state = reducePulseEvent(state, { type: 'safety_resolved', tool_id: 'call_9' });
    expect(state.approvals).toEqual([]);
  });

  it('reports a failed turn honestly instead of as a finished answer', () => {
    let state = reducePulseEvent(emptyTranscript(), { type: 'turn_started' });

    state = reducePulseEvent(state, { type: 'turn_failed', payload: { error: 'provider timeout' } });

    expect(state.messages[0]!.failure).toBe('provider timeout');
    expect(state.run.busy).toBe(false);
  });

  it('ignores frames it does not know — the protocol is additive', () => {
    const state = emptyTranscript();

    expect(reducePulseEvent(state, { type: 'brand_new_event', payload: {} })).toBe(state);
    expect(reducePulseEvent(state, { type: 'telemetry', tokens: 12 })).toBe(state);
  });
});

describe('the ported transcript paints', () => {
  const transcript = (): PulseTranscript => ({
    approvals: [],
    messages: [
      user('u1', 'add the guard and re-run the suite'),
      assistant('a1', [
        text('I will read the graph first.'),
        tool('read_file', { path: 'src/graphs/chat_graph.py' }, { content: '1|def _guard():\n2|    ...' }),
        tool('search_code', { query: 'approval_queue' }, { results: [{ title: 'chat_graph', snippet: 'approval_queue.request(', url: 'https://example.test/a' }] }),
        tool('edit_file', { path: 'src/graphs/chat_graph.py' }, {
          inline_diff: '--- a/src/graphs/chat_graph.py\n+++ b/src/graphs/chat_graph.py\n@@ -1,1 +1,2 @@\n-def _guard():\n+def _guard():\n+    return True',
        }),
        tool('run_terminal', { command: 'pytest src/tests -q' }, { stdout: '1133 passed', stderr: '', exit_code: 0 }),
      ]),
    ],
    run: { busy: false, model: 'qwen3.6-27b', plan: [{ detail: '', status: 'done', title: 'add guard' }], provider: 'custom', subagents: [], turnStartedAt: 1, verification: [{ detail: '1133 passed', status: 'passed', title: 'pytest' }] },
  });

  const signals = { busy: false, turnStartedAt: 1 };

  it('renders user + assistant turns, the edit diff, and the run summary', () => {
    const { container } = render(<PulseAgentThread signals={signals} transcript={transcript()} />);

    expect(screen.getByText('add the guard and re-run the suite')).toBeTruthy();
    expect(container.querySelector('[data-tool-group]')).toBeTruthy();
    expect(container.querySelector('[data-file-edit]')).toBeTruthy();

    const added = [...container.querySelectorAll('.pulse-diff-line--add')].map(node => node.textContent);

    expect(added).toEqual(['def _guard():', '    return True']);
    expect(container.querySelector('.pulse-diff-line--remove')?.textContent).toBe('def _guard():');

    // The command run collapsed into a summary line, not two tool cards.
    const summary = container.querySelector('[data-tool-summary]');

    expect(summary?.textContent).toMatch(/ran 1 command|Explored/i);

    // ...and the card it belongs to still exists as one row.
    expect(container.querySelectorAll('[data-tool-row]').length).toBeGreaterThanOrEqual(2);
  });

  it('mounts the command, exit code and stdout when a row is expanded', () => {
    const part = tool('run_terminal', { command: 'pytest -q' }, { stdout: '57 passed in 0.24s', stderr: '', exit_code: 1 }, { toolCallId: 'x' });
    const { container } = render(<PulseToolRow messageRunning={false} messageId="a1" part={part} />);

    // Collapsed by default: the payload stays behind the disclosure.
    expect(container.querySelector('.pulse-terminal-transcript')).toBeNull();

    fireEvent.click(screen.getByRole('button', { expanded: false }));

    expect(container.querySelector('.pulse-terminal-transcript__command')?.textContent).toContain('pytest -q');
    // `exit 1` is painted through StableText (one 1ch cell per character, so a
    // changing digit cannot shift the layout) — assert the cell run, not a text
    // match, which is exactly why the fork reads it as one string.
    expect(container.querySelector('.pulse-terminal-transcript__exit')?.textContent).toBe('exit 1');
    expect(container.querySelectorAll('.pulse-stable-text__cell').length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText('57 passed in 0.24s')).toBeTruthy();
    // An empty stderr stream invents no block.
    expect([...container.querySelectorAll('.pulse-tool-section-label')].map(node => node.textContent)).not.toContain('stderr');
  });

  it('hides a completed file edit with no diff to review', () => {
    const { container } = render(<PulseToolRow messageRunning={false} messageId="a1" part={tool('write_file', { path: 'a.py' }, { ok: true })} />);

    expect(container.firstChild).toBeNull();
  });

  it('keeps a failed edit visible — errors are debuggable, never swallowed', () => {
    const { container } = render(
      <PulseToolRow
        messageRunning={false}
        messageId="a1"
        part={tool('write_file', { path: 'a.py' }, { error: 'path escapes workspace' }, { isError: true })}
      />
    );

    expect(container.querySelector('[data-tool-row]')).toBeTruthy();
    expect(container.querySelector('.pulse-tool-title--error')).toBeTruthy();
  });

  it('persists disclosure state across unmount, keyed per message', () => {
    const part = tool('read_file', { path: 'a.py' }, { content: '1|x' }, { toolCallId: 'persist-1' });
    const first = render(<PulseToolRow messageRunning={false} messageId="a1" part={part} />);

    fireEvent.click(screen.getByRole('button', { expanded: false }));
    first.unmount();

    const second = render(<PulseToolRow messageRunning={false} messageId="a1" part={part} />);

    expect(second.container.querySelector('[data-tool-open]')).toBeTruthy();

    // ...and a different message keeps its own answer.
    const third = render(<PulseToolRow messageRunning={false} messageId="a2" part={part} />);

    expect(third.container.querySelector('[data-tool-open]')).toBeNull();
  });

  it('shows the plan/verification ledger a turn finished with', () => {
    const { container } = render(<PulseAgentThread signals={signals} transcript={transcript()} />);
    const panel = container.querySelector('[data-slot="pulse-run-status"]');

    expect(panel).toBeTruthy();
    expect(within(panel as HTMLElement).getByText('add guard')).toBeTruthy();
    expect(within(panel as HTMLElement).getByText('pytest')).toBeTruthy();
  });

  it('closes a turn that changed files with the files-changed card', () => {
    const { container } = render(<PulseAgentThread signals={signals} transcript={transcript()} />);
    const card = container.querySelector('[data-slot="aui_changed-files"]');

    expect(card).toBeTruthy();
    expect(within(card as HTMLElement).getByText('1 file changed')).toBeTruthy();
    expect(within(card as HTMLElement).getByText('chat_graph.py')).toBeTruthy();
  });

  it('pages the transcript without ever dropping below the floor', () => {
    const many: PulseMessage[] = [];

    for (let i = 0; i < 30; i += 1) {
      many.push(user(`u${i}`, `prompt ${i}`));
      many.push(assistant(`a${i}`, [text(`answer ${i}`.repeat(400))]));
    }

    const { container } = render(<PulseAgentThread signals={signals} transcript={{ approvals: [], messages: many, run: { busy: false, plan: [], subagents: [] } }} />);
    const button = container.querySelector('.pulse-thread__show-earlier');

    expect(button).toBeTruthy();

    const renderedBefore = container.querySelectorAll('[data-turn-id]').length;

    act(() => {
      fireEvent.click(button as HTMLElement);
    });

    expect(container.querySelectorAll('[data-turn-id]').length).toBeGreaterThanOrEqual(renderedBefore);
  });

  it('shows a designed empty state instead of a blank pane', () => {
    render(<PulseAgentThread signals={{ busy: false }} transcript={emptyTranscript()} />);

    expect(screen.getByText(/Pulse is ready/)).toBeTruthy();
  });

  it('renders the composer affordances Pulse actually supports', () => {
    const submitted: string[] = [];

    render(<PulseComposer onSubmit={value => submitted.push(value)} signals={{ busy: false }} />);

    const box = screen.getByRole('textbox', { name: 'Message Pulse' });

    fireEvent.change(box, { target: { value: '  ' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(submitted).toEqual([]);

    fireEvent.change(box, { target: { value: 'run the suite' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(submitted).toEqual(['run the suite']);
  });
});

describe('approval: Pulse\'s real decision contract', () => {
  const approval = {
    args: { command: 'rm -rf build' },
    reason: 'Destructive command outside the worktree',
    toolCallId: 'call_42',
    toolName: 'run_terminal',
  };

  it('gates on the tools Pulse actually guards', () => {
    expect(APPROVAL_TOOLS.has('run_terminal')).toBe(true);
    expect(APPROVAL_TOOLS.has('write_file')).toBe(true);
    expect(APPROVAL_TOOLS.has('read_file')).toBe(false);
    expect(approvalBlocksTool(approval, 'run_terminal', 'call_42')).toBe(true);
    expect(approvalBlocksTool(approval, 'run_terminal', 'other')).toBe(false);
    expect(approvalBlocksTool(undefined, 'run_terminal')).toBe(false);
    expect(commandFromArgs(approval.args)).toBe('rm -rf build');
  });

  it('renders Run / Allow-for-session / Reject and answers with the bridge frame', () => {
    const decisions: string[] = [];

    render(
      <div>
        <PulseAgentThread
          approvalRespond={choice => decisions.push(choice)}
          signals={{ awaitingInput: true, busy: true, turnStartedAt: 1 }}
          transcript={{
            approvals: [approval],
            messages: [
              user('u1', 'clean the build dir'),
              assistant('a1', [tool('run_terminal', { command: 'rm -rf build' }, undefined, { toolCallId: 'call_42' })]),
            ],
            run: { busy: true, plan: [], subagents: [] },
          }}
        />
      </div>
    );

    const bar = screen.getByRole('group');

    expect(within(bar).getByText('Destructive command outside the worktree')).toBeTruthy();

    fireEvent.click(within(bar).getByRole('button', { name: /^Run/ }));
    expect(decisions).toEqual(['once']);

    // ⌘/Ctrl+Enter and Esc are the keyboard path, same as upstream.
    fireEvent.keyDown(window, { ctrlKey: true, key: 'Enter' });
    expect(decisions).toContain('once');
  });

  it('a blocked run stops collapsing into the ticker', () => {
    const tools = [
      tool('read_file', { path: 'a' }, 'x', { toolCallId: 'r1' }),
      tool('run_terminal', { command: 'rm -rf build' }, undefined, { toolCallId: 'call_42' }),
    ];
    const run = computeToolRun(tools, true, 'a1');

    expect(run.live).toBe(true);
    expect(run.pendingApprovalTool).toBe(true);
  });

  it('names compaction as the wait that outranks every other hint', () => {
    expect(COMPACTION_LABEL).toBe('Summarizing thread');
  });
});

describe('branding: Pulse only, in everything the user can see', () => {
  const root = join(__dirname, '..', 'hermes-ui');

  const sources = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
      const path = join(dir, entry.name);

      return entry.isDirectory() ? sources(path) : path.endsWith('.css') || /\.tsx?$/.test(entry.name) ? [path] : [];
    });

  /** Strip comments and import/export specifiers: provenance comments and file
   *  paths are for engineers, and the rule is about what the UI SAYS. */
  const visibleCode = (source: string) =>
    source
      .replace(/\/\*[\s\S]*?\*\//g, ' ')
      .replace(/^\s*\/\/.*$/gm, ' ')
      .replace(/\bfrom\s+'[^']*'/g, "from 'x'")
      .replace(/\bimport\s*\([^)]*\)/g, 'import()');

  it('no upstream vendor token survives outside provenance comments', () => {
    const offenders = sources(root)
      .map(path => ({ path, text: visibleCode(readFileSync(path, 'utf8')) }))
      .filter(entry => /hermes|nous|anthropic|openai|grok|gemini/i.test(entry.text))
      .map(entry => entry.path.slice(root.length + 1));

    expect(offenders).toEqual([]);
  });

  it('a rendered transcript never names the upstream vendor', () => {
    const { container } = render(
      <PulseAgentThread
        signals={{ busy: true, turnStartedAt: 1 }}
        transcript={{
          approvals: [{ args: { command: 'ls' }, reason: 'guarded', toolCallId: 'c', toolName: 'run_terminal' }],
          messages: [user('u1', 'go'), assistant('a1', [text('done'), tool('run_terminal', { command: 'ls' }, { stdout: 'ok', exit_code: 0 })])],
          run: { busy: true, plan: [{ detail: '', status: 'running', title: 'verify' }], subagents: [] },
        }}
      />
    );

    expect(container.textContent).not.toMatch(/hermes|nous/i);
    expect(container.textContent).toContain('done');
  });
});
