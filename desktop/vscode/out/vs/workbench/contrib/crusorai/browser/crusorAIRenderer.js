/*---------------------------------------------------------------------------------------------
 * Framework-neutral, editor-native Crusor renderer. Both first-party workbench hosts mount this
 * module; no Electron, Node, or Code OSS service is imported across this boundary.
 *--------------------------------------------------------------------------------------------*/
import { reasoningEffortLabel } from '../common/crusorAIReasoningEffort.js';
import { separateGluedReasoningBlocks } from './crusorAIReasoningBlocks.js';
import { openHubDialog } from './crusorAIHubDialog.js';
import { crusorSessionIdFromUri } from '../common/crusorAISessionProjection.js';
import { crusorAIToolPresentation } from '../common/crusorAIToolCatalog.js';
import { deriveChangedFiles, hasAnsiCodes, parseAnsi, parseDiff, stripTerminalEnvelope, windowedTailLines } from './crusoraiCardFormat.js';
import { compactTarget, splitRunGroups, summarizeToolRun, toolPresentVerb } from './crusorAIRunSummary.js';
import { renderA2UIToolBody } from './crusorA2UISurface.js';
import { renderToolIcon } from './crusorAIIcons.js';
import { activityParts, activityRowMode, activitySignature, closeMeasurement, draftingToolName, elapsedFor, measuredDuration, DRAFTING_REVEAL_MS, statusHintLabel, toolNarratesWait, TURN_QUIET_S, UNNAMED_WAIT_LABEL, } from './crusorAIActivity.js';
function element(tag, className, ...children) {
    const node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    for (const child of children) {
        if (typeof child === 'string') {
            node.append(document.createTextNode(child));
        }
        else if (child) {
            node.append(child);
        }
    }
    return node;
}
/**
 * A row glyph. Hermes draws solid SVG for the names `crusorAIIcons.ts` covers and the outline
 * codicon font for everything else, because a font glyph has no fillable region -- the same
 * rule, keyed by the same names, so a row here shows the glyph the webview resolves.
 */
function icon(name) {
    return renderToolIcon(name);
}
/**
 * The workbench's real file-type icon for a path: a span carrying the
 * active file icon theme's classes (host-provided `getIconClasses`
 * output). The theme's injected CSS paints `::before` when an ancestor
 * carries `.show-file-icons` — the same contract the Explorer uses, so
 * `AGENTS.md`, `package.json` and `page.tsx` each get THEIR icon.
 */
function fileIcon(host, resource) {
    const span = element('span', 'crusorai-file-icon');
    span.className = `crusorai-file-icon ${host.fileIconClasses?.(resource) ?? 'file-icon'}`;
    return span;
}
// ---------------------------------------------------------------------------
// Minimal markdown rendering for the transcript (pure DOM, zero deps).
// The panel used to print assistant text as one plain text node, so every
// legitimate markdown line -- the model's "###" headers, the finalize stamp's
// bullets and sign-offs -- leaked as literal hash/asterisk soup. This renders
// the small dialect we actually emit (headings, bullets, hr, fenced code,
// bold/italic/inline-code) using element()/createTextNode ONLY -- never
// innerHTML -- so nothing the model sends can inject markup. Anything outside
// the dialect renders as plain text, which is the honest fallback.
// ---------------------------------------------------------------------------
function mdInline(target, text) {
    for (const part of text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|<https?:\/\/[^>\s]+>)/)) {
        if (!part) {
            continue;
        }
        const linkMd = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part);
        if (linkMd) {
            const a = element('a', 'crusorai-md-link', linkMd[1]);
            a.href = linkMd[2];
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            target.append(a);
            continue;
        }
        if (/^<https?:\/\/[^>\s]+>$/.test(part)) {
            const url = part.slice(1, -1);
            const a = element('a', 'crusorai-md-link', url);
            a.href = url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            target.append(a);
            continue;
        }
        if (!part) {
            continue;
        }
        if (part.length > 4 && part.indexOf('**') === 0 && part.lastIndexOf('**') === part.length - 2) {
            target.append(element('strong', undefined, part.slice(2, -2)));
        }
        else if (part.length > 2 && part.charCodeAt(0) === 96 && part.charCodeAt(part.length - 1) === 96) {
            target.append(element('code', 'crusorai-md-code', part.slice(1, -1)));
        }
        else if (part.length > 2 && part.indexOf('*') === 0 && part.lastIndexOf('*') === part.length - 1) {
            target.append(element('em', undefined, part.slice(1, -1)));
        }
        else {
            target.append(element('span', undefined, part));
        }
    }
}
// Some endpoint models leak their NATIVE tool-call dialect into CONTENT
// instead of emitting API tool_calls (field 2026-09-07 1:34 PM:
// <dots_function_call><exec><command>... painted as chat prose). The engine
// correctly declines to execute unparseable text; the renderer's job is to
// not PAINT it as the agent's voice. Hermes' equivalents are the toolset
// availability paint and the unverified verdict — the raw dialect itself is
// model-specific, so it is shown collapsed and labeled, never parsed.
// Two model dialects land as raw text: XML-ish tool tags and (field
// 2026-09-10, the grace summary) single-line JSON objects keyed by
// "action"/"tool" — the model kept "calling" tools textually after the
// toolless summary request. Both collapse into the labeled disclosure
// instead of painting raw JSON into the answer.
const RAW_TOOL_MARKUP = /^\s*(?:<\/?\s*(?:dots_function_call|exec|invoke|command|tool_call|function_call)\b|\{\s*"(?:action|tool|tool_call|function)"\s*:)/i;
// Workbench freshness stamp — bump with EVERY workbench UI round. The engine
// chip proves the PYTHON engine only; field round 2026-09-08 ran engine
// de0dbbae on a base-era compiled workbench (lab-era browser cards, reveal-
// URL ERRs) and nothing on screen could tell. This constant lives in this
// source file, so any compile of current source carries it while a stale
// out/ shows an older date; engineStatus() flags engine-newer skew as STALE.
const CRUSORAI_UI_STAMP = '2026-10-15';
function markdownCopy(text, slot) {
    const root = element('div', 'crusorai-assistant-copy crusorai-md');
    if (slot) {
        root.dataset.slot = slot;
    }
    let list = null;
    let code = null;
    // Consecutive raw tool-markup lines collapse into ONE labeled disclosure.
    // They are buffered and flushed on the next non-markup line (or at the
    // end of the text) — the old loop-carried rawBlock/rawPre pair hit a TS
    // circular-narrowing error (append on never) AND could crash at runtime
    // on a consecutive markup line (stale pre reference).
    const rawLines = [];
    const flushRawMarkup = () => {
        if (!rawLines.length) {
            return;
        }
        const details = element('details', 'crusorai-raw-call');
        details.append(element('summary', undefined, 'Unparsed tool-call markup (model dialect, not executed)'));
        const pre = element('pre', 'crusorai-raw-call-pre');
        pre.append(document.createTextNode(`${rawLines.join('\n')}\n`));
        details.append(pre);
        root.append(details);
        rawLines.length = 0;
        list = null;
    };
    for (const raw of text.split(/\r?\n/)) {
        const line = raw.replace(/\s+$/, '');
        if (code) {
            if (line.trim() === '```') {
                code = null;
            }
            else {
                code.append(document.createTextNode(raw + '\n'));
            }
            continue;
        }
        if (RAW_TOOL_MARKUP.test(line)) {
            rawLines.push(raw);
            continue;
        }
        flushRawMarkup();
        if (line.trim() === '```') {
            code = element('pre', 'crusorai-md-pre');
            root.append(code);
            continue;
        }
        const heading = /^(#{1,6})\s+(.*)$/.exec(line);
        if (heading) {
            list = null;
            const h = element('div', `crusorai-md-h crusorai-md-h${heading[1].length}`);
            mdInline(h, heading[2]);
            root.append(h);
            continue;
        }
        if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
            list = null;
            root.append(element('hr', 'crusorai-md-hr'));
            continue;
        }
        const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
        if (bullet) {
            if (!list || list.tagName !== 'UL') {
                list = element('ul', 'crusorai-md-ul');
                root.append(list);
            }
            const li = element('li');
            mdInline(li, bullet[1]);
            list.append(li);
            continue;
        }
        const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
        if (ordered) {
            // hermes markdown-text: ordered lists keep their own element so a
            // numbered "1. 2. 3." answer doesn't collapse into one paragraph.
            if (!list || list.tagName !== 'OL') {
                list = element('ol', 'crusorai-md-ol');
                root.append(list);
            }
            const li = element('li');
            mdInline(li, ordered[1]);
            list.append(li);
            continue;
        }
        const quote = /^>\s?(.*)$/.exec(line);
        if (quote) {
            // hermes compact-markdown: a quote is its own quiet block.
            list = null;
            const q = element('blockquote', 'crusorai-md-quote');
            mdInline(q, quote[1]);
            root.append(q);
            continue;
        }
        if (/^\s*\|.*\|\s*$/.test(line) && line.includes('|', 1)) {
            // hermes markdown-table: a pipe-table body renders as a real table.
            const cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
            if (cells.every(c => /^:?-{2,}:?$/.test(c))) {
                continue;
            } // separator row
            let table = root.querySelector('table.crusorai-md-table:last-of-type');
            if (!table || table.dataset.closed === 'true') {
                table = element('table', 'crusorai-md-table');
                table.dataset.closed = 'false';
                root.append(table);
            }
            const tr = element('tr');
            const kind = table.rows.length === 0 ? 'th' : 'td';
            for (const cell of cells) {
                const td = element(kind);
                mdInline(td, cell);
                tr.append(td);
            }
            table.append(tr);
            continue;
        }
        if (!line.trim()) {
            list = null;
            // a blank line closes an open table (hermes table scope)
            for (const t of root.querySelectorAll('table.crusorai-md-table')) {
                t.dataset.closed = 'true';
            }
            continue;
        }
        list = null;
        const para = element('div', 'crusorai-md-p');
        mdInline(para, line);
        root.append(para);
    }
    flushRawMarkup();
    return root;
}
// Hermes-pattern message action: a quiet Copy control under each completed
// answer -- the "Run completed" green check told the user what they had just
// watched happen; a copy button does something they actually want. Clipboard
// write never throws into the panel (best-effort), and the label flashes
// Copied so the click is confirmed without a dialog.
// Hermes port (components/chat/activity-timer.ts): seconds tick on a 1s
// heartbeat WITHOUT re-rendering the panel -- the ticker surgically updates
// only .crusorai-elapsed nodes in place, so a full transcript rebuild (which
// would reset scroll and disclosure state) never happens on a clock tick.
function formatElapsedSeconds(seconds) {
    return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
let elapsedTicker;
function elapsedSpan(originMs) {
    const span = element('span', 'crusorai-scaffold-meta crusorai-elapsed');
    const origin = typeof originMs === 'number' && originMs > 0 ? originMs : Date.now();
    datasetSet(span, 'origin', String(origin));
    span.textContent = formatElapsedSeconds(Math.max(0, Math.floor((Date.now() - origin) / 1000)));
    if (elapsedTicker === undefined) {
        elapsedTicker = window.setInterval(() => {
            for (const node of document.querySelectorAll('span.crusorai-elapsed')) {
                const nodeOrigin = Number(node.dataset.origin || '0');
                if (nodeOrigin > 0) {
                    node.textContent = formatElapsedSeconds(Math.max(0, Math.floor((Date.now() - nodeOrigin) / 1000)));
                }
            }
        }, 1000);
    }
    return span;
}
function datasetSet(node, key, value) {
    node.dataset[key] = value;
}
function copyButton(text, host) {
    // Hermes port (ui/copy-button.tsx): an ICON action, not a text line --
    // copy glyph, tooltip title, 1.5s check-flash on success, error state on
    // denial. With a host, clipboard goes through the workbench service
    // (navigator.clipboard is permission-blocked in the webview — field
    // proof); without one, the async-API fallback path.
    const btn = element('button', 'crusorai-icon-action');
    btn.type = 'button';
    btn.title = 'Copy';
    btn.setAttribute('aria-label', 'Copy');
    btn.append(icon('copy'));
    const reset = () => {
        btn.replaceChildren(icon('copy'));
        btn.title = 'Copy';
    };
    const flash = () => {
        btn.replaceChildren(icon('check'));
        btn.title = 'Copied';
        setTimeout(reset, 1500);
    };
    const fail = () => {
        btn.replaceChildren(icon('error'));
        btn.title = 'Copy failed';
        setTimeout(reset, 1500);
    };
    btn.addEventListener('click', () => {
        if (host) {
            try {
                host.copyToClipboard(text);
                flash();
            }
            catch {
                fail();
            }
            return;
        }
        try {
            void copyTextToClipboard(text).then(flash, fail);
        }
        catch {
            fail();
        }
    });
    return btn;
}
function button(label, className, action, iconName) {
    const node = element('button', className, iconName ? icon(iconName) : undefined, label);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
}
// Webview clipboard can be permission-blocked (field: NotAllowedError on
// writeText). Degrade honestly: async API first, hidden-textarea fallback,
// real failure surfaced by the caller's UI either way.
function copyTextToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        return navigator.clipboard.writeText(text).catch(() => copyViaExecCommand(text));
    }
    return new Promise((resolve) => { copyViaExecCommand(text); resolve(); });
}
function copyViaExecCommand(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.append(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
    }
    finally {
        textarea.remove();
    }
}
function record(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : undefined;
}
function firstString(source, keys) {
    const value = record(source);
    for (const key of keys) {
        if (typeof value?.[key] === 'string' && value[key]) {
            return value[key];
        }
        if (typeof value?.[key] === 'number') {
            return String(value[key]);
        }
    }
    return undefined;
}
function resultRecord(value) {
    // The tool_call_end frame carries `result` RAW (bridge _project_event):
    // structured tools ship json.dumps envelopes as strings, other paths may
    // deliver parsed objects. Cards read keys off the parsed shape — without
    // this, navigate/console/click render em-dashes even on a healthy run.
    if (typeof value === 'string') {
        try {
            return record(JSON.parse(value));
        }
        catch {
            return undefined;
        }
    }
    return record(value);
}
function displayTarget(tool) {
    return firstString(tool.arguments, ['path', 'file_path', 'resource', 'command', 'query', 'url', 'goal', 'target']) ?? tool.name;
}
function boundedText(value, max = 12_000) {
    let text;
    if (typeof value === 'string') {
        text = value;
    }
    else {
        try {
            text = JSON.stringify(value ?? {}, undefined, 2);
        }
        catch {
            text = String(value);
        }
    }
    if (text.length <= max) {
        return text;
    }
    return `... ${text.length - max} earlier characters omitted ...\n${text.slice(-max)}`;
}
function resultOutput(tool) {
    const value = record(tool.result);
    const parts = [value?.output, value?.stdout, value?.stderr].filter(part => typeof part === 'string' && part.length > 0);
    return boundedText(parts.length ? parts.join(parts.length > 1 ? '\n' : '') : tool.result);
}
function stateLabel(state) {
    if (state === 'passed') {
        return 'Passed';
    }
    if (state === 'failed') {
        return 'Failed';
    }
    if (state === 'approval') {
        return 'Approval';
    }
    if (state === 'running') {
        return 'Running';
    }
    return 'Queued';
}
function statusGlyph(state) {
    if (state === 'running') {
        return element('span', 'crusorai-mini-spinner');
    }
    const name = state === 'passed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'approval' ? 'shield' : 'circle-outline';
    return icon(name);
}
function labeledPayload(label, value) {
    return element('div', 'crusorai-tool-field', element('span', 'crusorai-tool-field-label', label), element('pre', 'crusorai-tool-pre', boundedText(value)));
}
// Hermes port (components/chat/expandable-block.tsx): cap a collapsed output
// block at 7.5rem with a bottom fade + one chevron; expanded caps at 40dvh and
// scrolls. Measured on the next frame so short output carries no chrome at all
// (their ResizeObserver discipline: never a sync scrollHeight read per mount).
function expandableOutput(content) {
    const wrap = element('div', 'crusorai-expandable is-collapsed');
    const clip = element('div', 'crusorai-expandable-clip', content);
    const toggle = element('button', 'crusorai-expandable-toggle', icon('chevron-down'));
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Expand output');
    toggle.addEventListener('click', () => {
        const collapsed = wrap.classList.toggle('is-collapsed');
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
    const fade = element('div', 'crusorai-expandable-fade', toggle);
    wrap.append(clip, fade);
    window.requestAnimationFrame(() => {
        if (clip.scrollHeight <= 121) {
            wrap.classList.remove('is-collapsed');
            wrap.classList.add('is-fits');
        }
        // Hermes terminal-output.tsx: jump straight to the LATEST output
        // on first delivery — boundedText keeps the tail, so the end of
        // the stream is the payload (dir listings end at the current
        // entries). First delivery only; a later resize must not yank
        // the user while they scroll up reading earlier output.
        const pre = clip.querySelector('.crusorai-terminal-output');
        if (pre && !pre.dataset.tailed && pre.scrollHeight > pre.clientHeight) {
            pre.dataset.tailed = 'true';
            pre.scrollTop = pre.scrollHeight;
        }
    });
    return wrap;
}
// hermes status-row.tsx todo glyphs, ported: pending = dashed ring,
// in_progress = live dot, completed = pass-filled, failed = error,
// cancelled = circle-slash. Rows speak the WRITTEN list, never arg JSON.
//
// User disclosure choices survive re-renders — the same law toolRow's
// openTools set serves one level up, here keyed by the owning tool id.
const openPlanLists = new Set();
// Per-tool tail-follow choices for streaming shell output (see terminalBody):
// true/absent = follow the newest line; false = the user scrolled up to read.
const bashFollow = new Map();
// hermes DESKTOP status stack (apps/desktop composer/status-stack +
// components/chat/status-section.tsx) — NOT the TUI TodoPanel. The desktop
// chrome: chevron-right caret (rotates 90deg open, 150ms), the `checklist`
// codicon, the en.ts label `Tasks ${done}/${total}`, the todo group is the
// ONLY group expanded by default (defaultCollapse = type !== 'todo'), and a
// spinner rides the header while an item is in_progress/running (hidden
// once open, pure CSS). Rows keep the status-row glyph grammar.
function planListBody(tool, result, args) {
    const rows = planStepsFrom(result, args);
    if (!rows.length) {
        const empty = element('div', 'crusorai-plan-list');
        empty.append(element('div', 'crusorai-plan-empty', 'No task list written'));
        return empty;
    }
    const done = rows.filter(s => s.status === 'completed').length;
    const running = rows.some(s => s.status === 'in_progress');
    const details = element('details', 'crusorai-plan-details');
    // Desktop defaultCollapse: the todo group is expanded by default; the
    // user's toggle wins and survives re-renders (openPlanLists).
    details.open = !openPlanLists.has(tool.id);
    details.addEventListener('toggle', () => details.open ? openPlanLists.delete(tool.id) : openPlanLists.add(tool.id));
    details.append(element('summary', 'crusorai-plan-head', element('span', 'crusorai-plan-caret', icon('chevron-right')), element('span', 'crusorai-plan-icon', icon('checklist')), element('span', 'crusorai-plan-title', `Tasks ${done}/${rows.length}`), running ? element('span', 'crusorai-mini-spinner crusorai-plan-spinner') : undefined));
    const wrap = element('div', 'crusorai-plan-list crusorai-todos');
    for (const step of rows) {
        const status = step.status;
        const row = element('div', `crusorai-plan-row is-${status}`);
        const glyph = element('span', 'crusorai-plan-glyph');
        if (status === 'completed') {
            glyph.append(icon('pass-filled'));
        }
        else if (status === 'failed') {
            glyph.append(icon('error'));
        }
        else if (status === 'cancelled') {
            glyph.append(icon('circle-slash'));
        }
        // pending (dashed ring) and in_progress (live dot) are pure CSS
        row.append(glyph, element('span', 'crusorai-plan-text', step.description));
        wrap.append(row);
    }
    details.append(wrap);
    return details;
}
function planStepsFrom(result, args) {
    const raw = (result && planStepsOf(result, 'steps'))
        ?? planStepsOf(result, 'todos')
        ?? planStepsOf(args, 'steps')
        ?? planStepsOf(args, 'todos')
        ?? [];
    const rows = [];
    for (const item of raw) {
        if (!item || typeof item !== 'object') {
            continue;
        }
        const rec = item;
        const description = String(rec.description ?? rec.content ?? '').trim();
        // hermes items are id-keyed; an id-only row (schema-forbidden but
        // seen in the field) reads as "Item <id>", never "(no description)".
        if (!description) {
            const id = String(rec.id ?? '').trim();
            if (!id) {
                continue;
            }
            rows.push({ description: `Item ${id}`, status: String(rec.status ?? 'pending') });
            continue;
        }
        rows.push({ description, status: String(rec.status ?? 'pending') });
    }
    return rows;
}
function planStepsOf(source, key) {
    if (!source) {
        return undefined;
    }
    let raw = source[key];
    if (typeof raw === 'string') {
        try {
            raw = JSON.parse(raw);
        }
        catch {
            return undefined;
        }
    }
    return Array.isArray(raw) ? raw : undefined;
}
function terminalBody(tool, host) {
    const args = record(tool.arguments);
    const result = resultRecord(tool.result);
    const command = firstString(args, ['command', 'script']) ?? 'Command details unavailable';
    // The engine wraps terminal results in a STDOUT:/STDERR: envelope; hermes'
    // card shows the raw output. The Exit-code trailer is parsed from the RAW
    // text above (exitSource) before this strip.
    const output = stripTerminalEnvelope(resultOutput(tool));
    const exitSource = typeof tool.result === 'string' ? tool.result : '';
    let exit = firstString(result, ['exitCode', 'exit_code', 'status', 'code']);
    if (exit === undefined && exitSource) {
        // run_terminal appends "Exit code: N" as the last line of its envelope
        // (and the output cap keeps the tail), so the real exit code is
        // recoverable even when the result is a plain string. Timeout
        // envelopes carry their own marker instead.
        const sentinel = /Exit code: (-?\d+)\s*$/.exec(exitSource);
        if (sentinel) {
            exit = sentinel[1];
        }
        else if (exitSource.includes('terminal timed out') || exitSource.includes('run_terminal timed out')) {
            exit = 'timeout';
        }
    }
    exit ??= (tool.state === 'running' ? 'running' : 'unknown');
    const body = element('div', 'crusorai-tool-body crusorai-terminal-body');
    // OpenCode bash-output box, copied from the captured reference
    // (third-party/opencode/session-ui/components/message-part.css) and wired
    // to Bridge v2 terminal events: ONE box — command block, then the result
    // block split by a hairline — with the copy control inside the box,
    // revealed on hover. Their --v2-* tokens map to live workbench vars.
    const outputBox = element('div', 'crusorai-bash-output');
    outputBox.dataset.component = 'bash-output';
    outputBox.dataset.variant = 'shell';
    const copyWrap = element('div', 'crusorai-bash-copy');
    copyWrap.dataset.slot = 'bash-copy';
    copyWrap.append(copyButton(command, host));
    const scroll = element('div', 'crusorai-bash-scroll');
    scroll.dataset.slot = 'bash-scroll';
    scroll.dataset.scrollable = '';
    scroll.tabIndex = 0;
    scroll.setAttribute('role', 'region');
    scroll.setAttribute('aria-label', 'Terminal output');
    const pre = element('pre', 'crusorai-bash-pre');
    pre.dataset.slot = 'bash-pre';
    const codeEl = element('code');
    const commandSpan = element('span', 'crusorai-bash-command', command);
    commandSpan.dataset.slot = 'bash-command';
    codeEl.append(commandSpan);
    const resultSpan = element('span', 'crusorai-bash-result');
    resultSpan.dataset.slot = 'bash-result';
    resultSpan.append(terminalOutputContent(output, tool.state === 'running'));
    // Streaming patch target: tool_output chunks rewrite THIS pre in place
    // (see patchLiveToolOutputs) instead of repainting the transcript.
    const outPre = resultSpan.querySelector('pre');
    if (outPre) {
        outPre.dataset.toolOutputFor = tool.id;
    }
    // OpenCode renders the result block only when there IS output —
    // founder 2026-10-15: 'don't show that down box until terminal get
    // single letter of the terminal response'. An untouched tool's
    // result stringifies to "{}" — that is not output either.
    const trimmedOutput = output.trim();
    const hasOutput = trimmedOutput.length > 0 && trimmedOutput !== '{}' && trimmedOutput !== 'null';
    if (hasOutput) {
        codeEl.append(resultSpan);
    }
    pre.append(codeEl);
    scroll.append(pre);
    // Tail-follow (their followShellOutput discipline): follow the newest
    // line until the user scrolls up to read; scrolling back re-engages.
    // The choice survives repaints, keyed by tool id.
    scroll.addEventListener('scroll', () => {
        bashFollow.set(tool.id, scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 40);
    });
    outputBox.append(copyWrap, scroll);
    // Pin to the latest output while following (default on, and always on
    // the first delivery); a user who scrolled up keeps their place.
    window.requestAnimationFrame(() => {
        if (bashFollow.get(tool.id) !== false) {
            scroll.scrollTop = scroll.scrollHeight;
        }
    });
    // OpenCode shell rows say NOTHING on success (no "Passed · exit 0"
    // footer — founder screenshot 2026-10-15: 'terminal looks shit');
    // only a failed/timed-out run earns one quiet exit line, like their
    // SessionShellMessage error. The header glyph already carries state.
    const showExit = exit !== undefined && exit !== '0' && exit !== 'running' && exit !== 'unknown';
    body.append(outputBox);
    if (showExit) {
        body.append(element('div', 'crusorai-terminal-result', element('span', undefined, exit === 'timeout' ? 'Timed out' : `Exit code ${exit}`)));
    }
    const actions = element('div', 'crusorai-tool-actions');
    const cwd = firstString(args, ['cwd', 'path']);
    if (cwd) {
        actions.append(button('Reveal location', 'crusorai-link-button', () => host.revealFile(cwd), 'go-to-file'));
    }
    if (cwd) {
        body.append(actions);
    }
    return body;
}
// OpenCode parity: agent color hash for task cards
function agentColor(name) {
    const palette = ['#0b6bcb', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
    let hash = 0;
    for (let i = 0; i < name.length; i++)
        hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    return palette[hash % palette.length];
}
function taskToolCard(tool, host) {
    const args = record(tool.arguments) ?? {};
    const resultRec = resultRecord(tool.result);
    // Extract from args: description, prompt, subagent_type, mode, background
    const description = firstString(args, ['description', 'goal', 'prompt', 'task']) ?? 'Sub-agent task';
    const agentName = firstString(args, ['subagent_type', 'agent_name', 'mode']) ?? 'general';
    const isBackground = Boolean(args.background ?? resultRec?.background ?? false);
    // sessionId metadata may be in result or tool metadata fields (bridge now emits child_thread_id)
    const childId = firstString(resultRec ?? {}, ['sessionId', 'session_id', 'child_thread_id', 'subagent_id'])
        ?? firstString(args, ['sessionId', 'child_thread_id'])
        ?? resultRec?.child_thread_id
        ?? resultRec?.sessionId;
    const toolCalls = resultRec?.toolCalls ?? resultRec?.tool_calls ?? args.toolCalls;
    const state = tool.state;
    const running = state === 'running' || state === 'queued';
    const card = element('div', 'crusorai-task-tool-card');
    card.dataset.component = 'task-tool-card';
    card.style.setProperty('--task-agent-color', agentColor(agentName));
    // Always clickable — even while sub-agent is still starting (childId not yet in result)
    const navId = childId ?? tool.toolCallId ?? tool.id;
    card.dataset.sessionId = String(navId);
    card.classList.add('is-clickable');
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', `Open sub-agent ${description}`);
    console.log('[CrusorAI] taskToolCard render', { description, agentName, childId, navId, state });
    const navigate = () => {
        console.log('[CrusorAI] taskToolCard click -> navigateToSession', { description, childId, navId, target: childId ?? navId });
        const target = childId ?? navId;
        if (host.navigateToSession && target)
            host.navigateToSession(String(target));
        else
            console.warn('[CrusorAI] navigateToSession not available or no target', { host: !!host.navigateToSession, target });
    };
    card.addEventListener('click', navigate);
    card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate();
        }
    });
    const surface = element('div', 'crusorai-task-tool-surface');
    const iconWrap = element('span', running ? 'crusorai-task-tool-spinner' : 'crusorai-task-tool-icon');
    iconWrap.append(running ? element('span', 'crusorai-mini-spinner') : icon('robot'));
    surface.append(iconWrap);
    surface.append(element('span', 'crusorai-task-tool-title', agentName.charAt(0).toUpperCase() + agentName.slice(1)));
    const subtitleText = description + (isBackground ? ' (background)' : '') + (toolCalls ? ` · ${toolCalls} calls` : '');
    surface.append(element('span', 'crusorai-task-tool-subtitle', subtitleText));
    card.append(surface);
    // For batch: show each task as clickable row that navigates to its sub-agent session
    const batchTasks = args.tasks;
    if (Array.isArray(batchTasks) && batchTasks.length > 0) {
        const batchList = element('div', 'crusorai-task-tool-batch');
        for (let i = 0; i < batchTasks.length; i++) {
            const t = String(batchTasks[i] ?? '');
            const short = t.slice(0, 80);
            const row = element('div', 'crusorai-task-tool-batch-row', element('span', 'crusorai-task-tool-batch-index', `${i + 1}.`), element('span', undefined, short));
            row.title = t;
            row.style.cursor = 'pointer';
            // Try to find sub-agent id for this task by matching goal/description in host's subAgents
            row.addEventListener('click', () => {
                const subs = host.getSubAgents?.() ?? host.subAgents ?? [];
                let target;
                for (const s of subs) {
                    if (s.goal && t.includes(s.goal.slice(0, 20))) {
                        target = s.id ?? s.subagent_id;
                        break;
                    }
                    if (s.description && t.includes(s.description.slice(0, 20))) {
                        target = s.id;
                        break;
                    }
                }
                if (!target)
                    target = childId ?? navId;
                if (target && host.navigateToSession)
                    host.navigateToSession(String(target));
            });
            batchList.append(row);
        }
        card.append(batchList);
    }
    else {
        // Show full task prompt below subtitle so user can see what the sub-agent is doing (was only short "Research")
        const fullTask = firstString(args, ['prompt', 'task', 'description', 'goal']) ?? '';
        if (fullTask && fullTask !== description) {
            card.append(element('div', 'crusorai-task-tool-task', fullTask.slice(0, 500)));
        }
        else if (fullTask) {
            card.append(element('div', 'crusorai-task-tool-task', fullTask.slice(0, 500)));
        }
    }
    if (childId) {
        const action = element('div', 'crusorai-task-tool-action', icon('arrow-up-right'));
        card.append(action);
    }
    return card;
}
// Their diagnostics box: the LSP report the write/edit tools append to the
// result (<diagnostics file="..."> lines) renders as its own ledger under
// the diff — severity colour is earned per row, never decorative.
function diagnosticsBox(tool) {
    const raw = typeof tool.result === 'string' ? tool.result : '';
    const match = /<diagnostics[^>]*>([\s\S]*?)<\/diagnostics>/.exec(raw);
    if (!match) {
        return undefined;
    }
    const lines = match[1].split('\n').map(line => line.trim()).filter(Boolean).slice(0, 8);
    if (!lines.length) {
        return undefined;
    }
    const box = element('div', 'crusorai-diagnostics');
    box.dataset.component = 'diagnostics';
    for (const line of lines) {
        const severity = /error/i.test(line) ? 'is-failed' : /warn/i.test(line) ? 'is-approval' : 'is-pending';
        box.append(element('div', `crusorai-diagnostics-row ${severity}`, line));
    }
    return box;
}
// Their error-card: a failed tool's own words in an earned-red box, never
// buried in generic JSON.
function errorCard(tool) {
    const card = element('div', 'crusorai-error-card');
    card.append(element('div', 'crusorai-error-card-title', 'Failed'));
    card.append(element('div', 'crusorai-error-card-body', boundedText(tool.result ?? 'The tool failed without a message.', 500)));
    return card;
}
// OpenCode's `skill` tool is NOT a collapsible card in their registry — it
// renders as a `tool-loaded-item` row ("loaded skill" + name). Ported: a
// loaded row for skill_view, one item row per listed skill for the index /
// hub results, and honest call fields for the install/manage actions. All
// rows read the tools' own plain-text results (skill_tools.py /
// skill_hub_tools.py emit "- name ..." lines), never invented fields.
function loadedItemRow(label, detail) {
    const row = element('div', 'crusorai-loaded-item');
    row.dataset.component = 'tool-loaded-item';
    row.append(icon('pass-filled'), element('span', 'crusorai-loaded-item-label', label));
    if (detail) {
        row.append(element('span', 'crusorai-loaded-item-detail', detail));
    }
    return row;
}
function skillBody(tool, result, args) {
    const wrap = element('div', 'crusorai-skill');
    wrap.dataset.component = 'skill';
    const raw = typeof tool.result === 'string' ? tool.result : boundedText(result ?? tool.result ?? '', 4000);
    if (tool.name === 'skill_view') {
        const name = firstString(args, ['name']) ?? /^# skill:\s*(.+)$/m.exec(raw)?.[1]?.trim() ?? 'skill';
        const source = /\(source:\s*([^;)]+)/.exec(raw)?.[1]?.trim();
        wrap.append(loadedItemRow(`Loaded skill · ${name}`, source));
        const prose = raw.replace(/^# skill:.*$/m, '').replace(/^\(source:.*$/m, '').trim();
        if (prose) {
            wrap.append(expandableOutput(markdownCopy(boundedText(prose, 4000))));
        }
        return wrap;
    }
    if (tool.name === 'skills_list' || tool.name === 'hub_list' || tool.name === 'hub_search') {
        const items = raw.split('\n').map(line => line.trim()).filter(line => line.startsWith('- ')).slice(0, 8);
        if (items.length) {
            for (const item of items) {
                const text = item.slice(2).trim();
                const split = text.search(/\s(?:\(|\[|—|--)/);
                wrap.append(split > 0
                    ? loadedItemRow(text.slice(0, split).trim(), text.slice(split).trim())
                    : loadedItemRow(text));
            }
            return wrap;
        }
    }
    if (raw.trim()) {
        wrap.append(toolOutputBox(boundedText(raw, 4000)));
    }
    return wrap;
}
// Multi-platform target family (src/tools/target_tools.py): the receipt is
// the tool's own text — fields say which target/device, the scrollable
// output box carries the receipt, and a device screenshot renders its
// evidence inline like the browser screenshot body does.
function targetBody(tool, host, result, args) {
    const wrap = element('div', 'crusorai-target');
    wrap.dataset.component = 'target';
    const raw = typeof tool.result === 'string' ? tool.result : boundedText(result ?? tool.result ?? '', 4000);
    if (tool.name === 'device_screenshot') {
        const saved = /([^\s"']+\.png)/.exec(raw)?.[1];
        if (saved && tool.state !== 'failed') {
            const src = host.resourceSrc(saved);
            if (src) {
                const img = element('img', 'crusorai-device-screenshot');
                img.src = src;
                img.alt = `Device screenshot ${saved}`;
                img.loading = 'lazy';
                img.onerror = () => { img.remove(); };
                wrap.append(img);
            }
            wrap.append(element('div', 'crusorai-tool-actions', button('Reveal screenshot', 'crusorai-link-button', () => host.revealFile(saved), 'device-camera'), copyButton(saved, host)));
        }
    }
    if (raw.trim()) {
        wrap.append(toolOutputBox(boundedText(raw, 4000)));
    }
    return wrap;
}
/**
 * OpenCode tool-output surface (tool-renderer.tsx list/glob/grep): the
 * tool's own output in a scrollable region -- no meta table, no invented
 * fields. Plain output keeps its line breaks (their CSS sets
 * white-space: pre on tool-output); extracted web text renders as markdown.
 */
function toolOutputBox(text, asMarkdown = false) {
    const box = element('div', 'crusorai-tool-output-box');
    box.dataset.component = 'tool-output';
    box.dataset.scrollable = '';
    box.append(asMarkdown ? markdownCopy(text) : element('pre', undefined, text));
    return box;
}
/** OpenCode GenericTool.args: up to 3 scalar args as `key=value` chips. */
function toolArgsChips(tool) {
    const args = record(tool.arguments);
    if (!args) {
        return [];
    }
    const isSearch = crusorAIToolPresentation(tool.name).family === 'search';
    const skip = new Set(['description', 'query', 'url', 'path', 'name', 'content', 'old_text', 'new_text', 'command', 'code', 'text', 'prompt']);
    const chips = [];
    for (const [key, value] of Object.entries(args)) {
        // OpenCode glob/grep: the pattern IS the info on the line (their
        // args carry pattern=/include=); elsewhere it stays a label key.
        if (skip.has(key) || (key === 'pattern' && !isSearch)) {
            continue;
        }
        if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
            const chip = element('span', 'crusorai-tool-arg', `${key}=${value}`);
            chip.dataset.slot = 'basic-tool-tool-arg';
            chips.push(chip);
            if (chips.length >= 3) {
                break;
            }
        }
    }
    return chips;
}
/**
 * Single-line info tools (founder 2026-10-15: "Read tool card doesn't need
 * a drop down menu, just show #L1-50 info — even Glob, Grep"): read_file
 * is OpenCode's Read (one trigger line, body only ever existed for
 * images), and our search_files/search_code are its Glob/Grep. These rows
 * never expand; the line itself carries the earned info — the line range
 * read, the match count found — computed from what the tool actually
 * delivered, never invented.
 */
const INLINE_INFO_TOOLS = new Set(['read_file', 'search_files', 'search_code']);
function toolInlineInfo(tool) {
    const result = resultRecord(tool.result);
    if (tool.name === 'read_file') {
        const args = record(tool.arguments);
        const offset = typeof args?.offset === 'number' ? args.offset : undefined;
        const limit = typeof args?.limit === 'number' ? args.limit : undefined;
        if (offset !== undefined || limit !== undefined) {
            const start = offset ?? 1;
            return `#L${start}-${limit !== undefined ? start + limit - 1 : start}`;
        }
    }
    if (tool.state === 'running' || tool.state === 'queued') {
        return undefined;
    }
    if (tool.name === 'read_file') {
        const text = (typeof tool.result === 'string' ? tool.result : undefined) ?? firstString(result, ['content', 'output', 'text']);
        if (!text || text.startsWith('Error:') || text.startsWith('⛔')) {
            return undefined;
        }
        const normalized = text.replace(/\r\n/g, '\n').replace(/\n$/, '');
        const lines = normalized === '' ? 0 : normalized.split('\n').length;
        return lines > 0 ? `#L1-${lines}` : undefined;
    }
    // Glob/Grep: the pattern rides the args chips; here the count.
    const matches = result?.matches ?? result?.results;
    if (Array.isArray(matches)) {
        return `${matches.length} match${matches.length === 1 ? '' : 'es'}`;
    }
    const text = (typeof tool.result === 'string' ? tool.result : undefined) ?? firstString(result, ['content', 'output', 'text']);
    if (!text) {
        return undefined;
    }
    if (/^No results found/.test(text)) {
        return 'No matches';
    }
    if (/^(Error:|Path does not exist|⛔)/.test(text)) {
        return undefined;
    }
    const count = text.split('\n').filter(line => line.trim() && !line.startsWith('...')).length;
    return count > 0 ? `${count} match${count === 1 ? '' : 'es'}` : undefined;
}
/** A muted `key=value`-slot chip (OpenCode basic-tool-tool-arg). */
function toolInfoChip(text) {
    const chip = element('span', 'crusorai-tool-arg', text);
    chip.dataset.slot = 'basic-tool-tool-arg';
    return chip;
}
/** Tools whose target is a file the header links to (icon + filename). */
const FILE_LINK_TOOLS = new Set(['read_file', 'edit_file', 'write_file', 'copy_file']);
/** The diff an edit/write result carries (record field or receipt tail). */
function editDiffText(tool) {
    const fromRecord = firstString(resultRecord(tool.result), ['diff']);
    if (fromRecord) {
        return fromRecord;
    }
    const text = typeof tool.result === 'string' ? tool.result : '';
    const marker = 'Diff preview:\n';
    return text.includes(marker) ? text.split(marker)[1] : undefined;
}
/** Counted +a −r for an edit/write (receipt-reported, else diff-counted). */
function editDiffStats(tool) {
    const receipt = /lines added:\s*(\d+),\s*removed:\s*(\d+)/i.exec(typeof tool.result === 'string' ? tool.result : '');
    if (receipt) {
        return { added: Number(receipt[1]), removed: Number(receipt[2]) };
    }
    return diffStats(editDiffText(tool));
}
/** OpenCode DiffChanges: the counted chip that rides the file header. */
function diffChangesChip(stats) {
    const chip = element('span', 'crusorai-diff-count', element('span', 'is-added', `+${stats.added}`), element('span', 'is-removed', `−${stats.removed}`));
    chip.dataset.slot = 'basic-tool-tool-arg';
    return chip;
}
/** First error line of an inline row's result, when the tool failed in-band. */
function toolInlineError(tool) {
    const result = resultRecord(tool.result);
    const text = (typeof tool.result === 'string' ? tool.result : undefined) ?? firstString(result, ['content', 'output', 'text', 'error']);
    if (!text) {
        return tool.state === 'failed' ? 'Failed' : undefined;
    }
    const firstLine = text.split('\n')[0]?.trim() ?? '';
    if (tool.state === 'failed' || /^(Error:|Path does not exist|⛔)/.test(firstLine)) {
        return firstLine.length > 160 ? `${firstLine.slice(0, 160)}…` : firstLine || 'Failed';
    }
    return undefined;
}
function familyBody(tool, host) {
    // A2UI Catalog v1 (plan Phase 2): a tool result carrying an
    // {"a2ui_operations": [...]} envelope renders through the fixed-catalog
    // surface manager — display_crusor_task takes this generic path instead
    // of painting its surface JSON as prose. No envelope -> today's bodies.
    const a2uiBody = renderA2UIToolBody(tool.result, {
        onAction: (event) => { console.log('[CrusorAI] A2UI action (no v2 handler wired yet)', event); },
        resourceSrc: (resource) => host.resourceSrc(resource),
    });
    if (a2uiBody) {
        return a2uiBody;
    }
    const presentation = crusorAIToolPresentation(tool.name);
    if (presentation.family === 'terminal' || presentation.family === 'process') {
        return terminalBody(tool, host);
    }
    const args = record(tool.arguments);
    const result = resultRecord(tool.result);
    const body = element('div', `crusorai-tool-body crusorai-family-${presentation.family}`);
    body.dataset.rendererFamily = presentation.family;
    const target = displayTarget(tool);
    if (presentation.family === 'file-read') {
        // OpenCode list/read: the trigger (title + path subtitle) is the
        // header; the body is only the tool's output in their scrollable
        // tool-output region. The old PATH/LINES/ENCODING table was ours,
        // not theirs -- and for list_files it invented 'Lines —'.
        const output = (typeof tool.result === 'string' ? tool.result : undefined)
            ?? firstString(result, ['content', 'output', 'text'])
            ?? boundedText(tool.result, 8000);
        if (output.trim()) {
            body.append(toolOutputBox(output.slice(0, 8000)));
        }
    }
    else if (presentation.family === 'file-write') {
        if (tool.name === 'generate_image' || tool.name === 'media_download') {
            const rawResult = typeof tool.result === 'string' ? tool.result : '';
            const savedMatch = /saved:\s*([^\s(]+)/i.exec(rawResult);
            const savedPath = savedMatch?.[1] ?? firstString(args, ['filename']) ?? target;
            const promptText = firstString(args, ['prompt']) ?? firstString(args, ['query']);
            const sizeMatch = /\(([^)]+)\)/.exec(rawResult);
            void sizeMatch;
            if (savedPath && tool.state !== 'failed') {
                const src = host.resourceSrc(savedPath);
                if (src) {
                    const mediaWrap = element('div', 'crusorai-media-preview-container');
                    const img = element('img', 'crusorai-generated-image');
                    img.src = src;
                    img.alt = promptText ? `Generated image: ${promptText}` : `Media ${savedPath}`;
                    img.loading = 'lazy';
                    img.onerror = () => { mediaWrap.remove(); };
                    mediaWrap.append(img);
                    body.append(mediaWrap);
                }
            }
            body.append(element('div', 'crusorai-tool-actions', button('Reveal image in files', 'crusorai-link-button', () => host.revealFile(savedPath), 'file-media'), copyButton(savedPath, host)));
        }
        else {
            // OpenCode edit/write/patch (FileTool): the counted +a −r rides
            // the HEADER (diffChangesChip in toolRow); the body is the diff
            // itself in edit-content — or, for a write with no diff, the
            // written content in write-content — plus earned diagnostics.
            const diff = editDiffText(tool);
            // OpenCode's write render NEVER shows a diff (tool-renderer.tsx
            // write: the file component in text mode) — a write's receipt
            // diff is all '+' lines, which painted as a solid green wall
            // (founder 2026-10-15: 'write file is not like opencode, worst
            // look'). Writes show the written content; edits show the diff.
            if (tool.name !== 'write_file' && diff) {
                const editBox = element('div', 'crusorai-edit-content');
                editBox.dataset.component = 'edit-content';
                editBox.append(diffPreview(diff));
                body.append(editBox);
            }
            else if (typeof args?.content === 'string' && args.content) {
                const writeBox = element('div', 'crusorai-write-content');
                writeBox.dataset.component = 'write-content';
                writeBox.append(element('pre', undefined, boundedText(args.content, 8000)));
                body.append(writeBox);
            }
            else {
                const text = (typeof tool.result === 'string' ? tool.result : undefined) ?? boundedText(tool.result, 4000);
                if (text.trim()) {
                    body.append(toolOutputBox(text.slice(0, 4000)));
                }
            }
            const diagnostics = diagnosticsBox(tool);
            if (diagnostics) {
                body.append(diagnostics);
            }
        }
    }
    else if (presentation.family === 'search') {
        // OpenCode glob/grep: matches ride the scrollable tool-output region.
        const matches = result?.matches ?? result?.results;
        if (Array.isArray(matches) && matches.length) {
            body.append(toolOutputBox(matches.map(m => typeof m === 'string' ? m : boundedText(m, 300)).join('\n')));
        }
        else {
            body.append(toolOutputBox(boundedText(result ?? tool.result, 4000)));
        }
    }
    else if (presentation.family === 'verification') {
        // NO invented checklist (the old body hardcoded three check rows
        // and a dead evidence button): the tool's own output — tsc
        // lines, the verify report — is the body. State rides the header.
        const text = (typeof tool.result === 'string' ? tool.result : undefined)
            ?? firstString(result, ['output', 'text', 'report'])
            ?? boundedText(tool.result, 6000);
        if (text.trim()) {
            body.append(toolOutputBox(text.slice(0, 6000)));
        }
    }
    else if (presentation.family === 'web') {
        body.append(toolOutputBox(boundedText(result ?? tool.result, 6000), true));
    }
    else if (presentation.family === 'browser') {
        // Hermes backend receipts (browser_tools.py): honest per-tool fields.
        // The lab-era rows (a Page field and a hardcoded viewport — puppeteer
        // shapes of a backend that never ran on user machines), the fake
        // 'document' line, and the reveal-on-URL buttons are retired:
        // visible testing (owner 2026-09-07) shows the EVIDENCE here — the
        // screenshot image, the session recording, the ref the agent acted on.
        if (tool.name === 'browser_screenshot') {
            const raw = typeof tool.result === 'string' ? tool.result : '';
            const saved = /Screenshot saved:\s*([^\s(]+)/.exec(raw)?.[1];
            if (saved) {
                const src = host.resourceSrc(saved);
                if (src) {
                    const img = element('img', 'crusorai-browser-screenshot');
                    img.src = src;
                    img.alt = `Screenshot ${saved}`;
                    img.loading = 'lazy';
                    img.onerror = () => { img.remove(); };
                    body.append(img);
                }
                body.append(element('div', 'crusorai-tool-actions', button('Reveal screenshot', 'crusorai-link-button', () => host.revealFile(saved), 'device-camera'), copyButton(saved, host)));
            }
        }
        else if (tool.name === 'browser_navigate') {
            const recording = firstString(result, ['recording']);
            const snapshot = firstString(result, ['snapshot']);
            if (snapshot) {
                body.append(toolOutputBox(boundedText(snapshot, 4000)));
            }
            if (recording) {
                // The visible-testing artifact (hermes record start/stop): one
                // click to watch what the agent did in the window.
                body.append(element('div', 'crusorai-tool-actions', button('Watch session recording', 'crusorai-link-button', () => host.revealFile(recording), 'device-camera'), copyButton(recording, host)));
            }
            else {
                body.append(element('div', 'crusorai-tool-actions', copyButton(firstString(args, ['url']) ?? target, host)));
            }
        }
        else if (tool.name === 'browser_click' || tool.name === 'browser_type' || tool.name === 'browser_press') {
            const done = firstString(result, ['clicked', 'typed', 'pressed']) ?? boundedText(tool.result, 500);
            if (done) {
                body.append(toolOutputBox(done));
            }
        }
        else if (tool.name === 'browser_console') {
            const evaluated = firstString(result, ['result']) ?? boundedText(tool.result, 2000);
            if (evaluated) {
                body.append(toolOutputBox(boundedText(evaluated, 2000)));
            }
        }
        else {
            body.append(toolOutputBox(boundedText(result ?? tool.result, 2000)));
        }
    }
    else if (presentation.family === 'plan') {
        // Field 2026-09-10: the body painted the raw {"steps":[...]} argument
        // JSON. hermes hoists todo parts into a status panel whose rows are
        // glyph+text (status-row.tsx: dashed ring pending, live dot
        // in_progress, pass-filled done, circle-slash cancelled) — the card
        // body ports those rows from the WRITTEN state (the tool result's
        // normalized list) with the call args as fallback.
        body.append(planListBody(tool, resultRecord(tool.result), args));
    }
    else if (presentation.family === 'skill') {
        body.append(skillBody(tool, result, args));
    }
    else if (presentation.family === 'target') {
        body.append(targetBody(tool, host, result, args));
    }
    else if (presentation.family === 'session') {
        body.append(toolOutputBox(boundedText(result ?? tool.result, 4000)));
    }
    else if (presentation.family === 'subagent' || tool.name.startsWith('delegate_to_subagent')) {
        // OpenCode parity: task-tool-card clickable navigation
        return taskToolCard(tool, host);
    }
    else if (presentation.family === 'code' || presentation.family === 'scaffold') {
        // Field 2026-09-10: this body hardcoded a fake RUNTIME value —
        // invented text on a JS scaffolding call. The card shows the call's
        // OWN fields and the honest state, nothing else.
        const detail = result ?? boundedText(tool.result, 4000);
        if (detail) {
            body.append(toolOutputBox(boundedText(detail, 4000)));
        }
    }
    else {
        // Generic families: a STRING result is model prose (think reasoning,
        // salvage notes). Render it through the same markdown pass as
        // assistant copy, inside the hermes expandable (cap + fade + chevron).
        // The old raw JSON dump leaked `**Thinking:**` and \n escapes into
        // the panel (owner verdict: disgusting). Arguments stay reachable,
        // collapsed, honestly labeled.
        const resultText = typeof tool.result === 'string' ? tool.result : '';
        // Models often self-announce ("**Thinking:** ...") — the card title
        // already says what the tool is, so a duplicated label is fake chrome.
        // Presentation-only strip of the leading self-labels.
        // Both self-announce shapes leak in the field: "💭 **Thinking:**" and
        // "**Thinking:**" — the label marker may sit on either side of the
        // bold wrapper (and the 💭 on either side of the label). One pattern
        // per position, tolerant of order.
        const prose = resultText
            .replace(/^\s*(?:\*\*)?\s*💭?\s*(?:\*\*)?\s*thinking\s*:?\s*(?:\*\*)?\s*:?\s*/i, '')
            .replace(/^\s*💭\s+/, '')
            .replace(/^\s*(?:\*\*)?\s*reasoning\s*:?\s*(?:\*\*)?\s*:?\s*/i, '')
            // The think tool's engine envelope ends with boilerplate
            // ("---\n*Proceeding with the approach above.*") — the row
            // already says Thought; the trailer is not the model's words.
            .replace(/\n*---\s*\n\*Proceeding with the approach above\.\*\s*$/i, '');
        if (prose.trim()) {
            if (tool.name === 'think') {
                // Hermes thought body: small, dim, quiet scaffold — never a
                // full-width prose block competing with the answer.
                body.append(expandableOutput(element('div', 'crusorai-thought-body', markdownCopy(prose))));
            }
            else {
                body.append(expandableOutput(markdownCopy(prose)));
            }
            if (tool.name !== 'think') {
                // Hermes thought cards carry ONLY the thought — an "Arguments"
                // disclosure under a thinking row is chrome the user never asked
                // to open (field screenshot 2026-09-05).
                const argsDetails = element('details', 'crusorai-tool-args-details');
                argsDetails.append(element('summary', 'crusorai-tool-args-summary', 'Arguments'));
                argsDetails.append(labeledPayload('Arguments', tool.arguments));
                body.append(argsDetails);
            }
        }
        else {
            body.append(labeledPayload('Details', { arguments: tool.arguments, result: tool.result }));
        }
    }
    return body;
}
function toolRow(tool, host, openTools, closedTools, pendingClarify) {
    // Hermes (message-parts ChainToolFallback): a clarify call renders its own
    // widget card — the interactive question while it blocks, the settled Q&A
    // after — never a generic collapsible tool row.
    if (tool.name === 'clarify' && pendingClarify !== undefined) {
        // The card is a widget, not a disclosure row; the toolSection slot
        // only appends HTMLElements, so the cast keeps the signature honest.
        return clarifyCard(tool, host, openTools, pendingClarify);
    }
    const presentation = crusorAIToolPresentation(tool.name);
    const isPending = tool.state === 'running' || tool.state === 'queued';
    // Read + Glob/Grep rows are single-line (no dropdown, no caret): the
    // trigger built below is the whole card, info chip included.
    const isInline = INLINE_INFO_TOOLS.has(tool.name);
    const details = element('details', `crusorai-tool-row is-${tool.state}`);
    details.dataset.component = 'tool-trigger';
    details.dataset.conversationScaffold = '';
    details.dataset.toolId = tool.id;
    details.dataset.toolName = tool.name;
    const shouldDefaultOpen = presentation.defaultOpen === 'always' || (presentation.defaultOpen === 'running' && (tool.state === 'running' || tool.state === 'approval'));
    // The user's own hand outranks every default (founder 2026-10-15:
    // 'why i can't close the dropdown — if did, reopens'): an explicitly
    // closed row stays closed across streaming repaints even when its
    // family defaults open ('always'/'running'); defaults only govern
    // rows the user never touched.
    details.open = !closedTools.has(tool.id) && (openTools.has(tool.id) || shouldDefaultOpen);
    // Hermes wording (ThinkingDisclosure): a live block says "Thinking", a
    // settled one says "Thought" — the tool catalog title stays canonical for
    // other surfaces; the transcript row speaks hermes.
    const rowTitle = tool.name === 'think' ? (isPending ? 'Thinking' : 'Thought') : presentation.title;
    const titleSpan = element('strong', isPending ? 'crusorai-shimmer' : undefined, rowTitle);
    const targetText = displayTarget(tool);
    // Hermes quiet-card rule: the target echo must SAY something. When it
    // just repeats the tool name ("Think think"), it is noise — drop it.
    // A bare "." / "./" (the workspace root, e.g. list_files) says nothing
    // either: "List files ." is noise, not a target (field 2026-10-15).
    const trivialTargets = new Set(['', '.', './', '/', 'workspace']);
    const targetMeaningful = !!targetText
        && !trivialTargets.has(targetText.trim().toLowerCase())
        && targetText.toLowerCase() !== tool.name.toLowerCase()
        && targetText.toLowerCase() !== presentation.title.toLowerCase();
    // OpenCode BasicTool anatomy, extracted (basic-tool.tsx): the trigger
    // carries tool-trigger > trigger-content > indicator + icon + info
    // (structured > main > title/subtitle) with the chevron as the
    // collapsible arrow. Our classes ride along; their verbatim CSS keys
    // off these data hooks.
    titleSpan.dataset.slot = 'basic-tool-tool-title';
    // Their rendered response (founder reference photos 2026-10-15): the
    // settled tool row is a bare muted label — "Shell ⌄" — no icon column,
    // no status glyph, the caret hugging the label. While a tool runs,
    // the spinner takes the label's left, exactly where their indicator
    // sits. State still earns colour in the body, not the label.
    const inlineInfo = isInline ? toolInlineInfo(tool) : undefined;
    let subtitle;
    if (targetMeaningful) {
        if (FILE_LINK_TOOLS.has(tool.name)) {
            // Founder 2026-10-15: the path is a FLAT file link — the file's
            // real workbench icon + filename only, no visible button/pill,
            // never larger than the tool title; the full path is the
            // tooltip, and clicking it opens that file in the editor.
            const fileName = targetText.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? targetText;
            subtitle = element('span', 'crusorai-tool-file-link show-file-icons', fileIcon(host, targetText), element('span', 'crusorai-tool-file-name', fileName));
            subtitle.title = targetText;
            subtitle.addEventListener('click', (event) => {
                event.stopPropagation();
                host.revealFile(targetText);
            });
        }
        else {
            subtitle = element('span', 'crusorai-tool-target', targetText);
        }
        if (presentation.family === 'terminal' || presentation.family === 'process') {
            // OpenCode shell trigger (tool-renderer.tsx): the command rides
            // the header ONLY while collapsed — once the card opens, the
            // bash-output box carries it and the header goes bare. First
            // line only (their ShellSubmessage for execute).
            subtitle.classList.add('crusorai-shell-command');
            subtitle.textContent = targetText.split('\n')[0];
        }
        subtitle.dataset.slot = 'basic-tool-tool-subtitle';
    }
    // OpenCode DiffChanges rides the header (their file-accordion actions):
    // counted +a −r next to the filename — earned from the result, so it
    // appears when the edit lands, never while running.
    const headerDiffStats = presentation.family === 'file-write' ? editDiffStats(tool) : undefined;
    const titleMain = element('span', undefined, titleSpan, subtitle, ...toolArgsChips(tool), headerDiffStats ? diffChangesChip(headerDiffStats) : undefined, 
    // Inline info (#L1-N, match count) hugs the filename on the same
    // line — never pushed to the row's far edge (founder 2026-10-15).
    inlineInfo ? toolInfoChip(inlineInfo) : undefined);
    titleMain.dataset.slot = 'basic-tool-tool-info-main';
    const titleStructured = element('span', undefined, titleMain);
    titleStructured.dataset.slot = 'basic-tool-tool-info-structured';
    const toolInfo = element('span', undefined, titleStructured);
    toolInfo.dataset.slot = 'basic-tool-tool-info';
    const arrow = element('span', undefined, isPending || isInline ? undefined : icon('chevron-down'));
    arrow.dataset.slot = 'collapsible-arrow';
    const triggerContent = element('span', undefined, isPending ? element('span', 'crusorai-mini-spinner') : undefined, toolInfo, arrow);
    triggerContent.dataset.slot = 'basic-tool-tool-trigger-content';
    const trigger = element('span', 'crusorai-tool-trigger', triggerContent);
    trigger.dataset.component = 'tool-trigger';
    const summary = element('summary', 'crusorai-tool-summary', trigger);
    summary.dataset.slot = 'collapsible-trigger';
    details.dataset.component = 'collapsible';
    details.classList.add('tool-collapsible');
    if (tool.duration) {
        const meta = element('span', 'crusorai-tool-duration', tool.duration);
        meta.dataset.slot = 'basic-tool-tool-arg';
        trigger.append(meta);
    }
    if (isInline) {
        const row = element('div', `crusorai-tool-row crusorai-tool-inline is-${tool.state}`);
        row.dataset.component = 'tool-trigger';
        row.dataset.conversationScaffold = '';
        row.dataset.toolId = tool.id;
        row.dataset.toolName = tool.name;
        row.append(trigger);
        const errorLine = toolInlineError(tool);
        if (errorLine) {
            row.append(element('span', 'crusorai-tool-inline-error', errorLine));
        }
        return row;
    }
    const body = familyBody(tool, host);
    body.dataset.slot = 'collapsible-content';
    if (tool.state === 'failed' && (body.classList.contains('crusorai-tool-body') || body.querySelector?.('.crusorai-tool-body'))) {
        body.append(errorCard(tool));
    }
    details.append(summary, body);
    // Persist ONLY user-driven disclosure. A 'toggle' listener also fires
    // for the programmatic `details.open = true` a running row gets on
    // every streaming repaint — that latched every live "Thinking" row
    // into openTools, so settled "Thought" rows stayed expanded and
    // painted the model's inner monologue full-size (field 2026-10-15).
    // A summary click is always the user's own hand (mouse or keyboard).
    summary.addEventListener('click', () => {
        if (details.open) {
            openTools.delete(tool.id);
            closedTools.add(tool.id);
        }
        else {
            openTools.add(tool.id);
            closedTools.delete(tool.id);
        }
    });
    return details;
}
/**
 * Cards and runs, in order -- the same split the CopilotKit webview renders.
 *
 * A run of consecutive activity calls folds into one summary line, identified by its
 * FIRST tool call id (never by position, or a live stream would re-key the row every
 * time a call lands) and disclosed under the same key so opening one survives a
 * re-render. Anything that draws its own surface -- a file edit's diff, a question --
 * stays a card in place. `live` comes from the caller: a settled turn whose last call
 * never got a result must still read as finished, not as work in progress.
 */
function toolSection(tools, host, openTools, closedTools, live, showHeading = true, pendingClarify) {
    const section = element('section', 'crusorai-tool-list');
    section.dataset.component = 'tool-list';
    if (showHeading) {
        section.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Actions'), element('span', 'crusorai-section-count', String(tools.length))));
    }
    const groups = splitRunGroups(tools);
    // Hermes: a SINGLE action is one bare row — never a collapsible run group
    // with a "(1)" count bubble wrapping its own duplicate header (owner
    // screenshot 2026-09-04: "Running dir /b (1)" over a "Terminal dir /b"
    // card said the same thing twice). Only 2+ calls earn a run summary.
    if (groups.length === 1 && groups[0].kind === 'run' && groups[0].tools.length === 1) {
        section.append(toolRow(groups[0].tools[0], host, openTools, closedTools, pendingClarify));
        return section;
    }
    for (const group of groups) {
        if (group.kind === 'card') {
            section.append(toolRow(group.tool, host, openTools, closedTools, pendingClarify));
            continue;
        }
        const runTools = group.tools;
        const key = runTools[0]?.id ?? `run-${group.start}`;
        const runLive = live && runTools.some(tool => tool.state === 'running' || tool.state === 'queued');
        const details = element('details', `crusorai-tool-run${runLive ? ' is-live' : ''}`);
        details.dataset.component = 'tool-run';
        details.dataset.conversationScaffold = '';
        details.dataset.runKey = key;
        details.open = !closedTools.has(key) && (runLive || openTools.has(key));
        details.addEventListener('toggle', () => {
            if (details.open) {
                openTools.add(key);
                closedTools.delete(key);
            }
            else {
                openTools.delete(key);
                closedTools.add(key);
            }
        });
        const summary = element('summary', 'crusorai-tool-run-summary', runLive ? element('span', 'crusorai-mini-spinner') : icon('tools'), element('span', 'crusorai-tool-run-text', summarizeToolRun(runTools, runLive, tool => compactTarget(displayTarget(tool)) ?? tool.name)), element('span', 'crusorai-tool-run-count', String(runTools.length)));
        details.append(summary);
        const body = element('div', 'crusorai-tool-run-body');
        for (const tool of runTools) {
            body.append(toolRow(tool, host, openTools, closedTools, pendingClarify));
        }
        details.append(body);
        section.append(details);
    }
    return section;
}
function engineStatus(model) {
    const state = model.engineState;
    const tone = state === 'ready' ? 'ready' : state === 'starting' ? 'running' : state === 'crashed' || state === 'degraded' ? 'failed' : 'idle';
    const chip = element('span', `crusorai-engine-status is-${tone}`, element('span', 'crusorai-status-dot'), state === 'ready' ? 'Crusor ready' : `Engine ${state}`);
    let engineTitle = '';
    if (model.engineBuild && model.engineBuild !== 'unknown') {
        const short = model.engineBuild.split(/\s+/)[0];
        chip.append(element('span', 'crusorai-engine-build', short));
        engineTitle = `Engine build: ${model.engineBuild}`;
    }
    // Freshness stamp next to the engine hash (see CRUSORAI_UI_STAMP): the
    // engine chip alone could not catch the 2026-09-08 field round where the
    // engine rebuilt but the workbench JS did not. An engine build dated
    // AFTER this stamp means the compiled workbench predates the engine.
    const engineDate = /\b\d{4}-\d{2}-\d{2}\b/.exec(model.engineBuild ?? '')?.[0];
    const stale = !!engineDate && engineDate > CRUSORAI_UI_STAMP;
    chip.append(element('span', 'crusorai-engine-build', `ui ${CRUSORAI_UI_STAMP}${stale ? ' STALE' : ''}`));
    const uiTitle = `Workbench UI build: ${CRUSORAI_UI_STAMP}`;
    chip.title = engineTitle ? `${uiTitle} · ${engineTitle}` : uiTitle;
    if (stale) {
        chip.title = `Workbench UI build ${CRUSORAI_UI_STAMP} is OLDER than the engine build (${model.engineBuild}) — the engine rebuilt, the desktop workbench did not. Recompile the desktop app to pick up the current UI.`;
    }
    return chip;
}
/** Hermes' todo tone rules (ui-tui todoTone / desktop composer-status): the
 *  row's own status drives the glyph -- the strip never guesses from the
 *  row index again. */
function planStepGlyph(status) {
    if (status === 'in_progress') {
        return element('span', 'crusorai-mini-spinner');
    }
    if (status === 'completed') {
        return icon('pass-filled');
    }
    if (status === 'failed') {
        return icon('circle-slash');
    }
    const ring = element('span', 'crusorai-todo-ring');
    ring.setAttribute('aria-hidden', 'true');
    return ring;
}
function planStrip(model, open, onToggle) {
    if (!model.plan.length) {
        return undefined;
    }
    const done = model.plan.filter(s => s.status === 'completed').length;
    const anyActive = model.plan.some(s => s.status === 'in_progress');
    const details = element('details', 'crusorai-plan-strip');
    details.dataset.component = 'plan-strip';
    details.open = open ?? model.running;
    details.addEventListener('toggle', () => onToggle(details.open));
    const summary = element('summary', 'crusorai-plan-strip-summary', icon('list-ordered'), element('strong', undefined, 'Plan'), element('span', undefined, `${done}/${model.plan.length}`), model.running && anyActive ? element('span', 'crusorai-plan-strip-state', element('span', 'crusorai-mini-spinner'), 'In progress') : undefined, icon('chevron-down'));
    const list = element('ol', 'crusorai-plan-strip-list');
    for (const step of model.plan) {
        list.append(element('li', `is-${step.status}`, planStepGlyph(step.status), element('span', undefined, step.text)));
    }
    details.append(summary, list);
    return details;
}
/**
 * The tail activity row, with the timers it needs to behave.
 *
 * It is mount-scoped state, not model data: the row must survive every re-render of a streaming
 * turn while holding (a) the signature of the last visible progress, so a quiet spell is timed
 * from the moment the turn LAST showed something rather than from whenever this row mounted, and
 * (b) the reveal delay, so a tool whose arguments land in three frames never gets to flash a
 * label down the column. `tick` asks the mount to repaint, which is what advances the seconds.
 */
const thoughtKey = (model) => `thought:${model.sessionId ?? 'session'}`;
function createActivityState(tick) {
    let lastSignature = '';
    let quietSince;
    let verb = '';
    let revealed = false;
    let quietTimer;
    let revealTimer;
    let ticker;
    return {
        sync(model) {
            const parts = activityParts(model);
            // Thinking is "active" while a thought is the newest thing the turn has produced.
            if (model.running && parts.at(-1)?.type === 'reasoning') {
                elapsedFor(thoughtKey(model), Date.now());
            }
            else {
                closeMeasurement(thoughtKey(model), Date.now());
            }
            const signature = activitySignature(parts);
            if (signature !== lastSignature) {
                lastSignature = signature;
                quietSince = undefined;
                if (quietTimer !== undefined) {
                    clearTimeout(quietTimer);
                    quietTimer = undefined;
                }
                if (model.running) {
                    quietTimer = setTimeout(() => { quietSince = Date.now(); tick(); }, TURN_QUIET_S * 1000);
                }
            }
            const name = draftingToolName(model.tools);
            const next = name && !toolNarratesWait(parts) ? toolPresentVerb(name) : '';
            if (next !== verb) {
                verb = next;
                revealed = false;
                if (revealTimer !== undefined) {
                    clearTimeout(revealTimer);
                    revealTimer = undefined;
                }
                if (verb) {
                    revealTimer = setTimeout(() => { revealed = true; tick(); }, DRAFTING_REVEAL_MS);
                }
            }
            if (model.running && ticker === undefined) {
                ticker = setInterval(tick, 1000);
            }
            if (!model.running && ticker !== undefined) {
                clearInterval(ticker);
                ticker = undefined;
            }
        },
        /**
         * The row for this model, or nothing at all. Two shapes, one markup: before the tail
         * message has produced anything this is the pre-first-token indicator counting from the
         * turn's start; after it, it is the gap indicator counting from the last visible
         * progress. Same classes either way, so the column reads as one continuous scaffolding
         * instead of two competing widgets.
         *
         * It stays silent when a tool row is already narrating the wait (that row carries its
         * own timer, and a second spinner would count the same seconds twice), and while the turn
         * is paused on a question the user has not answered -- that is not the agent working.
         */
        row(model) {
            const parts = activityParts(model);
            const hint = model.cancelRequested ? 'Stopping safely' : statusHintLabel(model.compacting, verb, revealed);
            const slot = activityRowMode({
                parts,
                working: model.running,
                awaitingInput: model.approval !== undefined,
                toolNarrating: toolNarratesWait(parts),
                hint,
                quietSince,
            });
            if (!slot) {
                return undefined;
            }
            const row = element('div', 'crusorai-scaffold-status');
            row.dataset.conversationScaffold = '';
            row.dataset.slot = slot;
            row.setAttribute('aria-label', hint || UNNAMED_WAIT_LABEL);
            row.setAttribute('aria-live', 'polite');
            row.setAttribute('role', 'status');
            // No breathing cursor, no elapsed seconds (founder 2026-10-15:
            // delete the breathing UI completely) — the row is words only.
            if (hint) {
                row.append(element('span', 'crusorai-scaffold-hint', hint));
            }
            return row;
        },
        /**
         * How long the CURRENT turn's thinking ran, once it has stopped running. The measurement
         * is armed while the last thing the turn produced is a thought and closed the moment the
         * turn moves on, so the number survives every repaint of the row that watched it.
         */
        thoughtSeconds(model) {
            return measuredDuration(thoughtKey(model));
        },
        dispose() {
            if (quietTimer !== undefined) {
                clearTimeout(quietTimer);
                quietTimer = undefined;
            }
            if (revealTimer !== undefined) {
                clearTimeout(revealTimer);
                revealTimer = undefined;
            }
            if (ticker !== undefined) {
                clearInterval(ticker);
                ticker = undefined;
            }
        },
    };
}
/**
 * What the model thought, behind a row -- Hermes' affordance, not a paragraph dumped into the
 * bubble. `think` receipts arrive as a `brain`-glyphed tool row upstream and streamed reasoning
 * folds into the same disclosure, so one component covers both. No leading chevron: the caret
 * sits to the RIGHT of the label and only the label is the hit target, which is why this is a
 * button-shaped summary over a content-width pill rather than a full-width bar.
 */
function thinkingBlock(reasoning, openTools, closedTools, live, seconds, partKey) {
    reasoning = separateGluedReasoningBlocks(reasoning);
    const key = partKey || 'thought';
    const details = element('details', 'crusorai-thought-row');
    details.dataset.component = 'reasoning-part';
    details.dataset.conversationScaffold = '';
    details.dataset.disclosureKey = key;
    // OpenCode reasoning anatomy: the live block shows itself; a settled
    // one rests as a single quiet row the user opens by choice. The old
    // always-open + 'toggle' latch painted every settled thought at full
    // size forever (field 2026-10-15) — persist only the user's click.
    details.open = !closedTools.has(key) && (live || openTools.has(key));
    // OpenCode's rendered response (founder reference 2026-10-15): the
    // reasoning row is the bare muted word "Thinking" — no icon, no caret
    // at the edge, no timer. The word itself is the disclosure; while
    // live it sweeps. Settled it rests as one quiet line.
    const summary = element('summary', 'crusorai-disclosure-row', element('strong', live ? 'crusorai-shimmer crusorai-thinking-word' : 'crusorai-thinking-word', live ? 'Thinking' : 'Thought'));
    summary.addEventListener('click', () => {
        if (details.open) {
            openTools.delete(key);
            closedTools.add(key);
        }
        else {
            openTools.add(key);
            closedTools.delete(key);
        }
    });
    // Split accumulated reasoning into separate blocks (one per LLM call)
    const body = element('div', 'crusorai-thought-body');
    body.dataset.component = 'markdown';
    const blocks = reasoning.split(/\n\n---\n\n/);
    for (const block of blocks) {
        const trimmed = block.trim();
        if (trimmed) {
            body.append(element('p', undefined, trimmed));
        }
    }
    details.append(summary, body);
    return details;
}
/**
 * One assistant turn: label, thinking disclosure, then the ORDERED timeline —
 * hermes message-parts.tsx walks message.parts at their arrival index, so a
 * work-then-answer turn reads top-to-bottom in the order the model produced
 * it: tool cards where the calls happened, final wording LAST. Tool bodies
 * come from the view map; a tool whose start frame was missed still paints
 * (after the timeline) so a card can never silently vanish.
 */
function textPart(text, slot) {
    const body = element('div', undefined, markdownCopy(text, slot));
    body.dataset.slot = 'text-part-body';
    const wrap = element('div', 'crusorai-text-part', body);
    wrap.dataset.component = 'text-part';
    return wrap;
}
function assistantTurn(spec, host, openTools, closedTools) {
    const live = spec.live;
    const response = element('section', 'crusorai-assistant-message');
    response.dataset.component = spec.current ? 'session-turn' : 'assistant-message';
    response.append(element('div', 'crusorai-assistant-label', icon('crusor'), element('strong', undefined, 'Crusor'), live ? element('span', 'crusorai-stream-label', spec.cancelRequested ? 'Stopping.' : 'Working') : undefined));
    // Reasoning parts are tracked INLINE in the parts array (kind='reasoning') so their
    // chronological position relative to text and tools is always preserved exactly.
    // This mirrors the Hermes approach (message.content is a single ordered array).
    const reasoningParts = (spec.reasoningParts || []).filter(p => p && p.text);
    // Parts are the ordering source. A turn that predates them (or somehow
    // carries text without a single text part) falls back to the legacy
    // single-block paint so the answer can never be dropped by a missing
    // timeline.
    const parts = spec.parts.length
        ? spec.parts
        : (spec.assistantText ? [{ kind: 'text', text: spec.assistantText }] : []);
    const toolsById = new Map(spec.tools.map(t => [t.id, t]));
    let lastTextIndex = -1;
    for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        if (part.kind === 'text' && part.text) {
            lastTextIndex = i;
        }
    }
    // The streaming slot rides the LAST text segment only: the painter's fast
    // path patches exactly that node per token; earlier segments are frozen.
    let run = [];
    const flushRun = () => {
        if (!run.length) {
            return;
        }
        response.append(toolSection(run, host, openTools, closedTools, live, false, spec.clarify));
        run = [];
    };
    parts.forEach((part, index) => {
        if (part.kind === 'reasoning') {
            // Flush any accumulated tool run BEFORE the reasoning block (preserves order)
            flushRun();
            const rp = reasoningParts[part.reasoningIndex];
            if (rp && rp.text) {
                // A reasoning block is "live" (spinner + growing text) only when it is the
                // last part in the timeline and the turn is still running.
                const isLastPart = index === parts.length - 1;
                response.append(thinkingBlock(rp.text, openTools, closedTools, live && isLastPart, spec.thoughtSeconds, `${spec.turnKey || 'turn'}:${part.reasoningIndex}`));
            }
            return;
        }
        if (part.kind === 'tool') {
            const tool = toolsById.get(part.toolId);
            if (tool) {
                run.push(tool);
            }
            return;
        }
        if (!part.text) {
            return;
        }
        flushRun();
        response.append(textPart(part.text, spec.current && index === lastTextIndex ? 'session-turn-content' : undefined));
    });
    flushRun();
    // A tool with no part (a replay that lost its start frame) must still show.
    const inTimeline = new Set(parts.filter(p => p.kind === 'tool').map(p => p.toolId));
    const orphans = spec.tools.filter(t => !inTimeline.has(t.id));
    if (orphans.length) {
        response.append(toolSection(orphans, host, openTools, closedTools, live, false, spec.clarify));
    }
    if (spec.assistantText && lastTextIndex < 0) {
        response.append(textPart(spec.assistantText, spec.current ? 'session-turn-content' : undefined));
    }
    if (spec.assistantText && !live) {
        response.append(copyButton(spec.assistantText, host));
    }
    return response;
}
// OpenCode user-message anatomy (message-part.css): a borderless bubble
// hugging the right edge — body max-width min(82%, 64ch), bubble padding
// 8px 12px / radius 10px — built as a named slot so the CSS layer and any
// future surface styling target the same shape.
function userMessage(text) {
    const bubbleText = element('span', 'crusorai-user-message-text', text);
    bubbleText.dataset.slot = 'user-message-text';
    const body = element('div', undefined, bubbleText);
    body.dataset.slot = 'user-message-body';
    const wrap = element('div', 'crusorai-user-message', body);
    wrap.dataset.component = 'user-message';
    return wrap;
}
function transcript(model, host, openTools, closedTools, liveThoughtSeconds) {
    const scroll = element('div', 'crusorai-transcript-scroll');
    const lane = element('div', 'crusorai-transcript-lane');
    // History: previous turns (user → agent) preserved wireframe style, no breathing
    for (const turn of model.history) {
        if (turn.userMessage)
            lane.append(userMessage(turn.userMessage));
        if (turn.assistantText || turn.parts.length || turn.tools.length) {
            lane.append(assistantTurn({
                reasoningParts: turn.reasoningParts,
                assistantText: turn.assistantText,
                parts: turn.parts,
                tools: turn.tools,
                live: false,
                turnKey: `history:${model.sessionId || 's'}`,
            }, host, openTools, closedTools));
        }
        if (turn.subAgents.length) {
            const subAgents = element('section', 'crusorai-subagent-list');
            subAgents.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'crusorai-section-count', String(turn.subAgents.length))));
            for (const subAgent of turn.subAgents) {
                const row = element('div', `crusorai-subagent-row is-${subAgent.state}`, element('span', undefined, ''), element('span', 'crusorai-subagent-goal', subAgent.goal ?? 'Sub-agent task'), element('span', `crusorai-subagent-state is-${subAgent.state}`, subAgent.state));
                if (subAgent.duration)
                    row.append(element('span', 'crusorai-subagent-duration', subAgent.duration));
                subAgents.append(row);
            }
            lane.append(subAgents);
        }
        // Hermes pattern: no green confetti for success -- the answer IS the
        // completion receipt. Only real deviations (cancelled, failed) get a row.
        if (turn.turnOutcome === 'cancelled' || turn.turnOutcome === 'failed') {
            const label = turn.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
            const iconName = turn.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
            const row = element('div', `crusorai-turn-receipt is-${turn.turnOutcome}`, icon(iconName), element('span', undefined, label));
            const intr = turn.interrupt;
            if (intr && (intr.landed > 0 || intr.dropped > 0)) {
                const bits = [];
                if (intr.landed > 0) {
                    bits.push(`${intr.landed} landed`);
                }
                if (intr.dropped > 0) {
                    bits.push(`${intr.dropped} dropped`);
                }
                row.append(element('span', 'crusorai-receipt-meta', `· ${bits.join(' · ')}`));
            }
            lane.append(row);
        }
        // same closing rollup for past turns (first-touched order, +/- summed)
        const turnFiles = deriveChangedFiles(turn.tools);
        if (turnFiles.length) {
            const card = element('div', 'crusorai-changed-files');
            card.dataset.component = 'changed-files';
            card.append(element('div', 'crusorai-changed-files-head', element('span', undefined, `${turnFiles.length} file${turnFiles.length === 1 ? '' : 's'} changed`)));
            const rows = element('div', 'crusorai-changed-files-rows');
            for (const file of turnFiles) {
                const row = element('div', 'crusorai-changed-file-row is-activatable show-file-icons', fileIcon(host, file.path), element('span', 'crusorai-changed-file-name', file.name), element('span', 'crusorai-diff-count', element('span', 'is-added', `+${file.added}`), element('span', 'is-removed', `−${file.removed}`)));
                row.title = file.path;
                const target = file.path;
                row.addEventListener('click', () => host.revealFile(target));
                rows.append(row);
            }
            card.append(rows);
            lane.append(card);
        }
    }
    // Current turn (breathing when running)
    if (model.userMessage) {
        lane.append(userMessage(model.userMessage));
    }
    // No assistant text means there is nothing to narrate. The line used to fall back to a sentence
    // claiming the agent was inspecting the workspace, which the turn had never done -- so a run that
    // died on a provider error still printed confident progress. The spinner and the 'Working' label
    // already say the only true thing: the turn is open.
    if (model.assistantText || model.reasoningParts.length || model.running || model.parts.length || model.tools.length) {
        lane.append(assistantTurn({
            reasoningParts: model.reasoningParts,
            assistantText: model.assistantText,
            parts: model.parts,
            tools: model.tools,
            live: model.running,
            current: true,
            thoughtSeconds: liveThoughtSeconds,
            cancelRequested: model.cancelRequested,
            clarify: model.clarify,
            turnKey: `current:${model.sessionId || 's'}`,
        }, host, openTools, closedTools));
    }
    if (model.subAgents.length) {
        const subAgents = element('section', 'crusorai-subagent-list');
        subAgents.dataset.component = 'subagent-list';
        subAgents.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'crusorai-section-count', String(model.subAgents.length))));
        for (const subAgent of model.subAgents) {
            const state = subAgent.state;
            const desc = subAgent.description ?? subAgent.goal ?? 'Sub-agent task';
            const childId = subAgent.childThreadId ?? subAgent.id;
            const isRunning = state === 'running' || state === 'pending';
            const row = element('div', `crusorai-subagent-row is-${state}${childId ? ' is-clickable' : ''}`);
            if (childId) {
                row.dataset.sessionId = childId;
                row.tabIndex = 0;
                row.setAttribute('role', 'button');
                row.addEventListener('click', () => { if (host.navigateToSession)
                    host.navigateToSession(childId); });
                row.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    if (host.navigateToSession)
                        host.navigateToSession(childId);
                } });
            }
            const iconEl = isRunning ? element('span', 'crusorai-mini-spinner') : icon(state === 'completed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'cancelled' ? 'circle-slash' : 'circle-outline');
            const goalEl = element('span', 'crusorai-subagent-goal', desc);
            goalEl.style.setProperty('--task-agent-color', agentColor(subAgent.agentName ?? subAgent.mode ?? 'general'));
            row.append(iconEl, goalEl, element('span', `crusorai-subagent-state is-${state}`, state));
            if (subAgent.background)
                row.append(element('span', 'crusorai-subagent-badge', 'bg'));
            if (subAgent.toolCalls)
                row.append(element('span', 'crusorai-subagent-calls', `${subAgent.toolCalls} calls`));
            if (subAgent.duration)
                row.append(element('span', 'crusorai-subagent-duration', subAgent.duration));
            if (childId)
                row.append(element('span', 'crusorai-subagent-action', icon('arrow-up-right')));
            subAgents.append(row);
        }
        lane.append(subAgents);
    }
    if (model.turnOutcome === 'cancelled' || model.turnOutcome === 'failed') {
        const label = model.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
        const iconName = model.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
        const row = element('div', `crusorai-turn-receipt is-${model.turnOutcome}`, icon(iconName), element('span', undefined, label));
        const intr = model.interrupt;
        if (intr && (intr.landed > 0 || intr.dropped > 0)) {
            const bits = [];
            if (intr.landed > 0) {
                bits.push(`${intr.landed} landed`);
            }
            if (intr.dropped > 0) {
                bits.push(`${intr.dropped} dropped`);
            }
            row.append(element('span', 'crusorai-receipt-meta', `· ${bits.join(' · ')}`));
        }
        lane.append(row);
    }
    // hermes changed-files-card: the turn-closing "N files changed" rollup.
    const changed = changedFilesCard(model, host);
    if (changed) {
        lane.append(changed);
    }
    if (model.voiceHeard) {
        const heard = model.voiceHeard;
        if (heard.ok) {
            lane.append(element('div', 'crusorai-context-status-row is-info', icon('lightbulb'), element('span', undefined, `\u{1F3A4} Heard: ${heard.text.slice(0, 200)}`)));
        }
        else {
            lane.append(element('div', 'crusorai-context-status-row is-warning', icon('warning'), element('span', undefined, `\u{1F3A4} Voice error: ${heard.error ?? 'unknown'}`)));
        }
    }
    if (model.degraded) {
        lane.append(element('div', 'crusorai-context-status-row is-warning', icon('warning'), element('span', undefined, model.degraded)));
    }
    // OpenCode streamed response (founder direction 2026-10-15, replacing
    // the whole breathing/wait apparatus): NO Asking row, NO model name,
    // NO elapsed timers, NO anatomy line in the chat. The turn renders as
    // its parts arrive; before the first part lands, the only mark is the
    // bare shimmering word "Thinking". Once reasoning, tools, or text
    // stream, they carry the wait themselves.
    if (model.running && !model.llmReasoningLive) {
        const liveTool = [...model.tools].reverse().find(tool => tool.state === 'running' || tool.state === 'queued');
        const lastPart = model.parts[model.parts.length - 1];
        if (!liveTool && lastPart?.kind !== 'text' && !model.assistantText) {
            lane.append(element('div', 'crusorai-thinking-wait', element('strong', 'crusorai-shimmer crusorai-thinking-word', 'Thinking')));
        }
        if (model.stalled) {
            lane.append(element('div', 'crusorai-context-status-row is-warning', element('span', undefined, 'No activity for a while — the turn is still running, but nothing has arrived.')));
        }
    }
    if (model.contextStatus) {
        const status = model.contextStatus;
        const percent = typeof status.usagePercent === 'number' && status.usagePercent > 0
            ? ` (${Math.min(100, Math.round(status.usagePercent))}% of the context window)`
            : '';
        lane.append(element('div', `crusorai-context-status-row is-${status.severity}`, icon(status.severity === 'warning' ? 'warning' : 'lightbulb'), element('span', undefined, status.message + percent)));
    }
    if (model.engineFault) {
        const fault = model.engineFault;
        const followUp = fault.retrying
            ? ` Retrying automatically (attempt ${fault.attempts + 1} of 3).`
            : ' Crusor stopped retrying on its own.';
        lane.append(element('div', 'crusorai-error-row is-engine-fault', icon('error'), element('span', undefined, fault.message + followUp), button('Retry engine', 'crusorai-link-button', host.retryEngine)));
    }
    if (model.error) {
        const setup = model.engineSetupError;
        lane.append(element('div', 'crusorai-error-row', icon(setup ? 'settings-gear' : 'warning'), element('span', undefined, setup ? `Crusor engine setup: ${model.error}` : model.error), setup
            ? button('Open Settings', 'crusorai-link-button', host.openEngineSettings, 'settings-gear')
            : button('Retry', 'crusorai-link-button', host.retryEngine)));
    }
    // OpenCode parity: child header parent / child + agent-designed prompt as user message
    if (model.isChild) {
        const delegatedTask = model.userMessage || model.subAgentGoal || '';
        const parentTitle = model.parentTitle || 'Parent session';
        const childTitle = delegatedTask.slice(0, 60) || 'Sub-agent';
        // Header like opencode: Spawn agents to analyze folders / Analyze playground folder
        const header = element('div', 'crusorai-child-header');
        const parentBtn = element('button', 'crusorai-child-header-parent', parentTitle);
        if (model.parentSessionId && host.navigateToSession) {
            const pId = model.parentSessionId;
            parentBtn.addEventListener('click', () => host.navigateToSession(pId));
        }
        header.append(parentBtn, element('span', undefined, ' / '), element('h1', 'crusorai-child-header-child', childTitle));
        lane.prepend(header);
        if (delegatedTask) {
            lane.append(userMessage(delegatedTask.slice(0, 800)));
        }
        const banner = element('div', 'crusorai-child-banner');
        banner.dataset.component = 'child-banner';
        banner.append(icon('info'), element('span', undefined, 'Sub-agent session — prompt disabled'));
        if (model.parentSessionId && host.navigateToSession) {
            const parentId = model.parentSessionId;
            banner.append(button('Back to Parent', 'crusorai-link-button', () => host.navigateToSession(parentId), 'arrow-left'));
        }
        lane.append(banner);
    }
    scroll.append(lane);
    return scroll;
}
/**
 * The empty-session predicate: genuinely nothing to render and nothing
 * broken — engine up, workspace chosen, no turn yet. Setup and
 * workspace-selection states have their own surfaces.
 */
function isEmptySession(model) {
    if (model.running || model.history.length || model.userMessage || model.assistantText || model.tools.length) {
        return false;
    }
    if (model.engineSetupError || model.noWorkspace || model.workspaceSelectionRequired) {
        return false;
    }
    return true;
}
/**
 * OpenCode's empty session (founder direction 2026-10-15): NO starter
 * cards, NO explainer paragraph — their session page rests on the mark
 * alone with the prompt dock as the hero (DockPrompt: the dock IS the
 * page until the first message lands). The Agent pane centres the dock
 * under this mark (see renderAgent's is-empty shell); the Manager keeps
 * its bottom composer and this hero simply centres above it.
 */
function emptyState(model, host) {
    if (!isEmptySession(model)) {
        return undefined;
    }
    const wrap = element('section', 'crusorai-empty-state');
    wrap.dataset.component = 'empty-state';
    const hero = element('div', 'crusorai-empty-hero');
    hero.append(icon('crusor'), element('span', 'crusorai-empty-wordmark', 'Crusor'));
    wrap.append(hero);
    return wrap;
}
function approvalDock(model, host) {
    if (!model.approval) {
        return undefined;
    }
    const approval = model.approval;
    ensureGlobalCardKeys();
    const dock = element('section', 'crusorai-approval-dock');
    dock.dataset.component = 'approval-dock';
    dock.dataset.toolId = approval.toolId;
    // OpenCode permission dock (captured session-permission-dock.tsx,
    // founder direction 2026-10-15): a DockPrompt-shaped card — shield
    // header "Permission required", the tool description, the resource
    // patterns as code rows (ours: the real command, or the diff preview),
    // and the footer Deny | Allow always | Allow once. Allow always passes
    // through a confirm dialog; the keyboard contract (⌘/Ctrl+Enter once,
    // Esc deny) is unchanged.
    const commandText = approvalCommandText(approval.name, approval.diff);
    const diffRecord = (approval.diff && typeof approval.diff === 'object') ? approval.diff : undefined;
    const diffString = typeof approval.diff === 'string' ? approval.diff : (typeof diffRecord?.diff === 'string' ? diffRecord.diff : undefined);
    const diffStatistics = diffString ? diffStats(diffString) : undefined;
    const isShell = approval.name === 'run_terminal' || approval.name === 'start_terminal' || approval.name === 'terminal' || approval.name === 'execute_code' || diffRecord?.kind === 'shell';
    let inlineDiffCard;
    if (diffString) {
        const targetPath = (diffRecord && (diffRecord.relative_path || diffRecord.path))
            ? String(diffRecord.relative_path || diffRecord.path)
            : displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff });
        const action = typeof diffRecord?.action === 'string' ? diffRecord.action : 'modify';
        const actionLabel = action === 'create' ? 'Create' : action === 'delete' ? 'Delete' : action === 'copy' ? 'Copy' : 'Edit';
        const header = element('div', 'crusorai-approval-diff-header', element('span', 'crusorai-approval-action-badge', actionLabel), element('span', 'crusorai-approval-file-path', targetPath));
        if (diffStatistics) {
            const count = element('span', 'crusorai-diff-count');
            if (diffStatistics.added > 0) {
                count.append(element('span', 'is-added', `+${diffStatistics.added}`));
            }
            if (diffStatistics.removed > 0) {
                count.append(element('span', 'is-removed', `−${diffStatistics.removed}`));
            }
            header.append(count);
        }
        inlineDiffCard = element('div', 'crusorai-approval-diff-preview', header, diffPreview(diffString));
    }
    let warningBox;
    if (approval.warning) {
        warningBox = element('div', 'crusorai-approval-warning', icon('shield'), element('span', undefined, approval.warning));
    }
    let shellRiskBadge;
    if (isShell) {
        const riskText = typeof diffRecord?.risk === 'string' ? diffRecord.risk : undefined;
        if (riskText) {
            shellRiskBadge = element('div', 'crusorai-approval-risk-badge', icon('shield'), element('span', undefined, riskText));
        }
    }
    const runButton = button('Allow once', 'crusorai-permission-once', () => host.replyToSafety(approval.toolId, true), 'check');
    runButton.dataset.approveOnce = '';
    hinted(runButton, 'Allow this call only.');
    const runHint = element('span', 'crusorai-approval-kbd', isMac() ? '⌘⏎' : 'Ctrl⏎');
    runButton.append(runHint);
    // OpenCode permission dock footer (captured session-permission-dock):
    // Deny (ghost) | Allow always (neutral, behind our confirm dialog — the
    // grant is session-scoped in our backend) | Allow once (primary).
    const alwaysButton = button('Allow always', 'crusorai-permission-always', () => overlay.classList.add('is-open'), 'shield');
    hinted(alwaysButton, 'Stop asking for this tool this session.');
    const reject = hinted(button('Deny', 'crusorai-permission-deny', () => host.replyToSafety(approval.toolId, false), 'close'), 'Deny this call. The next write is asked about again.');
    reject.dataset.deny = '';
    const rejectHint = element('span', 'crusorai-approval-kbd', 'Esc');
    reject.append(rejectHint);
    const permissionFooter = element('div', 'crusorai-permission-footer', reject, alwaysButton, runButton);
    // "Always allow" persists for the session, so it goes through a confirm
    // step rather than firing straight from the menu (hermes' dialog rule).
    const overlay = element('div', 'crusorai-dialog-overlay');
    const dialog = element('div', 'crusorai-dialog');
    dialog.append(element('h3', undefined, 'Always allow this?'), element('p', 'crusorai-dialog-copy', `Crusor will stop asking before running ${crusorAIToolPresentation(approval.name).title} for the rest of this session. Secret paths and git-ignored files are still asked every time.`));
    // append() takes (string | Node)[] — a ternary undefined arg is a type
    // error, so the optional command preview appends conditionally.
    if (commandText) {
        dialog.append(element('pre', 'crusorai-dialog-command', commandText));
    }
    const dialogButtons = element('div', 'crusorai-dialog-actions');
    dialogButtons.append(button('Cancel', 'crusorai-button crusorai-button-secondary', () => overlay.classList.remove('is-open')), button('Always allow', 'crusorai-button crusorai-button-primary', () => {
        overlay.classList.remove('is-open');
        host.replyToSafety(approval.toolId, true, true);
    }));
    dialog.append(dialogButtons);
    overlay.append(dialog);
    overlay.addEventListener('click', event => { if (event.target === overlay)
        overlay.classList.remove('is-open'); });
    // OpenCode permission dock assembly (DockPrompt kind=permission):
    // header (icon + "Permission required" + what tool) -> hint rows ->
    // resource patterns / content (their code rows; ours: the real command
    // or the diff) -> footer actions.
    dock.dataset.kind = 'permission';
    const headerRow = element('div', 'crusorai-permission-header', element('span', 'crusorai-permission-icon', icon('shield')), element('div', undefined, element('strong', undefined, 'Permission required'), element('span', 'crusorai-permission-subtitle', `${crusorAIToolPresentation(approval.name).title} · ${displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff })}`)), approval.diff ? button('Review change', 'crusorai-approval-review', () => host.openDiff(approval.toolId), 'diff') : undefined);
    dock.append(headerRow);
    if (warningBox) {
        dock.append(warningBox);
    }
    if (shellRiskBadge) {
        dock.append(shellRiskBadge);
    }
    if (inlineDiffCard) {
        dock.append(inlineDiffCard);
    }
    else if (commandText) {
        const patterns = element('div', 'crusorai-permission-patterns');
        patterns.append(element('code', undefined, commandText));
        dock.append(patterns);
    }
    dock.append(permissionFooter);
    dock.append(overlay);
    return dock;
}
function isMac() {
    return typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.platform);
}
function approvalCommandText(name, diff) {
    const row = (diff && typeof diff === 'object') ? diff : {};
    for (const key of ['command', 'cmd', 'path', 'file_path']) {
        const value = row[key];
        if (typeof value === 'string' && value.trim()) {
            return value.trim();
        }
    }
    if (diff === undefined || diff === null) {
        return name;
    }
    try {
        return `${name} ${JSON.stringify(diff)}`.trim();
    }
    catch {
        return name;
    }
}
// ── Hermes clarify card (the ask tool) ───────────────────────────────────────
// Port of apps/desktop/src/components/assistant-ui/clarify-tool.tsx: a widget
// card — the interactive batch form while the turn blocks, the settled Q&A
// after, and a skipped card whose choices draft a follow-up instead of
// vanishing. Draft state lives OUTSIDE the render (keyed by request id), the
// same way `openTools` survives re-renders.
const RECOMMENDED_LABEL = '(Recommended)';
const clarifyDrafts = new Map();
function clarifyDraft(requestId) {
    let draft = clarifyDrafts.get(requestId);
    if (!draft) {
        draft = { selected: new Map(), other: new Map(), cursor: 0 };
        clarifyDrafts.set(requestId, draft);
    }
    return draft;
}
function parseClarifyResult(raw) {
    if (typeof raw !== 'string') {
        return { responses: [], timedOut: false };
    }
    try {
        const parsed = JSON.parse(raw);
        if (typeof parsed.error === 'string') {
            return { responses: [], timedOut: false, error: parsed.error };
        }
        const responses = [];
        const list = Array.isArray(parsed.responses) ? parsed.responses : [parsed];
        for (const entry of list) {
            if (entry && typeof entry === 'object') {
                responses.push(entry);
            }
        }
        return { responses, timedOut: parsed.timed_out === true };
    }
    catch {
        return { responses: [], timedOut: false };
    }
}
function letterFor(index) {
    return String.fromCharCode(97 + index);
}
function keyBadge(char, selected) {
    const badge = element('span', `crusorai-key-badge${selected ? ' is-selected' : ''}`, char);
    badge.setAttribute('aria-hidden', 'true');
    return badge;
}
/** Split "Use React (Recommended)" into [bare, recommended?] the way the
 * ChoiceLabel renders it: the suffix is presentation, tertiary-toned. */
function choiceParts(choice) {
    const trimmed = String(choice ?? '').trim();
    if (trimmed.toLowerCase().endsWith(RECOMMENDED_LABEL.toLowerCase())) {
        return { bare: trimmed.slice(0, -RECOMMENDED_LABEL.length).trim(), recommended: true };
    }
    return { bare: trimmed, recommended: false };
}
function clarifyChoiceRow(qid, index, choice, multi, draft, requestId, onDirty) {
    const { bare, recommended } = choiceParts(choice);
    const picked = draft.selected.get(qid)?.has(bare) ?? false;
    const row = element('button', `crusorai-clarify-choice${picked ? ' is-selected' : ''}`);
    row.type = 'button';
    row.dataset.choiceIndex = String(index);
    row.dataset.qid = qid;
    row.dataset.choice = bare;
    row.setAttribute('aria-pressed', String(picked));
    // OpenCode question-option mark (captured session-question-dock):
    // radio dot for single-select, checkbox for multi-select.
    const mark = element('span', 'crusorai-question-mark');
    mark.dataset.type = multi ? 'checkbox' : 'radio';
    mark.setAttribute('aria-hidden', 'true');
    row.append(mark, keyBadge(letterFor(index), picked));
    const label = element('span', 'crusorai-clarify-choice-label');
    label.append(document.createTextNode(bare));
    if (recommended) {
        label.append(element('span', 'crusorai-clarify-recommended', ` ${RECOMMENDED_LABEL}`));
    }
    row.append(label);
    row.addEventListener('click', () => {
        const set = draft.selected.get(qid) ?? new Set();
        if (multi) {
            if (set.has(bare)) {
                set.delete(bare);
                row.classList.remove('is-selected');
                row.setAttribute('aria-pressed', 'false');
            }
            else {
                set.add(bare);
                row.classList.add('is-selected');
                row.setAttribute('aria-pressed', 'true');
            }
            draft.selected.set(qid, set);
            return;
        }
        // Single select: one picked row per question; picking clears siblings.
        set.clear();
        set.add(bare);
        draft.selected.set(qid, set);
        draft.other.set(qid, '');
        const form = row.closest('.crusorai-clarify-form');
        for (const other of (form?.querySelectorAll(`[data-qid="${qid}"].crusorai-clarify-choice`) ?? [])) {
            const isThis = other === row;
            other.classList.toggle('is-selected', isThis);
            other.setAttribute('aria-pressed', String(isThis));
        }
        const textarea = form?.querySelector(`textarea[data-qid="${qid}"]`);
        if (textarea) {
            textarea.value = '';
        }
        onDirty();
    });
    return row;
}
function clarifyCard(tool, host, _openTools, closedTools, pending) {
    ensureGlobalCardKeys();
    // Settled: the tool result carries the batch JSON — Q/A card, hermes
    // ClarifyToolSettled. A skipped card keeps its choices clickable; a pick
    // drafts a quoted follow-up into the composer (Enter sends, a running turn
    // queues it like any other prompt).
    if (tool.result !== undefined) {
        const { responses, timedOut, error } = parseClarifyResult(tool.result);
        const card = element('div', 'crusorai-clarify-card');
        card.dataset.component = 'clarify-settled';
        const skipped = !error && responses.length > 0 && responses.every(r => {
            const value = r.user_response;
            return value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
        });
        for (const response of responses) {
            card.append(element('div', 'crusorai-clarify-q', icon('question'), element('span', undefined, response.question ?? '')));
            const answer = response.user_response;
            const answerText = error
                ? error
                : skipped ? 'Skipped'
                    : Array.isArray(answer) ? answer.join(', ')
                        : (typeof answer === 'string' ? answer : '').trim();
            if (answerText) {
                card.append(element('div', `crusorai-clarify-a${error ? ' is-error' : ''}${skipped ? ' is-skipped' : ''}`, element('span', 'crusorai-clarify-a-badge', 'A'), element('span', undefined, answerText)));
            }
            if (timedOut || skipped) {
                const choices = response.choices_offered ?? [];
                if (choices.length) {
                    const late = element('div', 'crusorai-clarify-late');
                    choices.forEach((choice, index) => {
                        const { bare } = choiceParts(choice);
                        const row = element('button', 'crusorai-clarify-choice');
                        row.type = 'button';
                        row.append(keyBadge(letterFor(index), false), element('span', 'crusorai-clarify-choice-label', bare));
                        row.addEventListener('click', () => {
                            // Hermes late-answer: a pick can't resolve the dead
                            // request — it drafts a quoted follow-up instead.
                            host.setDraft(`Re: "${response.question ?? 'your question'}" — ${bare}`);
                        });
                        late.append(row);
                    });
                    late.append(element('p', 'crusorai-clarify-late-hint', 'The turn moved on — pick one to draft a follow-up instead.'));
                    card.append(late);
                }
            }
        }
        return card;
    }
    // Pending: the interactive batch form (hermes ClarifyToolSinglePending /
    // ClarifyToolBatchPending). Args alone can't drive it — the request frame
    // carries the qids the reply needs.
    const draft = clarifyDraft(pending.requestId);
    const form = element('div', 'crusorai-clarify-card crusorai-clarify-form');
    form.dataset.component = 'clarify-inline';
    form.dataset.live = '1';
    form.dataset.requestId = pending.requestId;
    const collectAnswers = () => {
        const answers = {};
        for (const question of pending.questions) {
            const other = draft.other.get(question.qid) ?? '';
            if (other.trim()) {
                answers[question.qid] = other.trim();
                continue;
            }
            const picked = Array.from(draft.selected.get(question.qid) ?? []);
            if (picked.length === 1) {
                answers[question.qid] = picked[0];
            }
            else if (picked.length > 1) {
                answers[question.qid] = picked;
            }
        }
        return answers;
    };
    const submitButton = element('button', 'crusorai-button crusorai-button-primary crusorai-clarify-submit');
    submitButton.type = 'button';
    submitButton.dataset.clarifySubmit = '';
    submitButton.append('Continue', element('span', 'crusorai-approval-kbd', '⏎'));
    submitButton.addEventListener('click', () => {
        form.dataset.live = '0';
        host.replyToClarify(pending.requestId, collectAnswers(), false);
    });
    const skipButton = element('button', 'crusorai-button crusorai-button-secondary crusorai-clarify-skip');
    skipButton.type = 'button';
    skipButton.textContent = 'Skip';
    skipButton.addEventListener('click', () => {
        form.dataset.live = '0';
        // Hermes skip: the batch resolves EMPTY — a deliberate skip the model
        // reads as "" answers, distinct from a walk-away timeout.
        host.replyToClarify(pending.requestId, {}, false);
    });
    for (const question of pending.questions) {
        const multi = question.multi_select === true;
        const block = element('div', 'crusorai-clarify-block');
        block.append(element('div', 'crusorai-clarify-q', icon('question'), element('span', undefined, question.question)));
        const choices = question.choices ?? [];
        if (choices.length) {
            const group = element('div', 'crusorai-clarify-choices');
            group.setAttribute('role', 'group');
            choices.forEach((choice, index) => {
                group.append(clarifyChoiceRow(question.qid, index, choice, multi, draft, pending.requestId, () => refreshSubmit()));
            });
            // The auto-appended "Other (type your answer)" row — hermes: the UI
            // always appends it; typing is its own answer and clears picks.
            const otherRow = element('label', 'crusorai-clarify-other');
            otherRow.dataset.choiceIndex = String(choices.length);
            otherRow.dataset.qid = question.qid;
            otherRow.append(keyBadge(letterFor(choices.length), false));
            const textarea = element('textarea', 'crusorai-clarify-other-input');
            textarea.rows = 1;
            textarea.placeholder = 'Other (type your answer)';
            textarea.dataset.qid = question.qid;
            textarea.value = draft.other.get(question.qid) ?? '';
            textarea.addEventListener('input', () => {
                draft.other.set(question.qid, textarea.value);
                if (textarea.value.trim()) {
                    draft.selected.set(question.qid, new Set());
                    for (const row of form.querySelectorAll(`[data-qid="${question.qid}"].crusorai-clarify-choice`)) {
                        row.classList.remove('is-selected');
                        row.setAttribute('aria-pressed', 'false');
                    }
                }
                refreshSubmit();
            });
            otherRow.append(textarea);
            group.append(otherRow);
            block.append(group);
        }
        else {
            const textarea = element('textarea', 'crusorai-clarify-other-input crusorai-clarify-open');
            textarea.rows = 2;
            textarea.placeholder = 'Type your answer…';
            textarea.dataset.qid = question.qid;
            textarea.value = draft.other.get(question.qid) ?? '';
            textarea.addEventListener('input', () => { draft.other.set(question.qid, textarea.value); refreshSubmit(); });
            block.append(textarea);
        }
        form.append(block);
    }
    function refreshSubmit() {
        const answers = collectAnswers();
        const hasAnswer = Object.keys(answers).length > 0;
        submitButton.disabled = !hasAnswer;
    }
    refreshSubmit();
    const actions = element('div', 'crusorai-clarify-actions', skipButton, submitButton);
    form.append(actions);
    return form;
}
// ── Hermes todo panel (the task tool) ────────────────────────────────────────
// Port of the composer status stack's todo rows (status-row.tsx): checkbox
// glyphs, not spinner-and-dot — a dashed ring while pending, codicons once the
// item resolves, a live spinner only on the in_progress item; depth-indented
// subtasks; an X/Y count. Rendered ABOVE the composer, like upstream.
let todoStackExpanded = false;
function todoStack(model) {
    const todos = model.todos;
    if (!todos.length) {
        return undefined;
    } // hermes: no active list, no panel
    const counted = todos.filter(t => t.status !== 'cancelled');
    const done = counted.filter(t => t.status === 'completed').length;
    const active = todos.find(t => t.status === 'in_progress') || todos.find(t => t.status !== 'completed' && t.status !== 'cancelled');
    const stack = element('section', 'crusorai-todo-stack');
    stack.dataset.component = 'todo-stack';
    const caret = icon(todoStackExpanded ? 'chevron-down' : 'chevron-right');
    const previewSpan = active ? element('span', 'crusorai-todo-active-preview', `· ${active.content}`) : undefined;
    if (previewSpan && todoStackExpanded) {
        previewSpan.style.display = 'none';
    }
    const heading = element('div', 'crusorai-todo-header', icon('list-ordered'), element('strong', 'crusorai-todo-title', 'Tasks'), element('span', 'crusorai-section-count', `${done}/${counted.length}`), previewSpan, element('span', 'crusorai-todo-caret', caret));
    heading.addEventListener('click', () => {
        todoStackExpanded = !todoStackExpanded;
        list.classList.toggle('is-hidden', !todoStackExpanded);
        const caretHost = heading.querySelector('.crusorai-todo-caret');
        if (caretHost) {
            caretHost.replaceChildren(icon(todoStackExpanded ? 'chevron-down' : 'chevron-right'));
        }
        if (previewSpan) {
            previewSpan.style.display = todoStackExpanded ? 'none' : 'inline';
        }
    });
    stack.append(heading);
    const list = element('div', `crusorai-todo-list${todoStackExpanded ? '' : ' is-hidden'}`);
    for (const todo of todos) {
        const depth = todoDepth(todo, todos);
        const glyph = todoGlyph(todo.status);
        const row = element('div', `crusorai-todo-row is-${todo.status}`);
        if (depth) {
            row.style.paddingLeft = `${Math.min(depth, 4) * 0.8}rem`;
        }
        row.append(glyph, element('span', 'crusorai-todo-content', todo.content));
        list.append(row);
    }
    stack.append(list);
    return stack;
}
function todoDepth(todo, todos) {
    let depth = 0;
    let current = todo;
    const byId = new Map(todos.map(t => [t.id, t]));
    while (current.parent && byId.has(current.parent) && current.parent !== current.id && depth < 4) {
        current = byId.get(current.parent);
        depth += 1;
    }
    return depth;
}
function todoGlyph(status) {
    if (status === 'in_progress') {
        return element('span', 'crusorai-mini-spinner');
    }
    if (status === 'completed') {
        return icon('pass-filled');
    }
    if (status === 'cancelled') {
        return icon('circle-slash');
    }
    // Pending: a dashed ring — the row speaks checkbox, not spinner-and-dot.
    const ring = element('span', 'crusorai-todo-ring');
    ring.setAttribute('aria-hidden', 'true');
    return ring;
}
// ── Global card keys ─────────────────────────────────────────────────────────
// One capture-phase listener, installed once (hermes' window keydown in
// ClarifyToolSinglePending + ApprovalBar): ⌘/Ctrl+Enter runs the approval,
// Esc rejects it; letters/numbers/arrows/Enter drive the live clarify card.
// The DOM is the state — a re-render between keystrokes cannot desync us.
let globalCardKeysInstalled = false;
function ensureGlobalCardKeys() {
    if (globalCardKeysInstalled || typeof document === 'undefined') {
        return;
    }
    globalCardKeysInstalled = true;
    document.addEventListener('keydown', (event) => {
        const dock = document.querySelector('[data-component="approval-dock"][data-tool-id]');
        if (dock) {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                dock.querySelector('[data-approve-once]')?.click();
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                dock.querySelector('[data-deny]')?.click();
                return;
            }
        }
        const form = document.querySelector('.crusorai-clarify-form[data-live="1"]');
        // Esc pulls the Stop button — the composer hint advertises it, and a
        // stop is one pull with nothing in the way. A live clarify question
        // keeps its own Escape (deny/close), and the approval dock above
        // already consumed Escape for deny before we get here.
        if (event.key === 'Escape' && !event.defaultPrevented && !event.metaKey && !event.ctrlKey && !event.altKey && !form) {
            const stop = document.querySelector('.crusorai-send-stop:not([disabled])');
            if (stop) {
                event.preventDefault();
                event.stopPropagation();
                stop.click();
                return;
            }
        }
        if (!form || event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) {
            return;
        }
        const active = document.activeElement;
        if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT' || active.isContentEditable)) {
            return;
        }
        const rows = Array.from(form.querySelectorAll('[data-choice-index]'));
        if (!rows.length) {
            return;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const delta = event.key === 'ArrowDown' ? 1 : -1;
            const current = rows.findIndex(row => row.classList.contains('is-active'));
            const next = Math.max(0, Math.min(rows.length - 1, (current === -1 ? 0 : current + delta)));
            rows.forEach((row, index) => row.classList.toggle('is-active', index === next));
            return;
        }
        if (/^[1-9]$/.test(event.key)) {
            const row = rows[Number(event.key) - 1];
            if (row) {
                event.preventDefault();
                row.classList.add('is-active');
                row.click?.();
            }
            return;
        }
        const key = event.key.toLowerCase();
        if (key.length === 1 && key >= 'a' && key <= 'z') {
            const row = rows[key.charCodeAt(0) - 97];
            if (row) {
                event.preventDefault();
                row.classList.add('is-active');
                if (row.click) {
                    row.click();
                }
                else {
                    row.querySelector('textarea')?.focus();
                }
            }
            return;
        }
        if (event.key === 'Enter') {
            const activeRow = rows.find(row => row.classList.contains('is-active'));
            if (activeRow) {
                event.preventDefault();
                if (activeRow.click) {
                    activeRow.click();
                }
                else {
                    activeRow.querySelector('textarea')?.focus();
                }
                return;
            }
            const submit = form.querySelector('[data-clarify-submit]');
            if (submit && !submit.disabled) {
                event.preventDefault();
                submit.click();
            }
        }
    }, true);
}
/** A `title` hint for buttons built through `button()`, which has no options bag. */
function hinted(control, hint) {
    control.title = hint;
    return control;
}
/**
 * Line counts for a unified diff, counted -- not assumed. Returns undefined when the
 * payload carries no +/- body at all, so callers can show '—' instead of a number.
 */
export function diffStats(diff) {
    if (!diff) {
        return undefined;
    }
    let added = 0;
    let removed = 0;
    for (const line of diff.split('\n')) {
        if (line.startsWith('+++') || line.startsWith('---')) {
            continue;
        }
        if (line.startsWith('+')) {
            added++;
        }
        else if (line.startsWith('-')) {
            removed++;
        }
    }
    return added || removed ? { added, removed } : undefined;
}
/** Lines are clamped for *paint*, never for correctness -- the count says what is hidden. */
const DIFF_PREVIEW_LINE_LIMIT = 40;
// hermes diff-lines.tsx wireframe, ported: file-headers + `@@` hunk noise and
// the +/- gutter are DROPPED -- changes read by tint + a 2px gutter accent,
// rows flush to the card edges, the box scrolls like a code block.
function diffPreview(diff) {
    const wrap = element('div', 'crusorai-diff-body');
    const parsed = parseDiff(diff || '');
    const shown = parsed.slice(0, DIFF_PREVIEW_LINE_LIMIT);
    for (const line of shown) {
        const row = element('span', `crusorai-diff-row is-${line.kind}`, line.text.length ? line.text : ' ');
        if (line.newNo !== undefined) {
            row.dataset.newNo = String(line.newNo);
        }
        if (line.oldNo !== undefined) {
            row.dataset.oldNo = String(line.oldNo);
        }
        wrap.append(row);
    }
    if (parsed.length > DIFF_PREVIEW_LINE_LIMIT) {
        wrap.append(element('div', 'crusorai-diff-row is-truncated', `… ${parsed.length - DIFF_PREVIEW_LINE_LIMIT} more line(s)`));
    }
    return wrap;
}
// hermes terminal-output.tsx + lib/ansi.ts: bounded tail (paint, not
// correctness) with SGR-colored segments; plain text when there is no ANSI.
const TERMINAL_PAINT_LINE_LIMIT = 400;
function terminalOutputContent(output, running) {
    const pre = element('pre', 'crusorai-terminal-output');
    const text = output || (running ? 'Waiting for output...' : 'No captured output');
    const windowed = windowedTailLines(text, TERMINAL_PAINT_LINE_LIMIT);
    if (windowed.hidden > 0) {
        pre.append(element('div', 'crusorai-terminal-earlier', `… ${windowed.hidden} earlier line(s) — full history stays in the run log`));
    }
    const body = windowed.lines.join('\n');
    if (!hasAnsiCodes(body)) {
        pre.append(document.createTextNode(body));
        return pre;
    }
    let line;
    for (const segment of parseAnsi(body)) {
        if (!line) {
            line = element('span', 'crusorai-ansi-line');
            pre.append(line);
        }
        const span = element('span', segment.fg ? `crusorai-ansi-${segment.fg}` : undefined, segment.text);
        if (segment.bold) {
            span.classList.add('is-bold');
        }
        // hermes ansi segments carry embedded \n — split into rows
        const parts = segment.text.split('\n');
        for (let i = 0; i < parts.length; i += 1) {
            if (i > 0) {
                line = element('span', 'crusorai-ansi-line');
                pre.append(line);
            }
            if (parts[i]) {
                line.append(element('span', segment.fg ? `crusorai-ansi-${segment.fg}` : undefined, parts[i]));
            }
        }
    }
    return pre;
}
// hermes changed-files-card.tsx: the turn-closing "N files changed" rollup —
// one row per LANDED file edit, +/- summed, click opens the file. Wears the
// shared widget chrome so it reads as the transcript's other inline widgets.
function changedFilesCard(model, host) {
    const files = deriveChangedFiles(model.tools);
    if (!files.length) {
        return undefined;
    }
    const card = element('div', 'crusorai-changed-files');
    card.dataset.component = 'changed-files';
    card.append(element('div', 'crusorai-changed-files-head', element('span', undefined, `${files.length} file${files.length === 1 ? '' : 's'} changed`)));
    const rows = element('div', 'crusorai-changed-files-rows');
    for (const file of files) {
        const row = element('div', 'crusorai-changed-file-row show-file-icons');
        row.append(fileIcon(host, file.path), element('span', 'crusorai-changed-file-name', file.name), element('span', 'crusorai-diff-count', element('span', 'is-added', `+${file.added}`), element('span', 'is-removed', `−${file.removed}`)));
        row.title = file.path;
        row.classList.add('is-activatable');
        row.addEventListener('click', () => host.revealFile(file.path));
        rows.append(row);
    }
    card.append(rows);
    return card;
}
const executionModes = [
    { id: 'agent', label: 'Agent', description: 'Build, change, and verify', icon: 'infinity' },
    { id: 'plan', label: 'Plan', description: 'Design before execution', icon: 'list-ordered' },
    { id: 'debug', label: 'Debug', description: 'Diagnose, fix, and retest', icon: 'debug-alt' },
    { id: 'ask', label: 'Ask', description: 'Explain without using tools', icon: 'comment' },
];
function modePicker(model, host) {
    const selected = executionModes.find(mode => mode.id === model.mode) ?? executionModes[0];
    const details = element('details', 'crusorai-mode-picker');
    const summary = element('summary', 'crusorai-mode-summary', icon(selected.icon), element('span', undefined, selected.label), icon('chevron-down'));
    summary.setAttribute('aria-label', `Execution mode: ${selected.label}`);
    if (model.running) {
        summary.setAttribute('aria-disabled', 'true');
        summary.addEventListener('click', event => event.preventDefault());
    }
    const menu = element('div', 'crusorai-mode-menu');
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Execution mode');
    for (const mode of executionModes) {
        const item = element('button', mode.id === selected.id ? 'crusorai-mode-option is-selected' : 'crusorai-mode-option', icon(mode.icon), element('span', 'crusorai-mode-option-copy', element('strong', undefined, mode.label), element('small', undefined, mode.description)), mode.id === selected.id ? icon('check') : undefined);
        item.type = 'button';
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(mode.id === selected.id));
        item.addEventListener('click', () => {
            details.open = false;
            host.setMode(mode.id);
        });
        menu.append(item);
    }
    details.append(summary, menu);
    return details;
}
// hermes desktop lib/reasoning-effort.ts + composer model-pill: the Think
// scale beside the execution mode. '' (no pick yet) means "inherit the
// engine default" — the summary shows that honestly instead of guessing.
const thinkOptions = [
    { id: 'low', description: 'Quick replies, light reasoning' },
    { id: 'medium', description: 'Balanced default' },
    { id: 'high', description: 'Deep reasoning, slower turns' },
    { id: 'none', description: 'Disable extended thinking' },
];
function thinkPicker(model, host) {
    const details = element('details', 'crusorai-mode-picker crusorai-think-picker');
    const current = model.reasoningEffort ?? 'none';
    const summary = element('summary', 'crusorai-mode-summary', element('span', undefined, reasoningEffortLabel(current)), icon('chevron-down'));
    summary.setAttribute('aria-label', `Thinking effort: ${reasoningEffortLabel(current)}`);
    if (model.running) {
        summary.setAttribute('aria-disabled', 'true');
        summary.addEventListener('click', event => event.preventDefault());
    }
    const menu = element('div', 'crusorai-mode-menu');
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Thinking effort');
    for (const option of thinkOptions) {
        const selected = option.id === current || (!current && option.id === 'none');
        const item = element('button', selected ? 'crusorai-mode-option is-selected' : 'crusorai-mode-option', icon(option.id === 'none' ? 'circle-slash' : 'lightbulb'), element('span', 'crusorai-mode-option-copy', element('strong', undefined, reasoningEffortLabel(option.id)), element('small', undefined, option.description)), selected ? icon('check') : undefined);
        item.type = 'button';
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(selected));
        item.addEventListener('click', () => {
            details.open = false;
            host.setReasoningEffort(option.id);
        });
        menu.append(item);
    }
    details.append(summary, menu);
    return details;
}
function composer(model, host, manager) {
    const input = element('textarea', 'crusorai-composer-input');
    input.rows = manager ? 2 : 3;
    input.placeholder = model.isChild ? 'Sub-agent session — prompt disabled. Use Back to Parent.' : manager ? 'Steer this agent or add context...' : 'Ask anything, / for commands, @ for context...';
    input.value = model.draft;
    input.addEventListener('input', () => host.setDraft(input.value));
    const inputBlocked = model.noWorkspace || model.workspaceSelectionRequired || !!model.isChild;
    if (inputBlocked) {
        input.disabled = true;
    }
    const submit = () => {
        const value = input.value.trim();
        if (!value) {
            return;
        }
        if (manager && model.running) {
            host.steer(value);
        }
        else {
            host.submitPrompt(value);
        }
    };
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
        }
    });
    const running = model.running;
    const send = element('button', running ? 'crusorai-send-button crusorai-send-stop' : 'crusorai-send-button');
    send.type = 'button';
    send.setAttribute('aria-label', running ? 'Stop' : 'Send');
    send.append(icon(running ? 'debug-stop' : 'arrow-up'));
    send.addEventListener('click', running ? host.cancel : submit);
    if (running && model.cancelRequested) {
        send.disabled = true;
    }
    if (inputBlocked) {
        send.disabled = true;
    }
    // hermes composer layout: the Think pill sits beside the execution-mode
    // picker; the Send button stays right-aligned via the toolbar's spare
    // `.crusorai-composer-left` grid track.
    // The composer + menu (field 2026-10-02 rev 8, owner flow: "+ ->
    // menu bar option -> Dialog box"): + opens the compact picker — the
    // exact anatomy of the Agent/Think pills (details.crusorai-mode-picker
    // > summary.crusorai-mode-summary > div.crusorai-mode-menu >
    // button.crusorai-mode-option) — opening UPWARD in the composer space,
    // click-away closes it. Choosing an option opens the hub dialog: the
    // centered modal over the whole pane (crusorAIHubDialog), never the
    // top-center QuickPick. The composer is one code path shared by the
    // Agent pane AND the Manager chat box, so both surfaces get the same
    // flow. Data flows through the host's skillsHubOp / oneshotRun hooks.
    const plusMenu = (() => {
        const allEntries = [
            { label: 'Marketplace…', glyph: 'search', desc: 'browse & install skills', tab: 'marketplace', run: openHubDialog },
            { label: 'Connectors…', glyph: 'plug', desc: 'MCP, plugins', tab: 'connectors', run: openHubDialog },
            { label: 'My Skills', glyph: 'checklist', desc: 'installed skills, on/off', tab: 'myskills', run: openHubDialog },
            { label: 'One-Shot Task…', glyph: 'zap', desc: 'quick jobs to clipboard', tab: 'oneshot', run: openHubDialog },
        ];
        const entries = allEntries.filter(entry => typeof host.skillsHubOp === 'function');
        if (entries.length === 0) {
            return undefined;
        }
        const details = element('details', 'crusorai-mode-picker crusorai-add-picker');
        const summary = element('summary', 'crusorai-mode-summary', icon('add'), icon('chevron-down'));
        summary.setAttribute('aria-label', 'Add — marketplace, connectors, skills, one-shot');
        summary.title = 'Marketplace, connectors, skills, one-shot';
        const menu = element('div', 'crusorai-mode-menu');
        menu.setAttribute('role', 'menu');
        menu.setAttribute('aria-label', 'Add');
        for (const entry of entries) {
            const item = element('button', 'crusorai-mode-option', icon(entry.glyph), element('span', 'crusorai-mode-option-copy', element('strong', undefined, entry.label), element('small', undefined, entry.desc)));
            item.type = 'button';
            item.setAttribute('role', 'menuitem');
            item.addEventListener('click', () => {
                details.open = false;
                entry.run(host, details);
            });
            menu.append(item);
        }
        details.append(summary, menu);
        summary.addEventListener('click', () => {
            if (!details.open) {
                return;
            }
            setTimeout(() => {
                const away = (event) => {
                    if (!details.contains(event.target)) {
                        details.open = false;
                    }
                };
                document.addEventListener('click', away, { capture: true, once: true });
            }, 0);
        });
        return details;
    })();
    const toolbar = element('div', 'crusorai-composer-toolbar', plusMenu, modePicker(model, host), thinkPicker(model, host), element('span', 'crusorai-composer-left'), send);
    const hint = element('div', 'crusorai-composer-hint', model.noWorkspace
        ? element('span', undefined, model.noWorkspaceHint)
        : model.workspaceSelectionRequired
            ? element('span', undefined, 'Select a workspace folder to start a Crusor session.')
            : element('span', undefined, model.running ? 'Esc to interrupt' : 'Enter to send'), element('span', undefined, model.noWorkspace ? '' : 'Shift+Enter for new line'));
    if (model.noWorkspace) {
        hint.append(button('Open Folder', 'crusorai-link-button', host.openFolder, 'folder'));
    }
    return element('footer', 'crusorai-composer', element('div', 'crusorai-composer-box', input, toolbar), hint);
}
function agentColumn(model, host, openTools, closedTools, activity, planOpen, setPlanOpen) {
    const nodes = [];
    const plan = planStrip(model, planOpen, setPlanOpen);
    if (plan) {
        nodes.push(plan);
    }
    // An engine that is not ready is a FACT the panel must paint — the empty
    // state's starter grid under a dead engine reads as a send button that
    // does nothing (field 2026-09-05). Same quiet row the activity ticker
    // uses; the chip lives in the Manager, this names the state HERE.
    if (model.engineState !== 'ready' && !model.engineFault) {
        const row = element('div', 'crusorai-context-status-row is-info');
        row.append(element('span', undefined, model.engineState === 'starting'
            ? 'Crusor engine is starting — prompts send the moment it is ready.'
            : `Crusor engine: ${model.engineState}.`));
        nodes.push(row);
    }
    // An empty transcript is a designed surface, not a blank div -- the same rule the ported
    // webview follows (`hermes-ui/components/empty-state.tsx`). Exactly one of the two is
    // mounted, so a first-run view never shows an empty lane under a grid of starters.
    const empty = emptyState(model, host);
    nodes.push(empty ?? transcript(model, host, openTools, closedTools, activity.thoughtSeconds(model)));
    // No breathing tail under the transcript (founder 2026-10-15: delete
    // the breathing UI completely) — OpenCode streams the turn itself; a
    // narrating status row under the transcript is not one of its parts.
    const approval = approvalDock(model, host);
    if (approval) {
        nodes.push(approval);
    }
    // Hermes: the todo panel lives between the transcript and the composer
    // (the composer status stack) — the list rides ABOVE the input, never
    // buried in transcript history.
    const todos = todoStack(model);
    if (todos) {
        nodes.push(todos);
    }
    return nodes;
}
function renderAgent(root, model, host, openTools, closedTools, planOpen, setPlanOpen, activity) {
    const shell = element('div', 'crusorai-agent-shell');
    const header = element('div', 'crusorai-agent-header', element('span', 'crusorai-agent-header-title', 'Crusor Agent'), button('Manager', 'crusorai-agent-manager-button', () => host.openManager(), 'organization'));
    // Field run 2026-09-09 (owner: "Ur claim failed"): the STALE chip lived
    // only in the Manager titlebar, so an Agent-pane session ran a pre-
    // fef8cdb2/74d146bd workbench against a current engine — every card-
    // format fix invisible — with NO warning where the user was looking.
    // The chip rides the Agent header too (next to the Manager button).
    header.append(engineStatus(model));
    shell.append(header);
    // OpenCode empty session: the prompt dock is the hero, centred under
    // the mark — it docks to the bottom the moment a turn exists. The
    // is-empty shell class does the centring in CSS (mark + composer
    // ride as one centred group between the header and the pane bottom);
    // the engine-starting row still paints above the hero so a dead
    // engine never reads as a send button that does nothing.
    if (isEmptySession(model)) {
        shell.classList.add('is-empty');
    }
    shell.append(...agentColumn(model, host, openTools, closedTools, activity, planOpen, setPlanOpen));
    shell.append(composer(model, host, false));
    root.append(shell);
}
function inspector(model) {
    const pane = element('aside', 'crusorai-manager-inspector');
    pane.append(element('header', 'crusorai-manager-pane-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'LIVE EVIDENCE'), element('h2', undefined, 'Run inspector'))));
    const plan = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Plan'), element('strong', undefined, `${model.plan.length} steps`)));
    const list = element('ol', 'crusorai-plan-list');
    for (const step of model.plan) {
        list.append(element('li', `is-${step.status}`, planStepGlyph(step.status), element('span', undefined, step.text)));
    }
    if (!model.plan.length) {
        list.append(element('li', 'is-muted', icon('circle-outline'), element('span', undefined, 'Plan appears when the run starts')));
    }
    plan.append(list);
    const evidence = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Verification'), element('strong', undefined, model.verification ?? 'Not started')), element('div', 'crusorai-evidence-row', icon(model.verification === 'passed' ? 'pass-filled' : 'circle-outline'), element('span', undefined, model.verification ? `Runtime reported ${model.verification}` : 'No evidence receipt yet')));
    const capabilities = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Workbench capabilities'), element('strong', undefined, `${model.capabilitySummary.available}/${model.capabilitySummary.total}`)), element('div', 'crusorai-evidence-row', icon('plug'), element('span', undefined, `${model.capabilitySummary.available} available · ${model.capabilitySummary.blocked} blocked`)));
    const usage = element('section', 'crusorai-inspector-section crusorai-usage', element('div', 'crusorai-inspector-title', element('span', undefined, 'Usage'), element('strong', undefined, model.telemetry.cost === undefined ? '\u2014' : `$${model.telemetry.cost.toFixed(4)}`)), element('div', 'crusorai-usage-grid', element('span', undefined, 'Input'), element('strong', undefined, String(model.telemetry.input ?? 0)), element('span', undefined, 'Cache'), element('strong', undefined, String(model.telemetry.cache ?? 0)), element('span', undefined, 'Output'), element('strong', undefined, String(model.telemetry.output ?? 0))));
    pane.append(plan, evidence, capabilities, usage);
    return pane;
}
/**
 * The manager's session rows, drawn from the workbench's own session vocabulary: the lifecycle is
 * `ChatSessionStatus`'s (via the projection), the elapsed text follows the fork's list rules, and
 * the line an in-flight session shows is produced by `summarizeToolRun` -- the same call the
 * transcript lane makes, so one action can never read differently in the two surfaces.
 *
 * No row is invented here and none can be renamed: this is a render of `model.sessions`.
 */
function sessionList(model, host) {
    const group = element('div', 'crusorai-workspace-group');
    group.append(element('div', 'crusorai-workspace-title', icon('chevron-down'), icon('folder'), element('strong', undefined, model.workspaceLabel)));
    const rows = model.sessions;
    if (!rows || !rows.length) {
        group.append(element('div', 'crusorai-session-row is-empty', element('span', 'crusorai-status-dot is-idle'), element('div', undefined, element('strong', undefined, 'No session yet'), element('span', undefined, 'A run appears here the moment the engine names one'))));
        return group;
    }
    const narration = summarizeToolRun(model.tools, model.running, tool => compactTarget(displayTarget(tool)) ?? tool.name);
    for (const row of rows) {
        const dot = row.statusName === 'inProgress' ? 'running'
            : row.statusName === 'needsInput' ? 'waiting'
                : row.statusName === 'failed' ? 'failed' : 'ready';
        const detail = row.isActive && narration ? narration
            : row.statusName === 'needsInput' ? 'Waiting for approval'
                : row.statusName === 'failed' ? 'Run failed'
                    : row.changes ? `${row.changes.files} file(s) +${row.changes.insertions} −${row.changes.deletions}`
                        : row.statusName === 'completed' ? 'Finished' : row.description;
        const state = row.elapsedLabel || (row.isActive ? (model.running ? 'Working…' : 'Ready') : '');
        const classes = ['crusorai-session-row'];
        if (row.isActive) {
            classes.push('is-active');
        }
        if (row.statusName === 'needsInput') {
            classes.push('is-needs-input');
        }
        if (row.needsAttention) {
            classes.push('is-attention');
        }
        const button = element('button', classes.join(' '), element('span', `crusorai-status-dot is-${dot}`), element('div', undefined, element('strong', undefined, row.label), element('span', 'crusorai-session-detail', detail)), element('span', 'crusorai-session-state', state));
        // Every row opens its session in place (navigateToSession rebinds the surface and
        // hydrates the transcript); the active row is already open so it stays inert.
        button.type = 'button';
        if (!row.isActive && host.navigateToSession) {
            const target = crusorSessionIdFromUri(row.resource);
            button.title = 'Open this session in this panel';
            if (target) {
                button.addEventListener('click', () => host.navigateToSession(target));
            }
        }
        else {
            button.title = 'Open in this panel';
        }
        group.append(button);
    }
    return group;
}
const skillOriginLabel = { hub: 'hub', bundled: 'bundled', user: 'yours', agent: 'agent-learned' };
function skillsErrorRow(message) {
    return element('div', 'crusorai-error-row', icon('warning'), element('span', undefined, message));
}
function skillRow(row, updateAvailable, ui) {
    const busy = ui.action?.name === row.name;
    const node = element('div', `crusorai-skill-row${row.enabled ? '' : ' is-disabled'}`);
    const title = element('div', 'crusorai-skill-title', element('span', 'crusorai-skill-name', row.name), element('span', `crusorai-skill-badge${row.enabled ? ' is-on' : ''}`, row.enabled ? 'enabled' : 'disabled'), element('span', 'crusorai-skill-badge', skillOriginLabel[row.origin] ?? row.origin));
    if (updateAvailable) {
        title.append(element('span', 'crusorai-skill-badge is-update', 'update available'));
    }
    if (row.pinned) {
        title.append(element('span', 'crusorai-skill-badge', 'pinned'));
    }
    node.append(title);
    if (row.description) {
        node.append(element('div', 'crusorai-skill-description', row.description));
    }
    if (row.triggers?.length) {
        node.append(element('div', 'crusorai-skill-triggers', `routes on: ${row.triggers.join(', ')}`));
    }
    const actions = element('div', 'crusorai-skill-actions');
    const toggle = button(row.enabled ? 'Disable' : 'Enable', 'crusorai-skill-action', () => ui.runAction('toggle', row.name, { enabled: !row.enabled }), row.enabled ? 'circle-slash' : 'check');
    toggle.disabled = busy;
    actions.append(toggle);
    if (updateAvailable) {
        const update = button('Update', 'crusorai-skill-action', () => ui.runAction('update', row.name), 'arrow-up');
        update.disabled = busy;
        actions.append(update);
    }
    if (row.origin === 'hub') {
        const confirming = ui.confirmRemove === row.name;
        const remove = button(confirming ? 'Confirm remove' : 'Remove', confirming ? 'crusorai-skill-action is-confirm' : 'crusorai-skill-action', () => ui.confirmRemoveFor(row.name), 'trash');
        remove.disabled = busy;
        actions.append(remove);
    }
    actions.append(element('span', 'crusorai-skill-uses', `used ${row.use_count}×`));
    if (busy) {
        actions.append(element('span', 'crusorai-skill-busy', `${ui.action?.op}…`));
    }
    node.append(actions);
    return node;
}
function skillsPanel(ui, host) {
    const pane = element('div', 'crusorai-skills-pane');
    const rows = ui.skills.rows;
    const enabledCount = rows.filter(row => row.enabled).length;
    const head = element('div', 'crusorai-skills-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'SKILLS'), element('h2', undefined, 'Installed skills')), element('span', 'crusorai-skills-summary', ui.skills.loaded && rows.length > 0 ? `${enabledCount} enabled / ${rows.length} installed` : ''));
    const refresh = button(ui.skills.loading ? 'Refreshing…' : 'Refresh', 'crusorai-skills-refresh', () => ui.refresh(), 'refresh');
    refresh.disabled = ui.skills.loading;
    head.append(refresh);
    pane.append(head);
    if (ui.actionError) {
        pane.append(skillsErrorRow(ui.actionError));
    }
    if (!ui.skills.loaded && ui.skills.loading) {
        pane.append(element('div', 'crusorai-skills-empty', 'Loading the installed skills…'));
    }
    else if (ui.skills.error) {
        pane.append(skillsErrorRow(ui.skills.error));
        const retry = button('Retry', 'crusorai-skills-refresh', () => ui.refresh());
        pane.append(retry);
    }
    else if (rows.length === 0) {
        pane.append(element('div', 'crusorai-skills-empty', 'No skills installed yet.'));
        const browse = button('Browse the marketplace', 'crusorai-skills-refresh', () => openHubDialog(host, browse, 'marketplace'), 'package');
        pane.append(browse);
    }
    else {
        if (ui.skills.hubError) {
            pane.append(skillsErrorRow(`Update badges unavailable: ${ui.skills.hubError}`));
        }
        for (const row of rows) {
            const hubRow = ui.skills.hub.find(candidate => candidate.name === row.name);
            pane.append(skillRow(row, !!hubRow?.update_available, ui));
        }
    }
    // "What the model sees": the engine's own skills_manifest() — the exact
    // byte-stable index injected into the system prompt, never a TS re-build
    // of it (single source of truth; a reconstruction would drift silently).
    const manifestSection = element('div', 'crusorai-skills-manifest');
    manifestSection.append(element('div', 'crusorai-skills-manifest-head', element('span', 'crusorai-eyebrow', 'WHAT THE MODEL SEES'), copyButton(ui.skills.manifest, host)));
    if (ui.skills.manifestError) {
        manifestSection.append(skillsErrorRow(ui.skills.manifestError));
    }
    else if (ui.skills.manifest) {
        manifestSection.append(element('pre', 'crusorai-skills-manifest-body', ui.skills.manifest));
    }
    else if (ui.skills.loaded && !ui.skills.error) {
        manifestSection.append(element('div', 'crusorai-skills-empty', 'No skills are enabled — the model sees an empty skills index.'));
    }
    pane.append(manifestSection);
    return pane;
}
function renderManager(root, model, host, openTools, closedTools, activity, planOpen, setPlanOpen, ui) {
    const shell = element('div', 'crusorai-manager-shell');
    const sidebar = element('aside', 'crusorai-manager-sidebar', element('header', 'crusorai-manager-pane-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'CONTROL PLANE'), element('h2', undefined, 'Workspaces')), button('', 'crusorai-icon-button', () => host.newSession?.(), 'add')), element('div', 'crusorai-manager-search', icon('search'), element('span', undefined, 'Find workspace or agent')), sessionList(model, host), element('footer', 'crusorai-manager-sidebar-footer', icon('organization'), element('span', undefined, model.sessions?.length ? `${model.sessions.length} session(s) remembered · ${model.running ? '1 running' : 'none running'}` : 'No session yet')));
    const main = element('main', 'crusorai-manager-main');
    // Session + Skills are real tabs (tab state drives the column below);
    // Tools/Changes stay display-only exactly as they were — inventing
    // half-empty views for them is scope the plan did not ask for.
    const tabs = element('nav', 'crusorai-manager-tabs', button('Session', ui.tab === 'session' ? 'is-active' : '', () => ui.setTab('session'), 'comment-discussion'), element('button', undefined, icon('terminal'), `Tools ${model.tools.length}`), element('button', undefined, icon('diff'), 'Changes'), button(ui.skills.loaded && ui.skills.rows.length > 0 ? `Skills ${ui.skills.rows.length}` : 'Skills', ui.tab === 'skills' ? 'is-active' : '', () => ui.setTab('skills'), 'library'));
    main.append(element('header', 'crusorai-manager-titlebar', element('div', undefined, element('div', 'crusorai-manager-breadcrumb', model.workspaceLabel, ' / ', model.sessionId?.slice(0, 12) ?? 'new-session'), element('h1', undefined, model.userMessage || 'Crusor Manager')), engineStatus(model)), tabs, ...(ui.tab === 'skills'
        ? [skillsPanel(ui, host)]
        : [...agentColumn(model, host, openTools, closedTools, activity, planOpen, setPlanOpen)]), composer(model, host, true));
    shell.append(sidebar, main, inspector(model));
    root.append(shell);
}
export function mountCrusorAIRenderer(root, surface, host) {
    // Global keys (Esc-to-interrupt, approval-dock and clarify shortcuts)
    // used to install only when an approval/clarify card first rendered —
    // a plain turn had NO Escape handler at all. The installer is flag-
    // guarded, so mounting the pane once is enough for the app's lifetime.
    ensureGlobalCardKeys();
    const openTools = new Set();
    const closedTools = new Set();
    let planOpen;
    let planSession;
    let disposed = false;
    let lastModel;
    // Hermes streaming isolation (apps/desktop mechanism 6): while tokens
    // arrive, ONLY the message part re-renders — never the whole transcript.
    // The full rebuild tore down every tool card + re-parsed all markdown on
    // every animation frame, O(turn length) per frame (the owner's "UI not
    // nice" jank that compounds the longer a turn runs). `paintSignature`
    // covers everything EXCEPT text content: it pins the part SHAPE (kinds +
    // tool ids), so token growth keeps the signature identical and patches the
    // [data-slot=session-turn-content] node (the LAST text segment — hermes
    // parts order means that is the live one) with the near-bottom scroll rule
    // preserved. A new part or tool changes the shape and takes the full paint
    // exactly as before.
    let lastPaint;
    const lastTextPart = (model) => {
        for (let i = model.parts.length - 1; i >= 0; i--) {
            const part = model.parts[i];
            if (part.kind === 'text' && part.text) {
                return part;
            }
        }
        return undefined;
    };
    const paintSignature = (model) => {
        const shape = model.parts.map(p => (p.kind === 'tool' ? `tool:${p.toolId}` : 'text') + (p.kind === 'reasoning' ? `:r${p.reasoningIndex}` : '')).join('>');
        return `${JSON.stringify({ ...model, assistantText: undefined, parts: undefined, reasoningParts: undefined })}|${shape}`;
    };
    // The activity row's timers outlive individual renders; a tick repaints from the last model,
    // which is what makes the seconds move while the engine is quiet.
    const activity = createActivityState(() => { if (!disposed) {
        tick();
    } });
    const tick = () => { if (!disposed && lastModel) {
        paint(lastModel);
    } };
    // ---- Manager Skills tab state (mount scope: survives wholesale repaints) ----
    let managerTab = 'session';
    let managerAction;
    let managerActionError;
    let managerConfirmRemove;
    let confirmRemoveTimer;
    const managerSkills = { loading: false, loaded: false, rows: [], hub: [], manifest: '' };
    const loadSkills = () => {
        if (!host.skillsHubOp) {
            managerSkills.loading = false;
            managerSkills.loaded = true;
            managerSkills.error = 'This host build does not expose skills (skillsHubOp is missing).';
            tick();
            return;
        }
        managerSkills.loading = true;
        managerSkills.error = undefined;
        tick();
        // Three distinct ops, so result frames can never cross-resolve within
        // this request; the palette's flows are modal, so a same-op race with
        // them is not reachable from this surface.
        void Promise.all([
            host.skillsHubOp('all'),
            host.skillsHubOp('list'),
            host.skillsHubOp('manifest'),
        ]).then(([all, list, manifest]) => {
            if (all.ok === false) {
                managerSkills.rows = [];
                managerSkills.error = String(all.error ?? 'could not list installed skills');
            }
            else {
                managerSkills.rows = Array.isArray(all.skills) ? all.skills : [];
            }
            if (list.ok === false) {
                managerSkills.hub = [];
                managerSkills.hubError = String(list.error ?? 'could not list hub-installed skills');
            }
            else {
                managerSkills.hub = Array.isArray(list.installed) ? list.installed : [];
                managerSkills.hubError = undefined;
            }
            if (manifest.ok === false) {
                managerSkills.manifest = '';
                managerSkills.manifestError = String(manifest.error ?? 'could not read the skills index');
            }
            else {
                managerSkills.manifest = typeof manifest.manifest === 'string' ? manifest.manifest : '';
                managerSkills.manifestError = undefined;
            }
            managerSkills.loading = false;
            managerSkills.loaded = true;
            tick();
        }, error => {
            managerSkills.loading = false;
            managerSkills.loaded = true;
            managerSkills.error = String(error?.message ?? error);
            tick();
        });
    };
    const runManagerAction = (op, name, extra) => {
        if (!host.skillsHubOp || managerAction) {
            return;
        }
        managerAction = { name, op };
        managerActionError = undefined;
        managerConfirmRemove = undefined;
        if (confirmRemoveTimer !== undefined) {
            clearTimeout(confirmRemoveTimer);
            confirmRemoveTimer = undefined;
        }
        tick();
        void host.skillsHubOp(op, { name, ...(extra ?? {}) }).then(result => {
            if (result && result.ok === false) {
                managerActionError = `${name}: ${String(result.error ?? `${op} failed`)}`;
                return false;
            }
            return true;
        }, error => {
            managerActionError = `${name}: ${String(error?.message ?? error)}`;
            return false;
        }).then(refreshed => {
            managerAction = undefined;
            // Failed actions keep the current list (nothing changed on the
            // engine side either); only a success pays for a refetch.
            if (refreshed) {
                loadSkills();
            }
            else {
                tick();
            }
        });
    };
    const confirmManagerRemove = (name) => {
        if (managerAction) {
            return;
        }
        if (managerConfirmRemove !== name) {
            // First click arms the row ("Remove" -> "Confirm remove"); the arm
            // self-disarms so a stale confirm can never eat a later click.
            managerConfirmRemove = name;
            if (confirmRemoveTimer !== undefined) {
                clearTimeout(confirmRemoveTimer);
            }
            confirmRemoveTimer = setTimeout(() => {
                managerConfirmRemove = undefined;
                confirmRemoveTimer = undefined;
                tick();
            }, 4000);
            tick();
            return;
        }
        runManagerAction('remove', name);
    };
    const managerUi = {
        get tab() { return managerTab; },
        setTab: tab => {
            if (managerTab === tab) {
                return;
            }
            managerTab = tab;
            if (tab === 'skills' && !managerSkills.loaded && !managerSkills.loading) {
                loadSkills();
            }
            else {
                tick();
            }
        },
        skills: managerSkills,
        get action() { return managerAction; },
        get actionError() { return managerActionError; },
        get confirmRemove() { return managerConfirmRemove; },
        refresh: loadSkills,
        runAction: runManagerAction,
        confirmRemoveFor: confirmManagerRemove,
    };
    // Live tool-output patch (OpenCode streaming feel): when ONLY running
    // tools' results grew (tool_output chunks) and the part shape is stable,
    // rewrite those <pre> nodes in place and follow the tail — the transcript,
    // scroll position, and every other card stay untouched. Returns true when
    // it handled the paint. Plain-text form while streaming; the settle frame
    // (state change) takes the full paint and restores ANSI colour.
    let lastToolOutputSig = '';
    const toolOutputSig = (model) => model.tools.map(t => `${t.id}:${t.state}:${typeof t.result === 'string' ? t.result.length : 0}`).join('|');
    const patchLiveToolOutputs = (model) => {
        const sig = toolOutputSig(model);
        if (sig === lastToolOutputSig) {
            return false;
        }
        let patched = false;
        for (const tool of model.tools) {
            if (tool.state !== 'running' || typeof tool.result !== 'string') {
                continue;
            }
            const pre = root.querySelector(`pre[data-tool-output-for="${tool.id}"]`);
            if (!pre) {
                continue;
            }
            const text = windowedTailLines(stripTerminalEnvelope(resultOutput(tool)), TERMINAL_PAINT_LINE_LIMIT).lines.join('\n');
            if (pre.textContent !== text) {
                pre.textContent = text;
            }
            const scroller = pre.closest('.crusorai-bash-scroll');
            if (scroller && bashFollow.get(tool.id) !== false) {
                scroller.scrollTop = scroller.scrollHeight;
            }
            patched = true;
        }
        if (patched) {
            lastToolOutputSig = sig;
        }
        return patched;
    };
    // Stable shape for the tool-output patch: everything the full signature
    // covers EXCEPT tool results (their growth is the patch's whole point).
    let lastStableSig = '';
    const stableSignature = (model) => {
        const strip = (t) => ({ id: t.id, name: t.name, state: t.state });
        return JSON.stringify({
            ...model, assistantText: undefined, parts: undefined, reasoningParts: undefined,
            tools: model.tools.map(strip),
            history: model.history.map(h => ({ ...h, tools: h.tools.map(strip) })),
        }) + '|' + model.parts.map(p => (p.kind === 'tool' ? `tool:${p.toolId}` : 'text')).join('>');
    };
    const paint = (model) => {
        if (model.sessionId !== planSession) {
            planSession = model.sessionId;
            planOpen = undefined;
            lastPaint = undefined;
            lastStableSig = '';
            lastToolOutputSig = '';
        }
        const signature = paintSignature(model);
        const stableSig = stableSignature(model);
        const streaming = lastTextPart(model);
        if (lastPaint
            && lastPaint.signature === signature
            && streaming
            && streaming.text !== lastPaint.text
            && streaming.text.startsWith(lastPaint.text)) {
            const slot = root.querySelector('[data-slot="session-turn-content"]');
            if (slot) {
                slot.replaceChildren(markdownCopy(streaming.text, 'session-turn-content'));
                const scroller = root.querySelector('.crusorai-transcript-scroll');
                if (scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120) {
                    scroller.scrollTop = scroller.scrollHeight;
                }
                lastPaint = { signature, text: streaming.text };
                lastStableSig = stableSig;
                return;
            }
            // No live slot even though the shape says one should exist — the
            // DOM does not match the model; take the full paint to resync.
        }
        if (lastPaint
            && stableSig === lastStableSig
            && streaming?.text === lastPaint.text
            && patchLiveToolOutputs(model)) {
            return;
        }
        const previousScroll = root.querySelector('.crusorai-transcript-scroll');
        const scrollTop = previousScroll?.scrollTop ?? 0;
        // Follow only from the bottom (founder 2026-10-15: 'i can't scroll
        // freely'): while the user reads up-scroll, repaints preserve their
        // place; the old `|| model.running` clause pinned every repaint to
        // the floor for the whole run.
        const wasNearBottom = !previousScroll || previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 120;
        const activeElement = document.activeElement;
        const activeComposer = root.contains(activeElement) && activeElement instanceof HTMLTextAreaElement ? activeElement : undefined;
        // Don't steal focus from ask tool (clarify card) — vibrations/streaming re-renders were
        // yanking focus back to the main composer while user typed in the card
        const isClarifyInput = activeComposer?.closest('.crusorai-clarify-card') !== null;
        const selectionStart = activeComposer?.selectionStart;
        const selectionEnd = activeComposer?.selectionEnd;
        root.replaceChildren();
        root.dataset.surface = surface;
        if (surface === 'agent') {
            renderAgent(root, model, host, openTools, closedTools, planOpen, open => { planOpen = open; }, activity);
        }
        else {
            renderManager(root, model, host, openTools, closedTools, activity, planOpen, open => { planOpen = open; }, managerUi);
        }
        const nextScroll = root.querySelector('.crusorai-transcript-scroll');
        if (nextScroll) {
            nextScroll.scrollTop = wasNearBottom ? nextScroll.scrollHeight : scrollTop;
        }
        if (activeComposer && !isClarifyInput && activeComposer.classList.contains('crusorai-composer-input')) {
            const input = root.querySelector('.crusorai-composer-input');
            input?.focus({ preventScroll: true });
            if (input && selectionStart !== undefined && selectionEnd !== undefined) {
                input.setSelectionRange(selectionStart, selectionEnd);
            }
        }
        else if (isClarifyInput && activeComposer) {
            // Restore focus to the clarify card's textarea (it was recreated by replaceChildren)
            const nextClarify = root.querySelector('.crusorai-clarify-card textarea');
            if (nextClarify) {
                nextClarify.focus({ preventScroll: true });
                if (selectionStart !== undefined && selectionEnd !== undefined) {
                    nextClarify.setSelectionRange(selectionStart, selectionEnd);
                }
            }
        }
        lastPaint = { signature, text: lastTextPart(model)?.text ?? '' };
        lastStableSig = stableSig;
        lastToolOutputSig = toolOutputSig(model);
    };
    return {
        update(model) {
            if (disposed) {
                return;
            }
            lastModel = model;
            activity.sync(model);
            paint(model);
        },
        dispose() {
            disposed = true;
            activity.dispose();
            if (confirmRemoveTimer !== undefined) {
                clearTimeout(confirmRemoveTimer);
                confirmRemoveTimer = undefined;
            }
            lastModel = undefined;
            root.replaceChildren();
        },
    };
}
