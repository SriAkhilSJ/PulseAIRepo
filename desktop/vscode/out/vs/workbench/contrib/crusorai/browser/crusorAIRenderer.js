/*---------------------------------------------------------------------------------------------
 * Framework-neutral, editor-native Crusor renderer. Both first-party workbench hosts mount this
 * module; no Electron, Node, or Code OSS service is imported across this boundary.
 *--------------------------------------------------------------------------------------------*/
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { reasoningEffortLabel } from '../common/crusorAIReasoningEffort.js';
import { separateGluedReasoningBlocks } from './crusorAIReasoningBlocks.js';
import { openHubDialog } from './crusorAIHubDialog.js';
import { crusorSessionIdFromUri } from '../common/crusorAISessionProjection.js';
import { crusorAIToolPresentation } from '../common/crusorAIToolCatalog.js';
import { deriveChangedFiles, hasAnsiCodes, parseAnsi, parseDiff, stripTerminalEnvelope, windowedTailLines } from './crusoraiCardFormat.js';
import { compactTarget, splitRunGroups, summarizeToolRun, toolPresentVerb } from './crusorAIRunSummary.js';
import { renderToolIcon } from './crusorAIIcons.js';
import { activityOrigin, activityParts, activityRowMode, activitySignature, closeMeasurement, draftingToolName, elapsedFor, measuredDuration, DRAFTING_REVEAL_MS, elapsedSeconds, formatElapsed, statusHintLabel, toolNarratesWait, TURN_QUIET_S, UNNAMED_WAIT_LABEL, } from './crusorAIActivity.js';
function element(tag, className) {
    var children = [];
    for (var _i = 2; _i < arguments.length; _i++) {
        children[_i - 2] = arguments[_i];
    }
    var node = document.createElement(tag);
    if (className) {
        node.className = className;
    }
    for (var _a = 0, children_1 = children; _a < children_1.length; _a++) {
        var child = children_1[_a];
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
    for (var _i = 0, _a = text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|<https?:\/\/[^>\s]+>)/); _i < _a.length; _i++) {
        var part = _a[_i];
        if (!part) {
            continue;
        }
        var linkMd = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part);
        if (linkMd) {
            var a = element('a', 'crusorai-md-link', linkMd[1]);
            a.href = linkMd[2];
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            target.append(a);
            continue;
        }
        if (/^<https?:\/\/[^>\s]+>$/.test(part)) {
            var url = part.slice(1, -1);
            var a = element('a', 'crusorai-md-link', url);
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
var RAW_TOOL_MARKUP = /^\s*(?:<\/?\s*(?:dots_function_call|exec|invoke|command|tool_call|function_call)\b|\{\s*"(?:action|tool|tool_call|function)"\s*:)/i;
// Workbench freshness stamp — bump with EVERY workbench UI round. The engine
// chip proves the PYTHON engine only; field round 2026-09-08 ran engine
// de0dbbae on a base-era compiled workbench (lab-era browser cards, reveal-
// URL ERRs) and nothing on screen could tell. This constant lives in this
// source file, so any compile of current source carries it while a stale
// out/ shows an older date; engineStatus() flags engine-newer skew as STALE.
var CRUSORAI_UI_STAMP = '2026-10-02';
function markdownCopy(text, slot) {
    var root = element('div', 'crusorai-assistant-copy crusorai-md');
    if (slot) {
        root.dataset.slot = slot;
    }
    var list = null;
    var code = null;
    // Consecutive raw tool-markup lines collapse into ONE labeled disclosure.
    // They are buffered and flushed on the next non-markup line (or at the
    // end of the text) — the old loop-carried rawBlock/rawPre pair hit a TS
    // circular-narrowing error (append on never) AND could crash at runtime
    // on a consecutive markup line (stale pre reference).
    var rawLines = [];
    var flushRawMarkup = function () {
        if (!rawLines.length) {
            return;
        }
        var details = element('details', 'crusorai-raw-call');
        details.append(element('summary', undefined, 'Unparsed tool-call markup (model dialect, not executed)'));
        var pre = element('pre', 'crusorai-raw-call-pre');
        pre.append(document.createTextNode("".concat(rawLines.join('\n'), "\n")));
        details.append(pre);
        root.append(details);
        rawLines.length = 0;
        list = null;
    };
    for (var _i = 0, _a = text.split(/\r?\n/); _i < _a.length; _i++) {
        var raw = _a[_i];
        var line = raw.replace(/\s+$/, '');
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
        var heading = /^(#{1,6})\s+(.*)$/.exec(line);
        if (heading) {
            list = null;
            var h = element('div', "crusorai-md-h crusorai-md-h".concat(heading[1].length));
            mdInline(h, heading[2]);
            root.append(h);
            continue;
        }
        if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
            list = null;
            root.append(element('hr', 'crusorai-md-hr'));
            continue;
        }
        var bullet = /^\s*[-*]\s+(.*)$/.exec(line);
        if (bullet) {
            if (!list || list.tagName !== 'UL') {
                list = element('ul', 'crusorai-md-ul');
                root.append(list);
            }
            var li = element('li');
            mdInline(li, bullet[1]);
            list.append(li);
            continue;
        }
        var ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
        if (ordered) {
            // hermes markdown-text: ordered lists keep their own element so a
            // numbered "1. 2. 3." answer doesn't collapse into one paragraph.
            if (!list || list.tagName !== 'OL') {
                list = element('ol', 'crusorai-md-ol');
                root.append(list);
            }
            var li = element('li');
            mdInline(li, ordered[1]);
            list.append(li);
            continue;
        }
        var quote = /^>\s?(.*)$/.exec(line);
        if (quote) {
            // hermes compact-markdown: a quote is its own quiet block.
            list = null;
            var q = element('blockquote', 'crusorai-md-quote');
            mdInline(q, quote[1]);
            root.append(q);
            continue;
        }
        if (/^\s*\|.*\|\s*$/.test(line) && line.includes('|', 1)) {
            // hermes markdown-table: a pipe-table body renders as a real table.
            var cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) { return c.trim(); });
            if (cells.every(function (c) { return /^:?-{2,}:?$/.test(c); })) {
                continue;
            } // separator row
            var table = root.querySelector('table.crusorai-md-table:last-of-type');
            if (!table || table.dataset.closed === 'true') {
                table = element('table', 'crusorai-md-table');
                table.dataset.closed = 'false';
                root.append(table);
            }
            var tr = element('tr');
            var kind = table.rows.length === 0 ? 'th' : 'td';
            for (var _b = 0, cells_1 = cells; _b < cells_1.length; _b++) {
                var cell = cells_1[_b];
                var td = element(kind);
                mdInline(td, cell);
                tr.append(td);
            }
            table.append(tr);
            continue;
        }
        if (!line.trim()) {
            list = null;
            // a blank line closes an open table (hermes table scope)
            for (var _c = 0, _d = root.querySelectorAll('table.crusorai-md-table'); _c < _d.length; _c++) {
                var t = _d[_c];
                t.dataset.closed = 'true';
            }
            continue;
        }
        list = null;
        var para = element('div', 'crusorai-md-p');
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
    return seconds < 60 ? "".concat(seconds, "s") : "".concat(Math.floor(seconds / 60), ":").concat(String(seconds % 60).padStart(2, '0'));
}
var elapsedTicker;
function elapsedSpan(originMs) {
    var span = element('span', 'crusorai-scaffold-meta crusorai-elapsed');
    var origin = typeof originMs === 'number' && originMs > 0 ? originMs : Date.now();
    datasetSet(span, 'origin', String(origin));
    span.textContent = formatElapsedSeconds(Math.max(0, Math.floor((Date.now() - origin) / 1000)));
    if (elapsedTicker === undefined) {
        elapsedTicker = window.setInterval(function () {
            for (var _i = 0, _a = document.querySelectorAll('span.crusorai-elapsed'); _i < _a.length; _i++) {
                var node = _a[_i];
                var nodeOrigin = Number(node.dataset.origin || '0');
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
    var btn = element('button', 'crusorai-icon-action');
    btn.type = 'button';
    btn.title = 'Copy';
    btn.setAttribute('aria-label', 'Copy');
    btn.append(icon('copy'));
    var reset = function () {
        btn.replaceChildren(icon('copy'));
        btn.title = 'Copy';
    };
    var flash = function () {
        btn.replaceChildren(icon('check'));
        btn.title = 'Copied';
        setTimeout(reset, 1500);
    };
    var fail = function () {
        btn.replaceChildren(icon('error'));
        btn.title = 'Copy failed';
        setTimeout(reset, 1500);
    };
    btn.addEventListener('click', function () {
        if (host) {
            try {
                host.copyToClipboard(text);
                flash();
            }
            catch (_a) {
                fail();
            }
            return;
        }
        try {
            void copyTextToClipboard(text).then(flash, fail);
        }
        catch (_b) {
            fail();
        }
    });
    return btn;
}
function button(label, className, action, iconName) {
    var node = element('button', className, iconName ? icon(iconName) : undefined, label);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
}
// Webview clipboard can be permission-blocked (field: NotAllowedError on
// writeText). Degrade honestly: async API first, hidden-textarea fallback,
// real failure surfaced by the caller's UI either way.
function copyTextToClipboard(text) {
    var _a;
    if ((_a = navigator.clipboard) === null || _a === void 0 ? void 0 : _a.writeText) {
        return navigator.clipboard.writeText(text).catch(function () { return copyViaExecCommand(text); });
    }
    return new Promise(function (resolve) { copyViaExecCommand(text); resolve(); });
}
function copyViaExecCommand(text) {
    var textarea = document.createElement('textarea');
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
    var value = record(source);
    for (var _i = 0, keys_1 = keys; _i < keys_1.length; _i++) {
        var key = keys_1[_i];
        if (typeof (value === null || value === void 0 ? void 0 : value[key]) === 'string' && value[key]) {
            return value[key];
        }
        if (typeof (value === null || value === void 0 ? void 0 : value[key]) === 'number') {
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
        catch (_a) {
            return undefined;
        }
    }
    return record(value);
}
function displayTarget(tool) {
    var _a;
    return (_a = firstString(tool.arguments, ['path', 'file_path', 'resource', 'command', 'query', 'url', 'goal', 'target'])) !== null && _a !== void 0 ? _a : tool.name;
}
function boundedText(value, max) {
    if (max === void 0) { max = 12000; }
    var text;
    if (typeof value === 'string') {
        text = value;
    }
    else {
        try {
            text = JSON.stringify(value !== null && value !== void 0 ? value : {}, undefined, 2);
        }
        catch (_a) {
            text = String(value);
        }
    }
    if (text.length <= max) {
        return text;
    }
    return "... ".concat(text.length - max, " earlier characters omitted ...\n").concat(text.slice(-max));
}
function resultOutput(tool) {
    var value = record(tool.result);
    var parts = [value === null || value === void 0 ? void 0 : value.output, value === null || value === void 0 ? void 0 : value.stdout, value === null || value === void 0 ? void 0 : value.stderr].filter(function (part) { return typeof part === 'string' && part.length > 0; });
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
    var name = state === 'passed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'approval' ? 'shield' : 'circle-outline';
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
    var wrap = element('div', 'crusorai-expandable is-collapsed');
    var clip = element('div', 'crusorai-expandable-clip', content);
    var toggle = element('button', 'crusorai-expandable-toggle', icon('chevron-down'));
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Expand output');
    toggle.addEventListener('click', function () {
        var collapsed = wrap.classList.toggle('is-collapsed');
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
    var fade = element('div', 'crusorai-expandable-fade', toggle);
    wrap.append(clip, fade);
    window.requestAnimationFrame(function () {
        if (clip.scrollHeight <= 121) {
            wrap.classList.remove('is-collapsed');
            wrap.classList.add('is-fits');
        }
        // Hermes terminal-output.tsx: jump straight to the LATEST output
        // on first delivery — boundedText keeps the tail, so the end of
        // the stream is the payload (dir listings end at the current
        // entries). First delivery only; a later resize must not yank
        // the user while they scroll up reading earlier output.
        var pre = clip.querySelector('.crusorai-terminal-output');
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
var openPlanLists = new Set();
// hermes DESKTOP status stack (apps/desktop composer/status-stack +
// components/chat/status-section.tsx) — NOT the TUI TodoPanel. The desktop
// chrome: chevron-right caret (rotates 90deg open, 150ms), the `checklist`
// codicon, the en.ts label `Tasks ${done}/${total}`, the todo group is the
// ONLY group expanded by default (defaultCollapse = type !== 'todo'), and a
// spinner rides the header while an item is in_progress/running (hidden
// once open, pure CSS). Rows keep the status-row glyph grammar.
function planListBody(tool, result, args) {
    var rows = planStepsFrom(result, args);
    if (!rows.length) {
        var empty = element('div', 'crusorai-plan-list');
        empty.append(element('div', 'crusorai-plan-empty', 'No task list written'));
        return empty;
    }
    var done = rows.filter(function (s) { return s.status === 'completed'; }).length;
    var running = rows.some(function (s) { return s.status === 'in_progress'; });
    var details = element('details', 'crusorai-plan-details');
    // Desktop defaultCollapse: the todo group is expanded by default; the
    // user's toggle wins and survives re-renders (openPlanLists).
    details.open = !openPlanLists.has(tool.id);
    details.addEventListener('toggle', function () { return details.open ? openPlanLists.delete(tool.id) : openPlanLists.add(tool.id); });
    details.append(element('summary', 'crusorai-plan-head', element('span', 'crusorai-plan-caret', icon('chevron-right')), element('span', 'crusorai-plan-icon', icon('checklist')), element('span', 'crusorai-plan-title', "Tasks ".concat(done, "/").concat(rows.length)), running ? element('span', 'crusorai-mini-spinner crusorai-plan-spinner') : undefined));
    var wrap = element('div', 'crusorai-plan-list');
    for (var _i = 0, rows_1 = rows; _i < rows_1.length; _i++) {
        var step = rows_1[_i];
        var status = step.status;
        var row = element('div', "crusorai-plan-row is-".concat(status));
        var glyph = element('span', 'crusorai-plan-glyph');
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
    var _a, _b, _c, _d, _e, _f, _g, _h, _j;
    var raw = (_d = (_c = (_b = (_a = (result && planStepsOf(result, 'steps'))) !== null && _a !== void 0 ? _a : planStepsOf(result, 'todos')) !== null && _b !== void 0 ? _b : planStepsOf(args, 'steps')) !== null && _c !== void 0 ? _c : planStepsOf(args, 'todos')) !== null && _d !== void 0 ? _d : [];
    var rows = [];
    for (var _i = 0, raw_1 = raw; _i < raw_1.length; _i++) {
        var item = raw_1[_i];
        if (!item || typeof item !== 'object') {
            continue;
        }
        var rec = item;
        var description = String((_f = (_e = rec.description) !== null && _e !== void 0 ? _e : rec.content) !== null && _f !== void 0 ? _f : '').trim();
        // hermes items are id-keyed; an id-only row (schema-forbidden but
        // seen in the field) reads as "Item <id>", never "(no description)".
        if (!description) {
            var id = String((_g = rec.id) !== null && _g !== void 0 ? _g : '').trim();
            if (!id) {
                continue;
            }
            rows.push({ description: "Item ".concat(id), status: String((_h = rec.status) !== null && _h !== void 0 ? _h : 'pending') });
            continue;
        }
        rows.push({ description: description, status: String((_j = rec.status) !== null && _j !== void 0 ? _j : 'pending') });
    }
    return rows;
}
function planStepsOf(source, key) {
    if (!source) {
        return undefined;
    }
    var raw = source[key];
    if (typeof raw === 'string') {
        try {
            raw = JSON.parse(raw);
        }
        catch (_a) {
            return undefined;
        }
    }
    return Array.isArray(raw) ? raw : undefined;
}
function terminalBody(tool, host) {
    var _a, _b, _c;
    var args = record(tool.arguments);
    var result = resultRecord(tool.result);
    var command = (_a = firstString(args, ['command', 'script'])) !== null && _a !== void 0 ? _a : 'Command details unavailable';
    // The engine wraps terminal results in a STDOUT:/STDERR: envelope; hermes'
    // card shows the raw output. The Exit-code trailer is parsed from the RAW
    // text above (exitSource) before this strip.
    var output = stripTerminalEnvelope(resultOutput(tool));
    var exitSource = typeof tool.result === 'string' ? tool.result : '';
    var exit = firstString(result, ['exitCode', 'exit_code', 'status', 'code']);
    if (exit === undefined && exitSource) {
        // run_terminal appends "Exit code: N" as the last line of its envelope
        // (and the output cap keeps the tail), so the real exit code is
        // recoverable even when the result is a plain string. Timeout
        // envelopes carry their own marker instead.
        var sentinel = /Exit code: (-?\d+)\s*$/.exec(exitSource);
        if (sentinel) {
            exit = sentinel[1];
        }
        else if (exitSource.includes('terminal timed out') || exitSource.includes('run_terminal timed out')) {
            exit = 'timeout';
        }
    }
    exit !== null && exit !== void 0 ? exit : (exit = tool.state === 'running' ? 'running' : 'unknown');
    var duration = (_c = (_b = tool.duration) !== null && _b !== void 0 ? _b : firstString(result, ['duration', 'elapsed'])) !== null && _c !== void 0 ? _c : '\u2014';
    var body = element('div', 'crusorai-tool-body crusorai-terminal-body');
    body.append(element('div', 'crusorai-terminal-command', element('span', 'crusorai-terminal-prompt', '$'), element('code', undefined, command)), expandableOutput(terminalOutputContent(output, tool.state === 'running')), 
    // One meta line (hermes scaffold grammar): state word + exit code
    // + duration, plain text — the colored glyph in the header already
    // carries the state, so no second PASSED pill here.
    element('div', 'crusorai-terminal-result', element('span', undefined, "".concat(stateLabel(tool.state), " \u00B7 exit ").concat(exit)), element('span', 'crusorai-tool-duration', duration)));
    var actions = element('div', 'crusorai-tool-actions');
    actions.append(copyButton(command, host));
    var cwd = firstString(args, ['cwd', 'path']);
    if (cwd) {
        actions.append(button('Reveal location', 'crusorai-link-button', function () { return host.revealFile(cwd); }, 'go-to-file'));
    }
    body.append(actions);
    return body;
}
function toolFields(rows) {
    var wrap = element('div', 'crusorai-tool-fields');
    for (var _i = 0, rows_2 = rows; _i < rows_2.length; _i++) {
        var _a = rows_2[_i], k = _a[0], v = _a[1];
        var row = element('div', 'crusorai-tool-field-row', element('span', 'crusorai-tool-field-key', k), element('code', 'crusorai-tool-field-val', v));
        wrap.append(row);
    }
    return wrap;
}
// OpenCode parity: agent color hash for task cards
function agentColor(name) {
    var palette = ['#0b6bcb', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
    var hash = 0;
    for (var i = 0; i < name.length; i++)
        hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
    return palette[hash % palette.length];
}
function taskToolCard(tool, host) {
    var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o;
    var args = (_a = record(tool.arguments)) !== null && _a !== void 0 ? _a : {};
    var resultRec = resultRecord(tool.result);
    // Extract from args: description, prompt, subagent_type, mode, background
    var description = (_b = firstString(args, ['description', 'goal', 'prompt', 'task'])) !== null && _b !== void 0 ? _b : 'Sub-agent task';
    var agentName = (_c = firstString(args, ['subagent_type', 'agent_name', 'mode'])) !== null && _c !== void 0 ? _c : 'general';
    var isBackground = Boolean((_e = (_d = args.background) !== null && _d !== void 0 ? _d : resultRec === null || resultRec === void 0 ? void 0 : resultRec.background) !== null && _e !== void 0 ? _e : false);
    // sessionId metadata may be in result or tool metadata fields (bridge now emits child_thread_id)
    var childId = (_h = (_g = (_f = firstString(resultRec !== null && resultRec !== void 0 ? resultRec : {}, ['sessionId', 'session_id', 'child_thread_id', 'subagent_id'])) !== null && _f !== void 0 ? _f : firstString(args, ['sessionId', 'child_thread_id'])) !== null && _g !== void 0 ? _g : resultRec === null || resultRec === void 0 ? void 0 : resultRec.child_thread_id) !== null && _h !== void 0 ? _h : resultRec === null || resultRec === void 0 ? void 0 : resultRec.sessionId;
    var toolCalls = (_k = (_j = resultRec === null || resultRec === void 0 ? void 0 : resultRec.toolCalls) !== null && _j !== void 0 ? _j : resultRec === null || resultRec === void 0 ? void 0 : resultRec.tool_calls) !== null && _k !== void 0 ? _k : args.toolCalls;
    var state = tool.state;
    var running = state === 'running' || state === 'queued';
    var card = element('div', 'crusorai-task-tool-card');
    card.dataset.component = 'task-tool-card';
    card.style.setProperty('--task-agent-color', agentColor(agentName));
    // Always clickable — even while sub-agent is still starting (childId not yet in result)
    var navId = (_l = childId !== null && childId !== void 0 ? childId : tool.toolCallId) !== null && _l !== void 0 ? _l : tool.id;
    card.dataset.sessionId = String(navId);
    card.classList.add('is-clickable');
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', "Open sub-agent ".concat(description));
    console.log('[CrusorAI] taskToolCard render', { description: description, agentName: agentName, childId: childId, navId: navId, state: state });
    var navigate = function () {
        console.log('[CrusorAI] taskToolCard click -> navigateToSession', { description: description, childId: childId, navId: navId, target: childId !== null && childId !== void 0 ? childId : navId });
        var target = childId !== null && childId !== void 0 ? childId : navId;
        if (host.navigateToSession && target)
            host.navigateToSession(String(target));
        else
            console.warn('[CrusorAI] navigateToSession not available or no target', { host: !!host.navigateToSession, target: target });
    };
    card.addEventListener('click', navigate);
    card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navigate();
        }
    });
    var surface = element('div', 'crusorai-task-tool-surface');
    var iconWrap = element('span', running ? 'crusorai-task-tool-spinner' : 'crusorai-task-tool-icon');
    iconWrap.append(running ? element('span', 'crusorai-mini-spinner') : icon('robot'));
    surface.append(iconWrap);
    surface.append(element('span', 'crusorai-task-tool-title', agentName.charAt(0).toUpperCase() + agentName.slice(1)));
    var subtitleText = description + (isBackground ? ' (background)' : '') + (toolCalls ? " \u00B7 ".concat(toolCalls, " calls") : '');
    surface.append(element('span', 'crusorai-task-tool-subtitle', subtitleText));
    // Breathing when sub-agent is running — main shows live process
    if (running) {
        var breath = element('span', 'crusorai-scaffold-crusor');
        breath.style.marginLeft = '6px';
        surface.append(breath);
    }
    card.append(surface);
    // For batch: show each task as clickable row that navigates to its sub-agent session
    var batchTasks = args.tasks;
    if (Array.isArray(batchTasks) && batchTasks.length > 0) {
        var batchList = element('div', 'crusorai-task-tool-batch');
        var _loop_1 = function (i) {
            var t = String((_m = batchTasks[i]) !== null && _m !== void 0 ? _m : '');
            var short = t.slice(0, 80);
            var row = element('div', 'crusorai-task-tool-batch-row', element('span', 'crusorai-task-tool-batch-index', "".concat(i + 1, ".")), element('span', undefined, short));
            row.title = t;
            row.style.cursor = 'pointer';
            // Try to find sub-agent id for this task by matching goal/description in host's subAgents
            row.addEventListener('click', function () {
                var _a, _b, _c, _d, _e;
                var subs = (_d = (_c = (_b = (_a = host).getSubAgents) === null || _b === void 0 ? void 0 : _b.call(_a)) !== null && _c !== void 0 ? _c : host.subAgents) !== null && _d !== void 0 ? _d : [];
                var target;
                for (var _i = 0, subs_1 = subs; _i < subs_1.length; _i++) {
                    var s = subs_1[_i];
                    if (s.goal && t.includes(s.goal.slice(0, 20))) {
                        target = (_e = s.id) !== null && _e !== void 0 ? _e : s.subagent_id;
                        break;
                    }
                    if (s.description && t.includes(s.description.slice(0, 20))) {
                        target = s.id;
                        break;
                    }
                }
                if (!target)
                    target = childId !== null && childId !== void 0 ? childId : navId;
                if (target && host.navigateToSession)
                    host.navigateToSession(String(target));
            });
            batchList.append(row);
        };
        for (var i = 0; i < batchTasks.length; i++) {
            _loop_1(i);
        }
        card.append(batchList);
    }
    else {
        // Show full task prompt below subtitle so user can see what the sub-agent is doing (was only short "Research")
        var fullTask = (_o = firstString(args, ['prompt', 'task', 'description', 'goal'])) !== null && _o !== void 0 ? _o : '';
        if (fullTask && fullTask !== description) {
            card.append(element('div', 'crusorai-task-tool-task', fullTask.slice(0, 500)));
        }
        else if (fullTask) {
            card.append(element('div', 'crusorai-task-tool-task', fullTask.slice(0, 500)));
        }
    }
    if (childId) {
        var action = element('div', 'crusorai-task-tool-action', icon('arrow-up-right'));
        card.append(action);
    }
    return card;
}
function familyBody(tool, host) {
    var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z, _0, _1, _2;
    var presentation = crusorAIToolPresentation(tool.name);
    if (presentation.family === 'terminal' || presentation.family === 'process') {
        return terminalBody(tool, host);
    }
    var args = record(tool.arguments);
    var result = resultRecord(tool.result);
    var body = element('div', "crusorai-tool-body crusorai-family-".concat(presentation.family));
    body.dataset.rendererFamily = presentation.family;
    var target = displayTarget(tool);
    if (presentation.family === 'file-read') {
        var lines = (_d = (_a = firstString(result, ['lines', 'line_count'])) !== null && _a !== void 0 ? _a : (_c = (_b = firstString(result, ['content'])) === null || _b === void 0 ? void 0 : _b.split('\n').length) === null || _c === void 0 ? void 0 : _c.toString()) !== null && _d !== void 0 ? _d : '—';
        body.append(toolFields([['Path', target], ['Lines', lines], ['Encoding', 'UTF-8']]));
        var content = (_e = firstString(result, ['content'])) !== null && _e !== void 0 ? _e : boundedText(tool.result, 800);
        body.append(element('pre', 'crusorai-tool-pre crusorai-code-preview', content.slice(0, 800)));
        body.append(element('div', 'crusorai-tool-actions', button('Open file', 'crusorai-link-button', function () { return host.revealFile(target); }, 'go-to-file'), copyButton(target, host)));
    }
    else if (presentation.family === 'file-write') {
        var rawText = (_f = firstString(result, ['diff'])) !== null && _f !== void 0 ? _f : boundedText((_g = result === null || result === void 0 ? void 0 : result.diff) !== null && _g !== void 0 ? _g : tool.result, 600);
        var diff = rawText.includes('Diff preview:\n') ? rawText.split('Diff preview:\n')[1] : rawText;
        var receiptMatch = /lines added:\s*(\d+),\s*removed:\s*(\d+)/i.exec(typeof tool.result === 'string' ? tool.result : '');
        var stats = (_h = (receiptMatch ? { added: Number(receiptMatch[1]), removed: Number(receiptMatch[2]) } : undefined)) !== null && _h !== void 0 ? _h : diffStats(diff);
        var rows = [['File', target], ['Change', stats ? "+".concat(stats.added, " \u2212").concat(stats.removed) : ((_j = firstString(result, ['change'])) !== null && _j !== void 0 ? _j : '—')]];
        // 'syntax valid' was a second always-true row; only surface a receipt the
        // tool actually reported.
        var receipt = firstString(result, ['receipt', 'syntax']);
        if (receipt) {
            rows.push(['Receipt', receipt]);
        }
        body.append(toolFields(rows));
        body.append(diffPreview(diff));
        body.append(element('div', 'crusorai-tool-actions', button('Open native diff', 'crusorai-link-button', function () { return host.openDiff(tool.id); }, 'diff'), button('Reveal file', 'crusorai-link-button', function () { return host.revealFile(target); }, 'go-to-file')));
    }
    else if (presentation.family === 'search') {
        body.append(toolFields([['Query', target], ['Scope', 'workspace'], ['Matches', (_k = firstString(result, ['matches', 'count'])) !== null && _k !== void 0 ? _k : '—']]));
        var matches = (_l = result === null || result === void 0 ? void 0 : result.matches) !== null && _l !== void 0 ? _l : result === null || result === void 0 ? void 0 : result.results;
        if (Array.isArray(matches) && matches.length) {
            var list = element('div', 'crusorai-search-results');
            for (var _i = 0, _3 = matches.slice(0, 5); _i < _3.length; _i++) {
                var m = _3[_i];
                list.append(element('div', 'crusorai-search-row', element('code', undefined, typeof m === 'string' ? m : boundedText(m, 80)), element('span', undefined, '')));
            }
            body.append(list);
        }
        else {
            body.append(element('pre', 'crusorai-tool-pre', boundedText(result !== null && result !== void 0 ? result : tool.arguments, 500)));
        }
        body.append(element('div', 'crusorai-tool-actions', button('Open Search', 'crusorai-link-button', function () { return host.revealFile(target); }, 'search')));
    }
    else if (presentation.family === 'verification') {
        body.append(element('div', 'crusorai-tool-checks', element('div', undefined, icon('pass-filled'), element('span', undefined, 'Typecheck'), element('strong', undefined, tool.state === 'passed' ? 'passed' : tool.state === 'running' ? 'running' : 'queued')), element('div', undefined, tool.state === 'running' ? element('span', 'crusorai-mini-spinner') : icon('circle-outline'), element('span', undefined, 'Browser callback'), element('strong', undefined, tool.state === 'passed' ? 'passed' : tool.state === 'running' ? 'running' : 'queued')), element('div', undefined, icon('circle-outline'), element('span', undefined, 'Destination assertion'), element('strong', undefined, 'queued'))));
        body.append(element('div', 'crusorai-tool-actions', button('Open evidence', 'crusorai-link-button', function () { return void 0; }, 'beaker')));
    }
    else if (presentation.family === 'web') {
        body.append(toolFields([['URL', target], ['Status', (_m = firstString(result, ['status'])) !== null && _m !== void 0 ? _m : '200 OK'], ['Received', (_o = firstString(result, ['size'])) !== null && _o !== void 0 ? _o : '—']]));
        body.append(element('pre', 'crusorai-tool-pre', boundedText(result !== null && result !== void 0 ? result : tool.arguments, 500)));
        body.append(element('div', 'crusorai-tool-actions', button('Open source', 'crusorai-link-button', function () { return host.revealFile(target); }, 'link'), copyButton(target, host)));
    }
    else if (presentation.family === 'browser') {
        // Hermes backend receipts (browser_tools.py): honest per-tool fields.
        // The lab-era rows (a Page field and a hardcoded viewport — puppeteer
        // shapes of a backend that never ran on user machines), the fake
        // 'document' line, and the reveal-on-URL buttons are retired:
        // visible testing (owner 2026-09-07) shows the EVIDENCE here — the
        // screenshot image, the session recording, the ref the agent acted on.
        if (tool.name === 'browser_screenshot') {
            var raw = typeof tool.result === 'string' ? tool.result : '';
            var saved_1 = (_p = /Screenshot saved:\s*([^\s(]+)/.exec(raw)) === null || _p === void 0 ? void 0 : _p[1];
            body.append(toolFields([
                ['Saved', saved_1 !== null && saved_1 !== void 0 ? saved_1 : '—'],
                ['Quality', /visual quality passed/i.test(raw) ? 'passed' : tool.state === 'running' ? 'running' : tool.state === 'failed' ? 'failed' : '—'],
            ]));
            if (saved_1) {
                var src = host.resourceSrc(saved_1);
                if (src) {
                    var img = element('img', 'crusorai-browser-screenshot');
                    img.src = src;
                    img.alt = "Screenshot ".concat(saved_1);
                    body.append(img);
                }
                body.append(element('div', 'crusorai-tool-actions', button('Reveal screenshot', 'crusorai-link-button', function () { return host.revealFile(saved_1); }, 'device-camera'), copyButton(saved_1, host)));
            }
        }
        else if (tool.name === 'browser_navigate') {
            var recording_1 = firstString(result, ['recording']);
            body.append(toolFields([
                ['URL', (_q = firstString(args, ['url'])) !== null && _q !== void 0 ? _q : target],
                ['Title', (_r = firstString(result, ['title'])) !== null && _r !== void 0 ? _r : '—'],
                ['Elements', (_s = firstString(result, ['element_count'])) !== null && _s !== void 0 ? _s : '—'],
            ]));
            var snapshot = firstString(result, ['snapshot']);
            if (snapshot) {
                body.append(element('pre', 'crusorai-tool-pre', boundedText(snapshot, 600)));
            }
            if (recording_1) {
                // The visible-testing artifact (hermes record start/stop): one
                // click to watch what the agent did in the window.
                body.append(element('div', 'crusorai-tool-actions', button('Watch session recording', 'crusorai-link-button', function () { return host.revealFile(recording_1); }, 'device-camera'), copyButton(recording_1, host)));
            }
            else {
                body.append(element('div', 'crusorai-tool-actions', copyButton((_t = firstString(args, ['url'])) !== null && _t !== void 0 ? _t : target, host)));
            }
        }
        else if (tool.name === 'browser_click' || tool.name === 'browser_type' || tool.name === 'browser_press') {
            body.append(toolFields([
                ['Element', (_v = (_u = firstString(args, ['ref'])) !== null && _u !== void 0 ? _u : firstString(args, ['key'])) !== null && _v !== void 0 ? _v : '—'],
                ['Text', (_w = firstString(args, ['text'])) !== null && _w !== void 0 ? _w : '—'],
                ['Done', (_x = firstString(result, ['clicked', 'typed', 'pressed'])) !== null && _x !== void 0 ? _x : (tool.state === 'passed' ? 'yes' : tool.state === 'failed' ? 'no' : '…')],
            ]));
        }
        else if (tool.name === 'browser_console') {
            body.append(toolFields([
                ['Expression', (_y = firstString(args, ['expression'])) !== null && _y !== void 0 ? _y : '—'],
                ['Messages', (_z = firstString(result, ['total_messages'])) !== null && _z !== void 0 ? _z : '—'],
                ['JS errors', (_0 = firstString(result, ['total_errors'])) !== null && _0 !== void 0 ? _0 : '—'],
            ]));
            var evaluated = firstString(result, ['result']);
            if (evaluated) {
                body.append(element('pre', 'crusorai-tool-pre', boundedText(evaluated, 400)));
            }
        }
        else {
            body.append(toolFields([
                ['URL', (_1 = firstString(args, ['url'])) !== null && _1 !== void 0 ? _1 : target],
                ['Detail', (_2 = firstString(result, ['count', 'scrolled', 'url', 'success'])) !== null && _2 !== void 0 ? _2 : '—'],
            ]));
            body.append(element('pre', 'crusorai-tool-pre', boundedText(result !== null && result !== void 0 ? result : tool.arguments, 400)));
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
    else if (presentation.family === 'session') {
        body.append(toolFields([['Query', target], ['Sessions', '2'], ['Model calls', '0']]));
        body.append(element('pre', 'crusorai-tool-pre', boundedText(result !== null && result !== void 0 ? result : tool.arguments, 400)));
    }
    else if (presentation.family === 'subagent' || tool.name.startsWith('delegate_to_subagent')) {
        // OpenCode parity: task-tool-card clickable navigation
        return taskToolCard(tool, host);
    }
    else if (presentation.family === 'code' || presentation.family === 'scaffold') {
        // Field 2026-09-10: this body hardcoded a fake RUNTIME value —
        // invented text on a JS scaffolding call. The card shows the call's
        // OWN fields and the honest state, nothing else.
        var scaffoldFields = [];
        var targetPath = firstString(args, ['path', 'project_path', 'projectPath', 'directory', 'dir']);
        if (targetPath) {
            scaffoldFields.push(['Location', targetPath]);
        }
        var template = firstString(args, ['template', 'framework', 'stack']);
        if (template) {
            scaffoldFields.push(['Template', template]);
        }
        scaffoldFields.push(['Status', stateLabel(tool.state)]);
        body.append(toolFields(scaffoldFields));
        var detail = result !== null && result !== void 0 ? result : boundedText(tool.arguments, 400);
        if (detail) {
            body.append(element('pre', 'crusorai-tool-pre crusorai-terminal-output', boundedText(detail, 600).slice(0, 700)));
        }
    }
    else {
        // Generic families: a STRING result is model prose (think reasoning,
        // salvage notes). Render it through the same markdown pass as
        // assistant copy, inside the hermes expandable (cap + fade + chevron).
        // The old raw JSON dump leaked `**Thinking:**` and \n escapes into
        // the panel (owner verdict: disgusting). Arguments stay reachable,
        // collapsed, honestly labeled.
        var resultText = typeof tool.result === 'string' ? tool.result : '';
        // Models often self-announce ("**Thinking:** ...") — the card title
        // already says what the tool is, so a duplicated label is fake chrome.
        // Presentation-only strip of the leading self-labels.
        // Both self-announce shapes leak in the field: "💭 **Thinking:**" and
        // "**Thinking:**" — the label marker may sit on either side of the
        // bold wrapper (and the 💭 on either side of the label). One pattern
        // per position, tolerant of order.
        var prose = resultText
            .replace(/^\s*(?:\*\*)?\s*💭?\s*(?:\*\*)?\s*thinking\s*:?\s*(?:\*\*)?\s*:?\s*/i, '')
            .replace(/^\s*💭\s+/, '')
            .replace(/^\s*(?:\*\*)?\s*reasoning\s*:?\s*(?:\*\*)?\s*:?\s*/i, '');
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
                var argsDetails = element('details', 'crusorai-tool-args-details');
                argsDetails.append(element('summary', 'crusorai-tool-args-summary', 'Arguments'));
                argsDetails.append(labeledPayload('Arguments', tool.arguments));
                body.append(argsDetails);
            }
        }
        else {
            body.append(labeledPayload('Details', { arguments: tool.arguments, result: tool.result }));
        }
    }
    var fileTarget = firstString(tool.arguments, ['path', 'file_path', 'resource']);
    if (fileTarget && presentation.family !== 'file-read' && presentation.family !== 'file-write') {
        if (!body.querySelector('.crusorai-tool-actions'))
            body.append(element('div', 'crusorai-tool-actions', button('Open file', 'crusorai-link-button', function () { return host.revealFile(fileTarget); }, 'go-to-file')));
    }
    return body;
}
function toolRow(tool, host, openTools, pendingClarify) {
    // Hermes (message-parts ChainToolFallback): a clarify call renders its own
    // widget card — the interactive question while it blocks, the settled Q&A
    // after — never a generic collapsible tool row.
    if (tool.name === 'clarify' && pendingClarify !== undefined) {
        // The card is a widget, not a disclosure row; the toolSection slot
        // only appends HTMLElements, so the cast keeps the signature honest.
        return clarifyCard(tool, host, openTools, pendingClarify);
    }
    var presentation = crusorAIToolPresentation(tool.name);
    var isPending = tool.state === 'running' || tool.state === 'queued';
    var details = element('details', "crusorai-tool-row is-".concat(tool.state));
    details.dataset.component = 'tool-trigger';
    details.dataset.conversationScaffold = '';
    details.dataset.toolId = tool.id;
    details.dataset.toolName = tool.name;
    var shouldDefaultOpen = presentation.defaultOpen === 'always' || (presentation.defaultOpen === 'running' && (tool.state === 'running' || tool.state === 'approval'));
    details.open = openTools.has(tool.id) || shouldDefaultOpen;
    // Hermes wording (ThinkingDisclosure): a live block says "Thinking", a
    // settled one says "Thought" — the tool catalog title stays canonical for
    // other surfaces; the transcript row speaks hermes.
    var rowTitle = tool.name === 'think' ? (isPending ? 'Thinking' : 'Thought') : presentation.title;
    var titleSpan = element('strong', isPending ? 'crusorai-shimmer' : undefined, rowTitle);
    var targetText = displayTarget(tool);
    // Hermes quiet-card rule: the target echo must SAY something. When it
    // just repeats the tool name ("Think think"), it is noise — drop it.
    var targetMeaningful = !!targetText
        && targetText.toLowerCase() !== tool.name.toLowerCase()
        && targetText.toLowerCase() !== presentation.title.toLowerCase();
    var summary = element('summary', 'crusorai-tool-summary', tool.name === 'think' ? element('span', 'crusorai-glyph-spacer') : statusGlyph(tool.state), icon(presentation.icon), titleSpan, targetMeaningful ? element('span', 'crusorai-tool-target', targetText) : undefined, tool.duration ? element('span', 'crusorai-tool-duration', tool.duration) : undefined, isPending ? undefined : icon('chevron-right'));
    details.append(summary, familyBody(tool, host));
    details.addEventListener('toggle', function () { return details.open ? openTools.add(tool.id) : openTools.delete(tool.id); });
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
function toolSection(tools, host, openTools, live, showHeading, pendingClarify) {
    var _a, _b;
    if (showHeading === void 0) { showHeading = true; }
    var section = element('section', 'crusorai-tool-list');
    section.dataset.component = 'tool-list';
    if (showHeading) {
        section.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Actions'), element('span', 'crusorai-section-count', String(tools.length))));
    }
    var groups = splitRunGroups(tools);
    // Hermes: a SINGLE action is one bare row — never a collapsible run group
    // with a "(1)" count bubble wrapping its own duplicate header (owner
    // screenshot 2026-09-04: "Running dir /b (1)" over a "Terminal dir /b"
    // card said the same thing twice). Only 2+ calls earn a run summary.
    if (groups.length === 1 && groups[0].kind === 'run' && groups[0].tools.length === 1) {
        section.append(toolRow(groups[0].tools[0], host, openTools, pendingClarify));
        return section;
    }
    var _loop_2 = function (group) {
        if (group.kind === 'card') {
            section.append(toolRow(group.tool, host, openTools, pendingClarify));
            return "continue";
        }
        var runTools = group.tools;
        var key = (_b = (_a = runTools[0]) === null || _a === void 0 ? void 0 : _a.id) !== null && _b !== void 0 ? _b : "run-".concat(group.start);
        var runLive = live && runTools.some(function (tool) { return tool.state === 'running' || tool.state === 'queued'; });
        var details = element('details', "crusorai-tool-run".concat(runLive ? ' is-live' : ''));
        details.dataset.component = 'tool-run';
        details.dataset.conversationScaffold = '';
        details.dataset.runKey = key;
        details.open = runLive || openTools.has(key);
        details.addEventListener('toggle', function () {
            if (details.open) {
                openTools.add(key);
            }
            else {
                openTools.delete(key);
            }
        });
        var summary = element('summary', 'crusorai-tool-run-summary', runLive ? element('span', 'crusorai-mini-spinner') : icon('tools'), element('span', 'crusorai-tool-run-text', summarizeToolRun(runTools, runLive, function (tool) { var _a; return (_a = compactTarget(displayTarget(tool))) !== null && _a !== void 0 ? _a : tool.name; })), element('span', 'crusorai-tool-run-count', String(runTools.length)));
        details.append(summary);
        var body = element('div', 'crusorai-tool-run-body');
        for (var _c = 0, runTools_1 = runTools; _c < runTools_1.length; _c++) {
            var tool = runTools_1[_c];
            body.append(toolRow(tool, host, openTools, pendingClarify));
        }
        details.append(body);
        section.append(details);
    };
    for (var _i = 0, groups_1 = groups; _i < groups_1.length; _i++) {
        var group = groups_1[_i];
        _loop_2(group);
    }
    return section;
}
function engineStatus(model) {
    var _a, _b;
    var state = model.engineState;
    var tone = state === 'ready' ? 'ready' : state === 'starting' ? 'running' : state === 'crashed' || state === 'degraded' ? 'failed' : 'idle';
    var chip = element('span', "crusorai-engine-status is-".concat(tone), element('span', 'crusorai-status-dot'), state === 'ready' ? 'Crusor ready' : "Engine ".concat(state));
    var engineTitle = '';
    if (model.engineBuild && model.engineBuild !== 'unknown') {
        var short = model.engineBuild.split(/\s+/)[0];
        chip.append(element('span', 'crusorai-engine-build', short));
        engineTitle = "Engine build: ".concat(model.engineBuild);
    }
    // Freshness stamp next to the engine hash (see CRUSORAI_UI_STAMP): the
    // engine chip alone could not catch the 2026-09-08 field round where the
    // engine rebuilt but the workbench JS did not. An engine build dated
    // AFTER this stamp means the compiled workbench predates the engine.
    var engineDate = (_b = /\b\d{4}-\d{2}-\d{2}\b/.exec((_a = model.engineBuild) !== null && _a !== void 0 ? _a : '')) === null || _b === void 0 ? void 0 : _b[0];
    var stale = !!engineDate && engineDate > CRUSORAI_UI_STAMP;
    chip.append(element('span', 'crusorai-engine-build', "ui ".concat(CRUSORAI_UI_STAMP).concat(stale ? ' STALE' : '')));
    var uiTitle = "Workbench UI build: ".concat(CRUSORAI_UI_STAMP);
    chip.title = engineTitle ? "".concat(uiTitle, " \u00B7 ").concat(engineTitle) : uiTitle;
    if (stale) {
        chip.title = "Workbench UI build ".concat(CRUSORAI_UI_STAMP, " is OLDER than the engine build (").concat(model.engineBuild, ") \u2014 the engine rebuilt, the desktop workbench did not. Recompile the desktop app to pick up the current UI.");
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
    var ring = element('span', 'crusorai-todo-ring');
    ring.setAttribute('aria-hidden', 'true');
    return ring;
}
function planStrip(model, open, onToggle) {
    if (!model.plan.length) {
        return undefined;
    }
    var done = model.plan.filter(function (s) { return s.status === 'completed'; }).length;
    var anyActive = model.plan.some(function (s) { return s.status === 'in_progress'; });
    var details = element('details', 'crusorai-plan-strip');
    details.dataset.component = 'plan-strip';
    details.open = open !== null && open !== void 0 ? open : model.running;
    details.addEventListener('toggle', function () { return onToggle(details.open); });
    var summary = element('summary', 'crusorai-plan-strip-summary', icon('list-ordered'), element('strong', undefined, 'Plan'), element('span', undefined, "".concat(done, "/").concat(model.plan.length)), model.running && anyActive ? element('span', 'crusorai-plan-strip-state', element('span', 'crusorai-mini-spinner'), 'In progress') : undefined, icon('chevron-down'));
    var list = element('ol', 'crusorai-plan-strip-list');
    for (var _i = 0, _a = model.plan; _i < _a.length; _i++) {
        var step = _a[_i];
        list.append(element('li', "is-".concat(step.status), planStepGlyph(step.status), element('span', undefined, step.text)));
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
var thoughtKey = function (model) { var _a; return "thought:".concat((_a = model.sessionId) !== null && _a !== void 0 ? _a : 'session'); };
function createActivityState(tick) {
    var lastSignature = '';
    var quietSince;
    var verb = '';
    var revealed = false;
    var quietTimer;
    var revealTimer;
    var ticker;
    return {
        sync: function (model) {
            var _a;
            var parts = activityParts(model);
            // Thinking is "active" while a thought is the newest thing the turn has produced.
            if (model.running && ((_a = parts.at(-1)) === null || _a === void 0 ? void 0 : _a.type) === 'reasoning') {
                elapsedFor(thoughtKey(model), Date.now());
            }
            else {
                closeMeasurement(thoughtKey(model), Date.now());
            }
            var signature = activitySignature(parts);
            if (signature !== lastSignature) {
                lastSignature = signature;
                quietSince = undefined;
                if (quietTimer !== undefined) {
                    clearTimeout(quietTimer);
                    quietTimer = undefined;
                }
                if (model.running) {
                    quietTimer = setTimeout(function () { quietSince = Date.now(); tick(); }, TURN_QUIET_S * 1000);
                }
            }
            var name = draftingToolName(model.tools);
            var next = name && !toolNarratesWait(parts) ? toolPresentVerb(name) : '';
            if (next !== verb) {
                verb = next;
                revealed = false;
                if (revealTimer !== undefined) {
                    clearTimeout(revealTimer);
                    revealTimer = undefined;
                }
                if (verb) {
                    revealTimer = setTimeout(function () { revealed = true; tick(); }, DRAFTING_REVEAL_MS);
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
        row: function (model) {
            var parts = activityParts(model);
            var hint = model.cancelRequested ? 'Stopping safely' : statusHintLabel(model.compacting, verb, revealed);
            var slot = activityRowMode({
                parts: parts,
                working: model.running,
                awaitingInput: model.approval !== undefined,
                toolNarrating: toolNarratesWait(parts),
                hint: hint,
                quietSince: quietSince,
            });
            if (!slot) {
                return undefined;
            }
            var seconds = elapsedSeconds(Date.now(), activityOrigin({ compacting: model.compacting, turnStartedAt: model.turnStartedAt, quietSince: quietSince }));
            var row = element('div', 'crusorai-scaffold-status');
            row.dataset.conversationScaffold = '';
            row.dataset.slot = slot;
            row.setAttribute('aria-label', hint || UNNAMED_WAIT_LABEL);
            row.setAttribute('aria-live', 'polite');
            row.setAttribute('role', 'status');
            var breathe = element('span', 'crusorai-scaffold-crusor');
            breathe.setAttribute('aria-hidden', 'true');
            var meta = element('span', 'crusorai-scaffold-meta', element('span', undefined, formatElapsed(seconds)));
            row.append.apply(row, __spreadArray(__spreadArray([breathe], (hint ? [element('span', 'crusorai-shimmer crusorai-scaffold-hint', hint)] : []), false), [meta], false));
            return row;
        },
        /**
         * How long the CURRENT turn's thinking ran, once it has stopped running. The measurement
         * is armed while the last thing the turn produced is a thought and closed the moment the
         * turn moves on, so the number survives every repaint of the row that watched it.
         */
        thoughtSeconds: function (model) {
            return measuredDuration(thoughtKey(model));
        },
        dispose: function () {
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
function thinkingBlock(reasoning, openTools, live, seconds, partKey) {
    reasoning = separateGluedReasoningBlocks(reasoning);
    var key = partKey || 'thought';
    var details = element('details', 'crusorai-thought-row');
    details.dataset.component = 'disclosure';
    details.dataset.conversationScaffold = '';
    details.dataset.disclosureKey = key;
    details.open = true;
    details.addEventListener('toggle', function () {
        if (details.open) {
            openTools.add(key);
        }
        else {
            openTools.delete(key);
        }
    });
    // Split accumulated reasoning into separate blocks (one per LLM call)
    var body = element('div', 'crusorai-thought-body');
    var blocks = reasoning.split(/\n\n---\n\n/);
    for (var _i = 0, blocks_1 = blocks; _i < blocks_1.length; _i++) {
        var block = blocks_1[_i];
        var trimmed = block.trim();
        if (trimmed) {
            body.append(element('p', undefined, trimmed));
        }
    }
    details.append(element('summary', 'crusorai-disclosure-row', element('span', 'crusorai-disclosure-stack', icon('brain'), element('strong', live ? 'crusorai-shimmer' : undefined, live ? 'Thinking' : 'Thought')), seconds !== undefined ? element('span', 'crusorai-scaffold-meta', formatElapsed(seconds)) : undefined, element('span', 'crusorai-disclosure-caret', '\u25be')), body);
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
function assistantTurn(spec, host, openTools) {
    var live = spec.live;
    var response = element('section', "crusorai-assistant-message".concat(live ? ' crusorai-breathing-edge is-streaming' : ''));
    if (spec.current) {
        response.dataset.component = 'session-turn';
    }
    response.append(element('div', 'crusorai-assistant-label', icon('crusor'), element('strong', undefined, 'Crusor'), live ? element('span', 'crusorai-stream-label', spec.cancelRequested ? 'Stopping.' : 'Working') : undefined));
    // Reasoning parts are tracked INLINE in the parts array (kind='reasoning') so their
    // chronological position relative to text and tools is always preserved exactly.
    // This mirrors the Hermes approach (message.content is a single ordered array).
    var reasoningParts = (spec.reasoningParts || []).filter(function (p) { return p && p.text; });
    // Parts are the ordering source. A turn that predates them (or somehow
    // carries text without a single text part) falls back to the legacy
    // single-block paint so the answer can never be dropped by a missing
    // timeline.
    var parts = spec.parts.length
        ? spec.parts
        : (spec.assistantText ? [{ kind: 'text', text: spec.assistantText }] : []);
    var toolsById = new Map(spec.tools.map(function (t) { return [t.id, t]; }));
    var lastTextIndex = -1;
    for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (part.kind === 'text' && part.text) {
            lastTextIndex = i;
        }
    }
    // The streaming slot rides the LAST text segment only: the painter's fast
    // path patches exactly that node per token; earlier segments are frozen.
    var run = [];
    var flushRun = function () {
        if (!run.length) {
            return;
        }
        response.append(toolSection(run, host, openTools, live, false, spec.clarify));
        run = [];
    };
    parts.forEach(function (part, index) {
        if (part.kind === 'reasoning') {
            // Flush any accumulated tool run BEFORE the reasoning block (preserves order)
            flushRun();
            var rp = reasoningParts[part.reasoningIndex];
            if (rp && rp.text) {
                // A reasoning block is "live" (spinner + growing text) only when it is the
                // last part in the timeline and the turn is still running.
                var isLastPart = index === parts.length - 1;
                response.append(thinkingBlock(rp.text, openTools, live && isLastPart, spec.thoughtSeconds, "".concat(spec.turnKey || 'turn', ":").concat(part.reasoningIndex)));
            }
            return;
        }
        if (part.kind === 'tool') {
            var tool = toolsById.get(part.toolId);
            if (tool) {
                run.push(tool);
            }
            return;
        }
        if (!part.text) {
            return;
        }
        flushRun();
        response.append(markdownCopy(part.text, spec.current && index === lastTextIndex ? 'session-turn-content' : undefined));
    });
    flushRun();
    // A tool with no part (a replay that lost its start frame) must still show.
    var inTimeline = new Set(parts.filter(function (p) { return p.kind === 'tool'; }).map(function (p) { return p.toolId; }));
    var orphans = spec.tools.filter(function (t) { return !inTimeline.has(t.id); });
    if (orphans.length) {
        response.append(toolSection(orphans, host, openTools, live, false, spec.clarify));
    }
    if (spec.assistantText && lastTextIndex < 0) {
        response.append(markdownCopy(spec.assistantText, spec.current ? 'session-turn-content' : undefined));
    }
    if (spec.assistantText && !live) {
        response.append(copyButton(spec.assistantText, host));
    }
    return response;
}
function transcript(model, host, openTools, liveThoughtSeconds) {
    var _a, _b, _c, _d, _e, _f, _g, _h, _j;
    var scroll = element('div', 'crusorai-transcript-scroll');
    var lane = element('div', 'crusorai-transcript-lane');
    // History: previous turns (user → agent) preserved wireframe style, no breathing
    for (var _i = 0, _k = model.history; _i < _k.length; _i++) {
        var turn = _k[_i];
        if (turn.userMessage)
            lane.append(element('div', 'crusorai-user-message', turn.userMessage));
        if (turn.assistantText || turn.parts.length || turn.tools.length) {
            lane.append(assistantTurn({
                reasoningParts: turn.reasoningParts,
                assistantText: turn.assistantText,
                parts: turn.parts,
                tools: turn.tools,
                live: false,
                turnKey: "history:".concat(model.sessionId || 's'),
            }, host, openTools));
        }
        if (turn.subAgents.length) {
            var subAgents = element('section', 'crusorai-subagent-list');
            subAgents.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'crusorai-section-count', String(turn.subAgents.length))));
            for (var _l = 0, _m = turn.subAgents; _l < _m.length; _l++) {
                var subAgent = _m[_l];
                var row = element('div', "crusorai-subagent-row is-".concat(subAgent.state), element('span', undefined, ''), element('span', 'crusorai-subagent-goal', (_a = subAgent.goal) !== null && _a !== void 0 ? _a : 'Sub-agent task'), element('span', "crusorai-subagent-state is-".concat(subAgent.state), subAgent.state));
                if (subAgent.duration)
                    row.append(element('span', 'crusorai-subagent-duration', subAgent.duration));
                subAgents.append(row);
            }
            lane.append(subAgents);
        }
        // Hermes pattern: no green confetti for success -- the answer IS the
        // completion receipt. Only real deviations (cancelled, failed) get a row.
        if (turn.turnOutcome === 'cancelled' || turn.turnOutcome === 'failed') {
            var label = turn.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
            var iconName = turn.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
            var row = element('div', "crusorai-turn-receipt is-".concat(turn.turnOutcome), icon(iconName), element('span', undefined, label));
            var intr = turn.interrupt;
            if (intr && (intr.landed > 0 || intr.dropped > 0)) {
                var bits = [];
                if (intr.landed > 0) {
                    bits.push("".concat(intr.landed, " landed"));
                }
                if (intr.dropped > 0) {
                    bits.push("".concat(intr.dropped, " dropped"));
                }
                row.append(element('span', 'crusorai-receipt-meta', "\u00B7 ".concat(bits.join(' · '))));
            }
            lane.append(row);
        }
        // same closing rollup for past turns (first-touched order, +/- summed)
        var turnFiles = deriveChangedFiles(turn.tools);
        if (turnFiles.length) {
            var card = element('div', 'crusorai-changed-files');
            card.dataset.component = 'changed-files';
            card.append(element('div', 'crusorai-changed-files-head', element('span', undefined, "".concat(turnFiles.length, " file").concat(turnFiles.length === 1 ? '' : 's', " changed"))));
            var rows = element('div', 'crusorai-changed-files-rows');
            var _loop_3 = function (file) {
                var row = element('div', 'crusorai-changed-file-row is-activatable', icon('file'), element('span', 'crusorai-changed-file-name', file.name), element('span', 'crusorai-diff-count', element('span', 'is-added', "+".concat(file.added)), element('span', 'is-removed', "\u2212".concat(file.removed))));
                row.title = file.path;
                var target = file.path;
                row.addEventListener('click', function () { return host.revealFile(target); });
                rows.append(row);
            };
            for (var _o = 0, turnFiles_1 = turnFiles; _o < turnFiles_1.length; _o++) {
                var file = turnFiles_1[_o];
                _loop_3(file);
            }
            card.append(rows);
            lane.append(card);
        }
    }
    // Current turn (breathing when running)
    if (model.userMessage) {
        lane.append(element('div', 'crusorai-user-message', model.userMessage));
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
            turnKey: "current:".concat(model.sessionId || 's'),
        }, host, openTools));
    }
    if (model.subAgents.length) {
        var subAgents = element('section', 'crusorai-subagent-list');
        subAgents.dataset.component = 'subagent-list';
        subAgents.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'crusorai-section-count', String(model.subAgents.length))));
        var _loop_4 = function (subAgent) {
            var state = subAgent.state;
            var desc = (_c = (_b = subAgent.description) !== null && _b !== void 0 ? _b : subAgent.goal) !== null && _c !== void 0 ? _c : 'Sub-agent task';
            var childId = (_d = subAgent.childThreadId) !== null && _d !== void 0 ? _d : subAgent.id;
            var isRunning = state === 'running' || state === 'pending';
            var row = element('div', "crusorai-subagent-row is-".concat(state).concat(childId ? ' is-clickable' : ''));
            if (childId) {
                row.dataset.sessionId = childId;
                row.tabIndex = 0;
                row.setAttribute('role', 'button');
                row.addEventListener('click', function () { if (host.navigateToSession)
                    host.navigateToSession(childId); });
                row.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    if (host.navigateToSession)
                        host.navigateToSession(childId);
                } });
            }
            var iconEl = isRunning ? element('span', 'crusorai-mini-spinner') : icon(state === 'completed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'cancelled' ? 'circle-slash' : 'circle-outline');
            var goalEl = element('span', 'crusorai-subagent-goal', desc);
            goalEl.style.setProperty('--task-agent-color', agentColor((_f = (_e = subAgent.agentName) !== null && _e !== void 0 ? _e : subAgent.mode) !== null && _f !== void 0 ? _f : 'general'));
            row.append(iconEl, goalEl, element('span', "crusorai-subagent-state is-".concat(state), state));
            if (subAgent.background)
                row.append(element('span', 'crusorai-subagent-badge', 'bg'));
            if (subAgent.toolCalls)
                row.append(element('span', 'crusorai-subagent-calls', "".concat(subAgent.toolCalls, " calls")));
            if (subAgent.duration)
                row.append(element('span', 'crusorai-subagent-duration', subAgent.duration));
            if (childId)
                row.append(element('span', 'crusorai-subagent-action', icon('arrow-up-right')));
            subAgents.append(row);
        };
        for (var _p = 0, _q = model.subAgents; _p < _q.length; _p++) {
            var subAgent = _q[_p];
            _loop_4(subAgent);
        }
        lane.append(subAgents);
    }
    if (model.turnOutcome === 'cancelled' || model.turnOutcome === 'failed') {
        var label = model.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
        var iconName = model.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
        var row = element('div', "crusorai-turn-receipt is-".concat(model.turnOutcome), icon(iconName), element('span', undefined, label));
        var intr = model.interrupt;
        if (intr && (intr.landed > 0 || intr.dropped > 0)) {
            var bits = [];
            if (intr.landed > 0) {
                bits.push("".concat(intr.landed, " landed"));
            }
            if (intr.dropped > 0) {
                bits.push("".concat(intr.dropped, " dropped"));
            }
            row.append(element('span', 'crusorai-receipt-meta', "\u00B7 ".concat(bits.join(' · '))));
        }
        lane.append(row);
    }
    // hermes changed-files-card: the turn-closing "N files changed" rollup.
    var changed = changedFilesCard(model, host);
    if (changed) {
        lane.append(changed);
    }
    if (model.voiceHeard) {
        var heard = model.voiceHeard;
        if (heard.ok) {
            lane.append(element('div', 'crusorai-context-status-row is-info', icon('lightbulb'), element('span', undefined, "\uD83C\uDFA4 Heard: ".concat(heard.text.slice(0, 200)))));
        }
        else {
            lane.append(element('div', 'crusorai-context-status-row is-warning', icon('warning'), element('span', undefined, "\uD83C\uDFA4 Voice error: ".concat((_g = heard.error) !== null && _g !== void 0 ? _g : 'unknown'))));
        }
    }
    if (model.degraded) {
        lane.append(element('div', 'crusorai-context-status-row is-warning', icon('warning'), element('span', undefined, model.degraded)));
    }
    // Hermes port (assistant-ui/thread/status.tsx ResponseLoadingIndicator):
    // while the turn runs, the TAIL carries one activity row -- crusor dot +
    // wait hint + LIVE elapsed seconds. Turn ended -> the row is gone;
    // history turns never grow one (tail-only rule). The hint names REAL
    // state, never a guess: a live tool card means the tool is the thing
    // working (owner run: the row claimed "Waiting on the model" for 4min
    // while dir /s /b was the one grinding); only a truly idle gap between
    // tool and model may fall through to the generic text.
    if (model.running && !model.llmReasoningLive) {
        // `llmReasoningLive`: the Thinking card is the live activity — the row
        // would narrate the same wait twice (field 2026-09-17: while the model
        // thinks, the tail showed both a Thinking card and an Asking… row).
        var liveTool = __spreadArray([], model.tools, true).reverse().find(function (tool) { return tool.state === 'running' || tool.state === 'queued'; });
        var hint = void 0;
        var stalled = model.stalled === true;
        if (liveTool) {
            var target = (_h = compactTarget(displayTarget(liveTool))) !== null && _h !== void 0 ? _h : liveTool.name;
            hint = liveTool.state === 'queued'
                ? "Queued: ".concat(liveTool.name, "\u2026")
                : "Running ".concat(target, "\u2026");
        }
        else if (model.llmStatus) {
            var attempt = model.llmStatus.attempt > 1 ? " \u2014 attempt ".concat(model.llmStatus.attempt) : '';
            hint = "Asking ".concat(model.llmStatus.model || 'model').concat(attempt, "\u2026");
        }
        else if (model.stalled) {
            // Hermes wording discipline: silence is not completion and not an
            // error — state the fact and keep the Stop option, without
            // screaming failure or pretending progress.
            hint = 'No activity for 5:00 \u2014 the turn is still running, but nothing has arrived.';
            stalled = true;
        }
        else {
            hint = 'Waiting on the model\u2026';
        }
        var row = element('div', "crusorai-context-status-row is-info crusorai-activity-row".concat(stalled ? ' is-stalled' : ''));
        row.append(element('span', 'crusorai-activity-dot'));
        row.append(element('span', undefined, hint));
        row.append(elapsedSpan(model.turnStartedAt));
        lane.append(row);
        // The anatomy inspector: the LIVE request, role+head per message —
        // "why 8 messages for hi?" becomes one click in the product, not a
        // chat question. Data rides the llm.request frame (factory caps the
        // heads); display slices are presentation guards only.
        var heads = (_j = model.llmHeads) !== null && _j !== void 0 ? _j : [];
        if (heads.length) {
            var anatomy = element('details', 'crusorai-llm-anatomy');
            anatomy.append(element('summary', 'crusorai-llm-anatomy-summary', element('span', undefined, "What the model sees \u2014 ".concat(heads.length, " message").concat(heads.length === 1 ? '' : 's'))));
            var list = element('div', 'crusorai-llm-anatomy-list');
            for (var _r = 0, _s = heads.slice(0, 32); _r < _s.length; _r++) {
                var head = _s[_r];
                var roleLabel = head.role === 'human' ? 'user'
                    : head.role === 'ai' ? 'assistant' : head.role;
                list.append(element('div', 'crusorai-llm-anatomy-row', element('span', "crusorai-llm-anatomy-role is-".concat(roleLabel), roleLabel), element('code', 'crusorai-llm-anatomy-head', (head.head || '').replace(/\s+/g, ' ').slice(0, 140))));
            }
            anatomy.append(list);
            lane.append(anatomy);
        }
    }
    if (model.contextStatus) {
        var status = model.contextStatus;
        var percent = typeof status.usagePercent === 'number' && status.usagePercent > 0
            ? " (".concat(Math.min(100, Math.round(status.usagePercent)), "% of the context window)")
            : '';
        lane.append(element('div', "crusorai-context-status-row is-".concat(status.severity), icon(status.severity === 'warning' ? 'warning' : 'lightbulb'), element('span', undefined, status.message + percent)));
    }
    if (model.engineFault) {
        var fault = model.engineFault;
        var followUp = fault.retrying
            ? " Retrying automatically (attempt ".concat(fault.attempts + 1, " of 3).")
            : ' Crusor stopped retrying on its own.';
        lane.append(element('div', 'crusorai-error-row is-engine-fault', icon('error'), element('span', undefined, fault.message + followUp), button('Retry engine', 'crusorai-link-button', host.retryEngine)));
    }
    if (model.error) {
        var setup = model.engineSetupError;
        lane.append(element('div', 'crusorai-error-row', icon(setup ? 'settings-gear' : 'warning'), element('span', undefined, setup ? "Crusor engine setup: ".concat(model.error) : model.error), setup
            ? button('Open Settings', 'crusorai-link-button', host.openEngineSettings, 'settings-gear')
            : button('Retry', 'crusorai-link-button', host.retryEngine)));
    }
    // OpenCode parity: child header parent / child + agent-designed prompt as user message
    if (model.isChild) {
        var delegatedTask = model.userMessage || model.subAgentGoal || '';
        var parentTitle = model.parentTitle || 'Parent session';
        var childTitle = delegatedTask.slice(0, 60) || 'Sub-agent';
        // Header like opencode: Spawn agents to analyze folders / Analyze playground folder
        var header = element('div', 'crusorai-child-header');
        var parentBtn = element('button', 'crusorai-child-header-parent', parentTitle);
        if (model.parentSessionId && host.navigateToSession) {
            var pId_1 = model.parentSessionId;
            parentBtn.addEventListener('click', function () { return host.navigateToSession(pId_1); });
        }
        header.append(parentBtn, element('span', undefined, ' / '), element('h1', 'crusorai-child-header-child', childTitle));
        lane.prepend(header);
        if (delegatedTask) {
            lane.append(element('div', 'crusorai-user-message', delegatedTask.slice(0, 800)));
        }
        var banner = element('div', 'crusorai-child-banner');
        banner.dataset.component = 'child-banner';
        banner.append(icon('info'), element('span', undefined, 'Sub-agent session — prompt disabled'));
        if (model.parentSessionId && host.navigateToSession) {
            var parentId_1 = model.parentSessionId;
            banner.append(button('Back to Parent', 'crusorai-link-button', function () { return host.navigateToSession(parentId_1); }, 'arrow-left'));
        }
        lane.append(banner);
    }
    scroll.append(lane);
    return scroll;
}
var STARTER_PROMPTS = [
    'Review this workspace and tell me what it does',
    'Find where the safety approval flow lives and explain it',
    'Run the project tests and fix the first failure',
];
/**
 * Shown only when there is genuinely nothing to render and nothing is broken: engine
 * up, workspace chosen, no turn yet. Setup and workspace-selection states have their
 * own surfaces, and a starter grid layered over them reads as a bug.
 */
function emptyState(model, host) {
    if (model.running || model.history.length || model.userMessage || model.assistantText || model.tools.length) {
        return undefined;
    }
    if (model.engineSetupError || model.noWorkspace || model.workspaceSelectionRequired) {
        return undefined;
    }
    var wrap = element('section', 'crusorai-empty-state');
    wrap.dataset.component = 'empty-state';
    wrap.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Crusor Agent')), element('p', 'crusorai-empty-copy', 'Ask for a change, or start from one of these. Every file write is consent-checked: git can undo it, so it just runs; git cannot, so it asks.'));
    var grid = element('div', 'crusorai-starter-grid');
    var _loop_5 = function (prompt) {
        grid.append(button(prompt, 'crusorai-starter-prompt', function () { return host.submitPrompt(prompt); }, 'arrow-right'));
    };
    for (var _i = 0, STARTER_PROMPTS_1 = STARTER_PROMPTS; _i < STARTER_PROMPTS_1.length; _i++) {
        var prompt = STARTER_PROMPTS_1[_i];
        _loop_5(prompt);
    }
    wrap.append(grid);
    return wrap;
}
function approvalDock(model, host) {
    if (!model.approval) {
        return undefined;
    }
    var approval = model.approval;
    ensureGlobalCardKeys();
    var dock = element('section', 'crusorai-approval-dock');
    dock.dataset.component = 'approval-dock';
    dock.dataset.toolId = approval.toolId;
    // Hermes ApprovalBar (apps/desktop/.../tool/approval.tsx), ported shape for
    // shape: a compact split pill [Run ⌘⏎ | ▾] under the pending tool row, a
    // separate Reject ghost with its Esc hint, a Command disclosure revealing
    // the full call, and "Always allow" behind a confirm dialog. The ▾ menu —
    // Allow for session / Always allow… / Reject — is the piece the old flat
    // button row was missing.
    var commandText = approvalCommandText(approval.name, approval.diff);
    var diffRecord = (approval.diff && typeof approval.diff === 'object') ? approval.diff : undefined;
    var diffString = typeof approval.diff === 'string' ? approval.diff : (typeof (diffRecord === null || diffRecord === void 0 ? void 0 : diffRecord.diff) === 'string' ? diffRecord.diff : undefined);
    var diffStatistics = diffString ? diffStats(diffString) : undefined;
    var isShell = approval.name === 'run_terminal' || approval.name === 'start_terminal' || approval.name === 'terminal' || approval.name === 'execute_code' || (diffRecord === null || diffRecord === void 0 ? void 0 : diffRecord.kind) === 'shell';
    var inlineDiffCard;
    if (diffString) {
        var targetPath = (diffRecord && (diffRecord.relative_path || diffRecord.path))
            ? String(diffRecord.relative_path || diffRecord.path)
            : displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff });
        var action = typeof (diffRecord === null || diffRecord === void 0 ? void 0 : diffRecord.action) === 'string' ? diffRecord.action : 'modify';
        var actionLabel = action === 'create' ? 'Create' : action === 'delete' ? 'Delete' : action === 'copy' ? 'Copy' : 'Edit';
        var header = element('div', 'crusorai-approval-diff-header', element('span', 'crusorai-approval-action-badge', actionLabel), element('span', 'crusorai-approval-file-path', targetPath));
        if (diffStatistics) {
            var count = element('span', 'crusorai-diff-count');
            if (diffStatistics.added > 0) {
                count.append(element('span', 'is-added', "+".concat(diffStatistics.added)));
            }
            if (diffStatistics.removed > 0) {
                count.append(element('span', 'is-removed', "\u2212".concat(diffStatistics.removed)));
            }
            header.append(count);
        }
        inlineDiffCard = element('div', 'crusorai-approval-diff-preview', header, diffPreview(diffString));
    }
    var warningBox;
    if (approval.warning) {
        warningBox = element('div', 'crusorai-approval-warning', icon('shield'), element('span', undefined, approval.warning));
    }
    var shellRiskBadge;
    if (isShell) {
        var riskText = typeof (diffRecord === null || diffRecord === void 0 ? void 0 : diffRecord.risk) === 'string' ? diffRecord.risk : undefined;
        if (riskText) {
            shellRiskBadge = element('div', 'crusorai-approval-risk-badge', icon('shield'), element('span', undefined, riskText));
        }
    }
    var runButton = button('Run', 'crusorai-approval-run', function () { return host.replyToSafety(approval.toolId, true); }, 'check');
    runButton.dataset.approveOnce = '';
    hinted(runButton, 'Allow this call only.');
    var runHint = element('span', 'crusorai-approval-kbd', isMac() ? '⌘⏎' : 'Ctrl⏎');
    runButton.append(runHint);
    var menu = element('div', 'crusorai-approval-menu');
    menu.append(button('Allow for session', 'crusorai-approval-menu-item', function () {
        // The client protocol has carried `always_allow` since the start and the
        // bridge honours it, but no control ever sent it before the hermes bar:
        // every ordinary write re-prompted for the rest of the session.
        menu.classList.remove('is-open');
        host.replyToSafety(approval.toolId, true, true);
    }, 'pass-filled'), button('Always allow…', 'crusorai-approval-menu-item', function () {
        menu.classList.remove('is-open');
        overlay.classList.add('is-open');
    }, 'shield'), button('Reject', 'crusorai-approval-menu-item is-destructive', function () {
        menu.classList.remove('is-open');
        host.replyToSafety(approval.toolId, false);
    }, 'close'));
    var menuTrigger = element('button', 'crusorai-approval-more');
    menuTrigger.type = 'button';
    menuTrigger.setAttribute('aria-label', 'More options');
    menuTrigger.setAttribute('aria-expanded', 'false');
    menuTrigger.append(icon('chevron-down'));
    menuTrigger.addEventListener('click', function (event) {
        event.stopPropagation();
        var open = menu.classList.toggle('is-open');
        menuTrigger.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', function () { return menu.classList.remove('is-open'); }, { once: true });
    var pill = element('div', 'crusorai-approval-pill', runButton);
    if (true) {
        var divider = element('span', 'crusorai-approval-divider');
        divider.setAttribute('aria-hidden', 'true');
        pill.append(divider, menuTrigger);
    }
    pill.append(menu);
    var reject = hinted(button('Reject', 'crusorai-approval-reject', function () { return host.replyToSafety(approval.toolId, false); }, 'close'), 'Deny this call. The next write is asked about again.');
    reject.dataset.deny = '';
    var rejectHint = element('span', 'crusorai-approval-kbd', 'Esc');
    reject.append(rejectHint);
    var commandToggle = element('button', 'crusorai-approval-command-toggle');
    commandToggle.type = 'button';
    commandToggle.append(element('span', undefined, 'Command'), icon('chevron-down'));
    var commandPre = element('pre', 'crusorai-approval-command', commandText);
    commandToggle.setAttribute('aria-expanded', 'false');
    commandToggle.addEventListener('click', function () {
        var open = commandPre.classList.toggle('is-open');
        commandToggle.setAttribute('aria-expanded', String(open));
    });
    // "Always allow" persists for the session, so it goes through a confirm
    // step rather than firing straight from the menu (hermes' dialog rule).
    var overlay = element('div', 'crusorai-dialog-overlay');
    var dialog = element('div', 'crusorai-dialog');
    dialog.append(element('h3', undefined, 'Always allow this?'), element('p', 'crusorai-dialog-copy', "Crusor will stop asking before running ".concat(crusorAIToolPresentation(approval.name).title, " for the rest of this session. Secret paths and git-ignored files are still asked every time.")));
    // append() takes (string | Node)[] — a ternary undefined arg is a type
    // error, so the optional command preview appends conditionally.
    if (commandText) {
        dialog.append(element('pre', 'crusorai-dialog-command', commandText));
    }
    var dialogButtons = element('div', 'crusorai-dialog-actions');
    dialogButtons.append(button('Cancel', 'crusorai-button crusorai-button-secondary', function () { return overlay.classList.remove('is-open'); }), button('Always allow', 'crusorai-button crusorai-button-primary', function () {
        overlay.classList.remove('is-open');
        host.replyToSafety(approval.toolId, true, true);
    }));
    dialog.append(dialogButtons);
    overlay.append(dialog);
    overlay.addEventListener('click', function (event) { if (event.target === overlay)
        overlay.classList.remove('is-open'); });
    dock.append(element('div', 'crusorai-approval-copy', icon('shield'), element('div', undefined, element('strong', undefined, "".concat(crusorAIToolPresentation(approval.name).title, " needs approval")), element('span', undefined, displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff })))));
    if (warningBox) {
        dock.append(warningBox);
    }
    if (shellRiskBadge) {
        dock.append(shellRiskBadge);
    }
    if (inlineDiffCard) {
        dock.append(inlineDiffCard);
    }
    dock.append(element('div', 'crusorai-approval-bar', pill, reject, approval.diff ? button('Review change', 'crusorai-approval-review', function () { return host.openDiff(approval.toolId); }, 'diff') : undefined, commandText && !diffString ? commandToggle : undefined));
    if (commandText && !diffString) {
        dock.append(commandPre);
    }
    dock.append(overlay);
    return dock;
}
function isMac() {
    return typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.platform);
}
function approvalCommandText(name, diff) {
    var row = (diff && typeof diff === 'object') ? diff : {};
    for (var _i = 0, _a = ['command', 'cmd', 'path', 'file_path']; _i < _a.length; _i++) {
        var key = _a[_i];
        var value = row[key];
        if (typeof value === 'string' && value.trim()) {
            return value.trim();
        }
    }
    if (diff === undefined || diff === null) {
        return name;
    }
    try {
        return "".concat(name, " ").concat(JSON.stringify(diff)).trim();
    }
    catch (_b) {
        return name;
    }
}
// ── Hermes clarify card (the ask tool) ───────────────────────────────────────
// Port of apps/desktop/src/components/assistant-ui/clarify-tool.tsx: a widget
// card — the interactive batch form while the turn blocks, the settled Q&A
// after, and a skipped card whose choices draft a follow-up instead of
// vanishing. Draft state lives OUTSIDE the render (keyed by request id), the
// same way `openTools` survives re-renders.
var RECOMMENDED_LABEL = '(Recommended)';
var clarifyDrafts = new Map();
function clarifyDraft(requestId) {
    var draft = clarifyDrafts.get(requestId);
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
        var parsed = JSON.parse(raw);
        if (typeof parsed.error === 'string') {
            return { responses: [], timedOut: false, error: parsed.error };
        }
        var responses = [];
        var list = Array.isArray(parsed.responses) ? parsed.responses : [parsed];
        for (var _i = 0, list_1 = list; _i < list_1.length; _i++) {
            var entry = list_1[_i];
            if (entry && typeof entry === 'object') {
                responses.push(entry);
            }
        }
        return { responses: responses, timedOut: parsed.timed_out === true };
    }
    catch (_a) {
        return { responses: [], timedOut: false };
    }
}
function letterFor(index) {
    return String.fromCharCode(97 + index);
}
function keyBadge(char, selected) {
    var badge = element('span', "crusorai-key-badge".concat(selected ? ' is-selected' : ''), char);
    badge.setAttribute('aria-hidden', 'true');
    return badge;
}
/** Split "Use React (Recommended)" into [bare, recommended?] the way the
 * ChoiceLabel renders it: the suffix is presentation, tertiary-toned. */
function choiceParts(choice) {
    var trimmed = String(choice !== null && choice !== void 0 ? choice : '').trim();
    if (trimmed.toLowerCase().endsWith(RECOMMENDED_LABEL.toLowerCase())) {
        return { bare: trimmed.slice(0, -RECOMMENDED_LABEL.length).trim(), recommended: true };
    }
    return { bare: trimmed, recommended: false };
}
function clarifyChoiceRow(qid, index, choice, multi, draft, requestId, onDirty) {
    var _a, _b;
    var _c = choiceParts(choice), bare = _c.bare, recommended = _c.recommended;
    var picked = (_b = (_a = draft.selected.get(qid)) === null || _a === void 0 ? void 0 : _a.has(bare)) !== null && _b !== void 0 ? _b : false;
    var row = element('button', "crusorai-clarify-choice".concat(picked ? ' is-selected' : ''));
    row.type = 'button';
    row.dataset.choiceIndex = String(index);
    row.dataset.qid = qid;
    row.dataset.choice = bare;
    row.setAttribute('aria-pressed', String(picked));
    row.append(keyBadge(letterFor(index), picked));
    var label = element('span', 'crusorai-clarify-choice-label');
    label.append(document.createTextNode(bare));
    if (recommended) {
        label.append(element('span', 'crusorai-clarify-recommended', " ".concat(RECOMMENDED_LABEL)));
    }
    row.append(label);
    row.addEventListener('click', function () {
        var _a, _b;
        var set = (_a = draft.selected.get(qid)) !== null && _a !== void 0 ? _a : new Set();
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
        var form = row.closest('.crusorai-clarify-form');
        for (var _i = 0, _c = ((_b = form === null || form === void 0 ? void 0 : form.querySelectorAll("[data-qid=\"".concat(qid, "\"].crusorai-clarify-choice"))) !== null && _b !== void 0 ? _b : []); _i < _c.length; _i++) {
            var other = _c[_i];
            var isThis = other === row;
            other.classList.toggle('is-selected', isThis);
            other.setAttribute('aria-pressed', String(isThis));
        }
        var textarea = form === null || form === void 0 ? void 0 : form.querySelector("textarea[data-qid=\"".concat(qid, "\"]"));
        if (textarea) {
            textarea.value = '';
        }
        onDirty();
    });
    return row;
}
function clarifyCard(tool, host, _openTools, pending) {
    var _a, _b, _c, _d, _e;
    ensureGlobalCardKeys();
    // Settled: the tool result carries the batch JSON — Q/A card, hermes
    // ClarifyToolSettled. A skipped card keeps its choices clickable; a pick
    // drafts a quoted follow-up into the composer (Enter sends, a running turn
    // queues it like any other prompt).
    if (tool.result !== undefined) {
        var _f = parseClarifyResult(tool.result), responses = _f.responses, timedOut = _f.timedOut, error = _f.error;
        var card = element('div', 'crusorai-clarify-card');
        card.dataset.component = 'clarify-settled';
        var skipped = !error && responses.length > 0 && responses.every(function (r) {
            var value = r.user_response;
            return value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
        });
        var _loop_6 = function (response) {
            card.append(element('div', 'crusorai-clarify-q', icon('question'), element('span', undefined, (_a = response.question) !== null && _a !== void 0 ? _a : '')));
            var answer = response.user_response;
            var answerText = error
                ? error
                : skipped ? 'Skipped'
                    : Array.isArray(answer) ? answer.join(', ')
                        : (typeof answer === 'string' ? answer : '').trim();
            if (answerText) {
                card.append(element('div', "crusorai-clarify-a".concat(error ? ' is-error' : '').concat(skipped ? ' is-skipped' : ''), element('span', 'crusorai-clarify-a-badge', 'A'), element('span', undefined, answerText)));
            }
            if (timedOut || skipped) {
                var choices = (_b = response.choices_offered) !== null && _b !== void 0 ? _b : [];
                if (choices.length) {
                    var late_1 = element('div', 'crusorai-clarify-late');
                    choices.forEach(function (choice, index) {
                        var bare = choiceParts(choice).bare;
                        var row = element('button', 'crusorai-clarify-choice');
                        row.type = 'button';
                        row.append(keyBadge(letterFor(index), false), element('span', 'crusorai-clarify-choice-label', bare));
                        row.addEventListener('click', function () {
                            var _a;
                            // Hermes late-answer: a pick can't resolve the dead
                            // request — it drafts a quoted follow-up instead.
                            host.setDraft("Re: \"".concat((_a = response.question) !== null && _a !== void 0 ? _a : 'your question', "\" \u2014 ").concat(bare));
                        });
                        late_1.append(row);
                    });
                    late_1.append(element('p', 'crusorai-clarify-late-hint', 'The turn moved on — pick one to draft a follow-up instead.'));
                    card.append(late_1);
                }
            }
        };
        for (var _i = 0, responses_1 = responses; _i < responses_1.length; _i++) {
            var response = responses_1[_i];
            _loop_6(response);
        }
        return card;
    }
    // Pending: the interactive batch form (hermes ClarifyToolSinglePending /
    // ClarifyToolBatchPending). Args alone can't drive it — the request frame
    // carries the qids the reply needs.
    var draft = clarifyDraft(pending.requestId);
    var form = element('div', 'crusorai-clarify-card crusorai-clarify-form');
    form.dataset.component = 'clarify-inline';
    form.dataset.live = '1';
    form.dataset.requestId = pending.requestId;
    var collectAnswers = function () {
        var _a, _b;
        var answers = {};
        for (var _i = 0, _c = pending.questions; _i < _c.length; _i++) {
            var question = _c[_i];
            var other = (_a = draft.other.get(question.qid)) !== null && _a !== void 0 ? _a : '';
            if (other.trim()) {
                answers[question.qid] = other.trim();
                continue;
            }
            var picked = Array.from((_b = draft.selected.get(question.qid)) !== null && _b !== void 0 ? _b : []);
            if (picked.length === 1) {
                answers[question.qid] = picked[0];
            }
            else if (picked.length > 1) {
                answers[question.qid] = picked;
            }
        }
        return answers;
    };
    var submitButton = element('button', 'crusorai-button crusorai-button-primary crusorai-clarify-submit');
    submitButton.type = 'button';
    submitButton.dataset.clarifySubmit = '';
    submitButton.append('Continue', element('span', 'crusorai-approval-kbd', '⏎'));
    submitButton.addEventListener('click', function () {
        form.dataset.live = '0';
        host.replyToClarify(pending.requestId, collectAnswers(), false);
    });
    var skipButton = element('button', 'crusorai-button crusorai-button-secondary crusorai-clarify-skip');
    skipButton.type = 'button';
    skipButton.textContent = 'Skip';
    skipButton.addEventListener('click', function () {
        form.dataset.live = '0';
        // Hermes skip: the batch resolves EMPTY — a deliberate skip the model
        // reads as "" answers, distinct from a walk-away timeout.
        host.replyToClarify(pending.requestId, {}, false);
    });
    var _loop_7 = function (question) {
        var multi = question.multi_select === true;
        var block = element('div', 'crusorai-clarify-block');
        block.append(element('div', 'crusorai-clarify-q', icon('question'), element('span', undefined, question.question)));
        var choices = (_c = question.choices) !== null && _c !== void 0 ? _c : [];
        if (choices.length) {
            var group_1 = element('div', 'crusorai-clarify-choices');
            group_1.setAttribute('role', 'group');
            choices.forEach(function (choice, index) {
                group_1.append(clarifyChoiceRow(question.qid, index, choice, multi, draft, pending.requestId, function () { return refreshSubmit(); }));
            });
            // The auto-appended "Other (type your answer)" row — hermes: the UI
            // always appends it; typing is its own answer and clears picks.
            var otherRow = element('label', 'crusorai-clarify-other');
            otherRow.dataset.choiceIndex = String(choices.length);
            otherRow.dataset.qid = question.qid;
            otherRow.append(keyBadge(letterFor(choices.length), false));
            var textarea_1 = element('textarea', 'crusorai-clarify-other-input');
            textarea_1.rows = 1;
            textarea_1.placeholder = 'Other (type your answer)';
            textarea_1.dataset.qid = question.qid;
            textarea_1.value = (_d = draft.other.get(question.qid)) !== null && _d !== void 0 ? _d : '';
            textarea_1.addEventListener('input', function () {
                draft.other.set(question.qid, textarea_1.value);
                if (textarea_1.value.trim()) {
                    draft.selected.set(question.qid, new Set());
                    for (var _i = 0, _a = form.querySelectorAll("[data-qid=\"".concat(question.qid, "\"].crusorai-clarify-choice")); _i < _a.length; _i++) {
                        var row = _a[_i];
                        row.classList.remove('is-selected');
                        row.setAttribute('aria-pressed', 'false');
                    }
                }
                refreshSubmit();
            });
            otherRow.append(textarea_1);
            group_1.append(otherRow);
            block.append(group_1);
        }
        else {
            var textarea_2 = element('textarea', 'crusorai-clarify-other-input crusorai-clarify-open');
            textarea_2.rows = 2;
            textarea_2.placeholder = 'Type your answer…';
            textarea_2.dataset.qid = question.qid;
            textarea_2.value = (_e = draft.other.get(question.qid)) !== null && _e !== void 0 ? _e : '';
            textarea_2.addEventListener('input', function () { draft.other.set(question.qid, textarea_2.value); refreshSubmit(); });
            block.append(textarea_2);
        }
        form.append(block);
    };
    for (var _g = 0, _h = pending.questions; _g < _h.length; _g++) {
        var question = _h[_g];
        _loop_7(question);
    }
    function refreshSubmit() {
        var answers = collectAnswers();
        var hasAnswer = Object.keys(answers).length > 0;
        submitButton.disabled = !hasAnswer;
    }
    refreshSubmit();
    var actions = element('div', 'crusorai-clarify-actions', skipButton, submitButton);
    form.append(actions);
    return form;
}
// ── Hermes todo panel (the task tool) ────────────────────────────────────────
// Port of the composer status stack's todo rows (status-row.tsx): checkbox
// glyphs, not spinner-and-dot — a dashed ring while pending, codicons once the
// item resolves, a live spinner only on the in_progress item; depth-indented
// subtasks; an X/Y count. Rendered ABOVE the composer, like upstream.
function todoStack(model) {
    var todos = model.todos;
    if (!todos.length) {
        return undefined;
    } // hermes: no active list, no panel
    var counted = todos.filter(function (t) { return t.status !== 'cancelled'; });
    var done = counted.filter(function (t) { return t.status === 'completed'; }).length;
    var stack = element('section', 'crusorai-todo-stack');
    stack.dataset.component = 'todo-stack';
    stack.append(element('div', 'crusorai-section-heading', icon('list-ordered'), element('span', undefined, 'Tasks'), element('span', 'crusorai-section-count', "".concat(done, "/").concat(counted.length))));
    var list = element('div', 'crusorai-todo-list');
    for (var _i = 0, todos_1 = todos; _i < todos_1.length; _i++) {
        var todo = todos_1[_i];
        var depth = todoDepth(todo, todos);
        var glyph = todoGlyph(todo.status);
        var row = element('div', "crusorai-todo-row is-".concat(todo.status));
        if (depth) {
            row.style.paddingLeft = "".concat(Math.min(depth, 4) * 0.8, "rem");
        }
        row.append(glyph, element('span', 'crusorai-todo-content', todo.content));
        list.append(row);
    }
    stack.append(list);
    return stack;
}
function todoDepth(todo, todos) {
    var depth = 0;
    var current = todo;
    var byId = new Map(todos.map(function (t) { return [t.id, t]; }));
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
    var ring = element('span', 'crusorai-todo-ring');
    ring.setAttribute('aria-hidden', 'true');
    return ring;
}
// ── Global card keys ─────────────────────────────────────────────────────────
// One capture-phase listener, installed once (hermes' window keydown in
// ClarifyToolSinglePending + ApprovalBar): ⌘/Ctrl+Enter runs the approval,
// Esc rejects it; letters/numbers/arrows/Enter drive the live clarify card.
// The DOM is the state — a re-render between keystrokes cannot desync us.
var globalCardKeysInstalled = false;
function ensureGlobalCardKeys() {
    if (globalCardKeysInstalled || typeof document === 'undefined') {
        return;
    }
    globalCardKeysInstalled = true;
    document.addEventListener('keydown', function (event) {
        var _a, _b, _c, _d, _e, _f;
        var dock = document.querySelector('[data-component="approval-dock"][data-tool-id]');
        if (dock) {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault();
                (_a = dock.querySelector('[data-approve-once]')) === null || _a === void 0 ? void 0 : _a.click();
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                (_b = dock.querySelector('[data-deny]')) === null || _b === void 0 ? void 0 : _b.click();
                return;
            }
        }
        var form = document.querySelector('.crusorai-clarify-form[data-live="1"]');
        // Esc pulls the Stop button — the composer hint advertises it, and a
        // stop is one pull with nothing in the way. A live clarify question
        // keeps its own Escape (deny/close), and the approval dock above
        // already consumed Escape for deny before we get here.
        if (event.key === 'Escape' && !event.defaultPrevented && !event.metaKey && !event.ctrlKey && !event.altKey && !form) {
            var stop = document.querySelector('.crusorai-send-stop:not([disabled])');
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
        var active = document.activeElement;
        if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT' || active.isContentEditable)) {
            return;
        }
        var rows = Array.from(form.querySelectorAll('[data-choice-index]'));
        if (!rows.length) {
            return;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            var delta = event.key === 'ArrowDown' ? 1 : -1;
            var current = rows.findIndex(function (row) { return row.classList.contains('is-active'); });
            var next_1 = Math.max(0, Math.min(rows.length - 1, (current === -1 ? 0 : current + delta)));
            rows.forEach(function (row, index) { return row.classList.toggle('is-active', index === next_1); });
            return;
        }
        if (/^[1-9]$/.test(event.key)) {
            var row = rows[Number(event.key) - 1];
            if (row) {
                event.preventDefault();
                row.classList.add('is-active');
                (_d = (_c = row).click) === null || _d === void 0 ? void 0 : _d.call(_c);
            }
            return;
        }
        var key = event.key.toLowerCase();
        if (key.length === 1 && key >= 'a' && key <= 'z') {
            var row = rows[key.charCodeAt(0) - 97];
            if (row) {
                event.preventDefault();
                row.classList.add('is-active');
                if (row.click) {
                    row.click();
                }
                else {
                    (_e = row.querySelector('textarea')) === null || _e === void 0 ? void 0 : _e.focus();
                }
            }
            return;
        }
        if (event.key === 'Enter') {
            var activeRow = rows.find(function (row) { return row.classList.contains('is-active'); });
            if (activeRow) {
                event.preventDefault();
                if (activeRow.click) {
                    activeRow.click();
                }
                else {
                    (_f = activeRow.querySelector('textarea')) === null || _f === void 0 ? void 0 : _f.focus();
                }
                return;
            }
            var submit = form.querySelector('[data-clarify-submit]');
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
    var added = 0;
    var removed = 0;
    for (var _i = 0, _a = diff.split('\n'); _i < _a.length; _i++) {
        var line = _a[_i];
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
    return added || removed ? { added: added, removed: removed } : undefined;
}
/** Lines are clamped for *paint*, never for correctness -- the count says what is hidden. */
var DIFF_PREVIEW_LINE_LIMIT = 40;
// hermes diff-lines.tsx wireframe, ported: file-headers + `@@` hunk noise and
// the +/- gutter are DROPPED -- changes read by tint + a 2px gutter accent,
// rows flush to the card edges, the box scrolls like a code block.
function diffPreview(diff) {
    var wrap = element('div', 'crusorai-diff-body');
    var parsed = parseDiff(diff || '');
    var shown = parsed.slice(0, DIFF_PREVIEW_LINE_LIMIT);
    for (var _i = 0, shown_1 = shown; _i < shown_1.length; _i++) {
        var line = shown_1[_i];
        var row = element('span', "crusorai-diff-row is-".concat(line.kind), line.text.length ? line.text : ' ');
        if (line.newNo !== undefined) {
            row.dataset.newNo = String(line.newNo);
        }
        if (line.oldNo !== undefined) {
            row.dataset.oldNo = String(line.oldNo);
        }
        wrap.append(row);
    }
    if (parsed.length > DIFF_PREVIEW_LINE_LIMIT) {
        wrap.append(element('div', 'crusorai-diff-row is-truncated', "\u2026 ".concat(parsed.length - DIFF_PREVIEW_LINE_LIMIT, " more line(s) \u2014 'Open native diff' shows all of it")));
    }
    return wrap;
}
// hermes terminal-output.tsx + lib/ansi.ts: bounded tail (paint, not
// correctness) with SGR-colored segments; plain text when there is no ANSI.
var TERMINAL_PAINT_LINE_LIMIT = 400;
function terminalOutputContent(output, running) {
    var pre = element('pre', 'crusorai-terminal-output');
    var text = output || (running ? 'Waiting for output...' : 'No captured output');
    var windowed = windowedTailLines(text, TERMINAL_PAINT_LINE_LIMIT);
    if (windowed.hidden > 0) {
        pre.append(element('div', 'crusorai-terminal-earlier', "\u2026 ".concat(windowed.hidden, " earlier line(s) \u2014 full history stays in the run log")));
    }
    var body = windowed.lines.join('\n');
    if (!hasAnsiCodes(body)) {
        pre.append(document.createTextNode(body));
        return pre;
    }
    var line;
    for (var _i = 0, _a = parseAnsi(body); _i < _a.length; _i++) {
        var segment = _a[_i];
        if (!line) {
            line = element('span', 'crusorai-ansi-line');
            pre.append(line);
        }
        var span = element('span', segment.fg ? "crusorai-ansi-".concat(segment.fg) : undefined, segment.text);
        if (segment.bold) {
            span.classList.add('is-bold');
        }
        // hermes ansi segments carry embedded \n — split into rows
        var parts = segment.text.split('\n');
        for (var i = 0; i < parts.length; i += 1) {
            if (i > 0) {
                line = element('span', 'crusorai-ansi-line');
                pre.append(line);
            }
            if (parts[i]) {
                line.append(element('span', segment.fg ? "crusorai-ansi-".concat(segment.fg) : undefined, parts[i]));
            }
        }
    }
    return pre;
}
// hermes changed-files-card.tsx: the turn-closing "N files changed" rollup —
// one row per LANDED file edit, +/- summed, click opens the file. Wears the
// shared widget chrome so it reads as the transcript's other inline widgets.
function changedFilesCard(model, host) {
    var files = deriveChangedFiles(model.tools);
    if (!files.length) {
        return undefined;
    }
    var card = element('div', 'crusorai-changed-files');
    card.dataset.component = 'changed-files';
    card.append(element('div', 'crusorai-changed-files-head', element('span', undefined, "".concat(files.length, " file").concat(files.length === 1 ? '' : 's', " changed"))));
    var rows = element('div', 'crusorai-changed-files-rows');
    var _loop_8 = function (file) {
        var row = element('div', 'crusorai-changed-file-row');
        row.append(icon('file'), element('span', 'crusorai-changed-file-name', file.name), element('span', 'crusorai-diff-count', element('span', 'is-added', "+".concat(file.added)), element('span', 'is-removed', "\u2212".concat(file.removed))));
        row.title = file.path;
        row.classList.add('is-activatable');
        row.addEventListener('click', function () { return host.revealFile(file.path); });
        rows.append(row);
    };
    for (var _i = 0, files_1 = files; _i < files_1.length; _i++) {
        var file = files_1[_i];
        _loop_8(file);
    }
    card.append(rows);
    return card;
}
var executionModes = [
    { id: 'agent', label: 'Agent', description: 'Build, change, and verify', icon: 'infinity' },
    { id: 'plan', label: 'Plan', description: 'Design before execution', icon: 'list-ordered' },
    { id: 'debug', label: 'Debug', description: 'Diagnose, fix, and retest', icon: 'debug-alt' },
    { id: 'ask', label: 'Ask', description: 'Explain without using tools', icon: 'comment' },
];
function modePicker(model, host) {
    var _a;
    var selected = (_a = executionModes.find(function (mode) { return mode.id === model.mode; })) !== null && _a !== void 0 ? _a : executionModes[0];
    var details = element('details', 'crusorai-mode-picker');
    var summary = element('summary', 'crusorai-mode-summary', icon(selected.icon), element('span', undefined, selected.label), icon('chevron-down'));
    summary.setAttribute('aria-label', "Execution mode: ".concat(selected.label));
    if (model.running) {
        summary.setAttribute('aria-disabled', 'true');
        summary.addEventListener('click', function (event) { return event.preventDefault(); });
    }
    var menu = element('div', 'crusorai-mode-menu');
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Execution mode');
    var _loop_9 = function (mode) {
        var item = element('button', mode.id === selected.id ? 'crusorai-mode-option is-selected' : 'crusorai-mode-option', icon(mode.icon), element('span', 'crusorai-mode-option-copy', element('strong', undefined, mode.label), element('small', undefined, mode.description)), mode.id === selected.id ? icon('check') : undefined);
        item.type = 'button';
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(mode.id === selected.id));
        item.addEventListener('click', function () {
            details.open = false;
            host.setMode(mode.id);
        });
        menu.append(item);
    };
    for (var _i = 0, executionModes_1 = executionModes; _i < executionModes_1.length; _i++) {
        var mode = executionModes_1[_i];
        _loop_9(mode);
    }
    details.append(summary, menu);
    return details;
}
// hermes desktop lib/reasoning-effort.ts + composer model-pill: the Think
// scale beside the execution mode. '' (no pick yet) means "inherit the
// engine default" — the summary shows that honestly instead of guessing.
var thinkOptions = [
    { id: 'low', description: 'Quick replies, light reasoning' },
    { id: 'medium', description: 'Balanced default' },
    { id: 'high', description: 'Deep reasoning, slower turns' },
    { id: 'none', description: 'Disable extended thinking' },
];
function thinkPicker(model, host) {
    var _a;
    var details = element('details', 'crusorai-mode-picker crusorai-think-picker');
    var current = (_a = model.reasoningEffort) !== null && _a !== void 0 ? _a : '';
    var summary = element('summary', 'crusorai-mode-summary', element('span', undefined, current ? reasoningEffortLabel(current) : 'Think'), icon('chevron-down'));
    summary.setAttribute('aria-label', "Thinking effort: ".concat(current ? reasoningEffortLabel(current) : 'engine default'));
    if (model.running) {
        summary.setAttribute('aria-disabled', 'true');
        summary.addEventListener('click', function (event) { return event.preventDefault(); });
    }
    var menu = element('div', 'crusorai-mode-menu');
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Thinking effort');
    var _loop_10 = function (option) {
        var selected = option.id === current;
        var item = element('button', selected ? 'crusorai-mode-option is-selected' : 'crusorai-mode-option', icon(option.id === 'none' ? 'circle-slash' : 'lightbulb'), element('span', 'crusorai-mode-option-copy', element('strong', undefined, reasoningEffortLabel(option.id)), element('small', undefined, option.description)), selected ? icon('check') : undefined);
        item.type = 'button';
        item.setAttribute('role', 'menuitemradio');
        item.setAttribute('aria-checked', String(selected));
        item.addEventListener('click', function () {
            details.open = false;
            host.setReasoningEffort(option.id);
        });
        menu.append(item);
    };
    for (var _i = 0, thinkOptions_1 = thinkOptions; _i < thinkOptions_1.length; _i++) {
        var option = thinkOptions_1[_i];
        _loop_10(option);
    }
    details.append(summary, menu);
    return details;
}
function composer(model, host, manager) {
    var input = element('textarea', 'crusorai-composer-input');
    input.rows = manager ? 2 : 3;
    input.placeholder = model.isChild ? 'Sub-agent session — prompt disabled. Use Back to Parent.' : manager ? 'Steer this agent or add context...' : 'Plan, @ for context, / for commands';
    input.value = model.draft;
    input.addEventListener('input', function () { return host.setDraft(input.value); });
    var inputBlocked = model.noWorkspace || model.workspaceSelectionRequired || !!model.isChild;
    if (inputBlocked) {
        input.disabled = true;
    }
    var submit = function () {
        var value = input.value.trim();
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
    input.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
        }
    });
    var running = model.running;
    var send = element('button', running ? 'crusorai-send-button crusorai-send-stop' : 'crusorai-send-button');
    send.type = 'button';
    send.setAttribute('aria-label', running ? 'Stop' : 'Send');
    send.append(icon(running ? 'debug-pause' : 'arrow-up'));
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
    var plusMenu = (function () {
        var allEntries = [
            { label: 'Marketplace…', glyph: 'search', desc: 'browse & install skills', tab: 'marketplace', run: openHubDialog },
            { label: 'Connectors…', glyph: 'plug', desc: 'MCP, plugins', tab: 'connectors', run: openHubDialog },
            { label: 'My Skills', glyph: 'checklist', desc: 'installed skills, on/off', tab: 'myskills', run: openHubDialog },
            { label: 'One-Shot Task…', glyph: 'zap', desc: 'quick jobs to clipboard', tab: 'oneshot', run: openHubDialog },
        ];
        var entries = allEntries.filter(function (entry) { return typeof host.skillsHubOp === 'function'; });
        if (entries.length === 0) {
            return undefined;
        }
        var details = element('details', 'crusorai-mode-picker crusorai-add-picker');
        var summary = element('summary', 'crusorai-mode-summary', icon('add'), icon('chevron-down'));
        summary.setAttribute('aria-label', 'Add — marketplace, connectors, skills, one-shot');
        summary.title = 'Marketplace, connectors, skills, one-shot';
        var menu = element('div', 'crusorai-mode-menu');
        menu.setAttribute('role', 'menu');
        menu.setAttribute('aria-label', 'Add');
        var _loop_11 = function (entry) {
            var item = element('button', 'crusorai-mode-option', icon(entry.glyph), element('span', 'crusorai-mode-option-copy', element('strong', undefined, entry.label), element('small', undefined, entry.desc)));
            item.type = 'button';
            item.setAttribute('role', 'menuitem');
            item.addEventListener('click', function () {
                details.open = false;
                entry.run(host, details);
            });
            menu.append(item);
        };
        for (var _i = 0, entries_1 = entries; _i < entries_1.length; _i++) {
            var entry = entries_1[_i];
            _loop_11(entry);
        }
        details.append(summary, menu);
        summary.addEventListener('click', function () {
            if (!details.open) {
                return;
            }
            setTimeout(function () {
                var away = function (event) {
                    if (!details.contains(event.target)) {
                        details.open = false;
                    }
                };
                document.addEventListener('click', away, { capture: true, once: true });
            }, 0);
        });
        return details;
    })();
    var toolbar = element('div', 'crusorai-composer-toolbar', plusMenu, modePicker(model, host), thinkPicker(model, host), element('span', 'crusorai-composer-left'), send);
    var hint = element('div', 'crusorai-composer-hint', model.noWorkspace
        ? element('span', undefined, model.noWorkspaceHint)
        : model.workspaceSelectionRequired
            ? element('span', undefined, 'Select a workspace folder to start a Crusor session.')
            : element('span', undefined, model.running ? 'Esc to interrupt' : 'Enter to send'), element('span', undefined, model.noWorkspace ? '' : 'Shift+Enter for new line'));
    if (model.noWorkspace) {
        hint.append(button('Open Folder', 'crusorai-link-button', host.openFolder, 'folder'));
    }
    return element('footer', 'crusorai-composer', element('div', 'crusorai-composer-box', input, toolbar), hint);
}
function agentColumn(model, host, openTools, activity, planOpen, setPlanOpen) {
    var nodes = [];
    var plan = planStrip(model, planOpen, setPlanOpen);
    if (plan) {
        nodes.push(plan);
    }
    // An engine that is not ready is a FACT the panel must paint — the empty
    // state's starter grid under a dead engine reads as a send button that
    // does nothing (field 2026-09-05). Same quiet row the activity ticker
    // uses; the chip lives in the Manager, this names the state HERE.
    if (model.engineState !== 'ready' && !model.engineFault) {
        var row = element('div', 'crusorai-context-status-row is-info');
        row.append(element('span', 'crusorai-activity-dot'));
        row.append(element('span', undefined, model.engineState === 'starting'
            ? 'Crusor engine is starting — prompts send the moment it is ready.'
            : "Crusor engine: ".concat(model.engineState, ".")));
        nodes.push(row);
    }
    // An empty transcript is a designed surface, not a blank div -- the same rule the ported
    // webview follows (`hermes-ui/components/empty-state.tsx`). Exactly one of the two is
    // mounted, so a first-run view never shows an empty lane under a grid of starters.
    var empty = emptyState(model, host);
    nodes.push(empty !== null && empty !== void 0 ? empty : transcript(model, host, openTools, activity.thoughtSeconds(model)));
    var working = activity.row(model);
    if (working) {
        nodes.push(working);
    }
    var approval = approvalDock(model, host);
    if (approval) {
        nodes.push(approval);
    }
    // Hermes: the todo panel lives between the transcript and the composer
    // (the composer status stack) — the list rides ABOVE the input, never
    // buried in transcript history.
    var todos = todoStack(model);
    if (todos) {
        nodes.push(todos);
    }
    return nodes;
}
function renderAgent(root, model, host, openTools, planOpen, setPlanOpen, activity) {
    var shell = element('div', 'crusorai-agent-shell');
    var header = element('div', 'crusorai-agent-header', element('span', 'crusorai-agent-header-title', 'Crusor Agent'), button('Manager', 'crusorai-agent-manager-button', function () { return host.openManager(); }, 'organization'));
    // Field run 2026-09-09 (owner: "Ur claim failed"): the STALE chip lived
    // only in the Manager titlebar, so an Agent-pane session ran a pre-
    // fef8cdb2/74d146bd workbench against a current engine — every card-
    // format fix invisible — with NO warning where the user was looking.
    // The chip rides the Agent header too (next to the Manager button).
    header.append(engineStatus(model));
    shell.append(header);
    shell.append.apply(shell, agentColumn(model, host, openTools, activity, planOpen, setPlanOpen));
    shell.append(composer(model, host, false));
    root.append(shell);
}
function inspector(model) {
    var _a, _b, _c, _d;
    var pane = element('aside', 'crusorai-manager-inspector');
    pane.append(element('header', 'crusorai-manager-pane-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'LIVE EVIDENCE'), element('h2', undefined, 'Run inspector'))));
    var plan = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Plan'), element('strong', undefined, "".concat(model.plan.length, " steps"))));
    var list = element('ol', 'crusorai-plan-list');
    for (var _i = 0, _e = model.plan; _i < _e.length; _i++) {
        var step = _e[_i];
        list.append(element('li', "is-".concat(step.status), planStepGlyph(step.status), element('span', undefined, step.text)));
    }
    if (!model.plan.length) {
        list.append(element('li', 'is-muted', icon('circle-outline'), element('span', undefined, 'Plan appears when the run starts')));
    }
    plan.append(list);
    var evidence = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Verification'), element('strong', undefined, (_a = model.verification) !== null && _a !== void 0 ? _a : 'Not started')), element('div', 'crusorai-evidence-row', icon(model.verification === 'passed' ? 'pass-filled' : 'circle-outline'), element('span', undefined, model.verification ? "Runtime reported ".concat(model.verification) : 'No evidence receipt yet')));
    var capabilities = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Workbench capabilities'), element('strong', undefined, "".concat(model.capabilitySummary.available, "/").concat(model.capabilitySummary.total))), element('div', 'crusorai-evidence-row', icon('plug'), element('span', undefined, "".concat(model.capabilitySummary.available, " available \u00B7 ").concat(model.capabilitySummary.blocked, " blocked"))));
    var usage = element('section', 'crusorai-inspector-section crusorai-usage', element('div', 'crusorai-inspector-title', element('span', undefined, 'Usage'), element('strong', undefined, model.telemetry.cost === undefined ? '\u2014' : "$".concat(model.telemetry.cost.toFixed(4)))), element('div', 'crusorai-usage-grid', element('span', undefined, 'Input'), element('strong', undefined, String((_b = model.telemetry.input) !== null && _b !== void 0 ? _b : 0)), element('span', undefined, 'Cache'), element('strong', undefined, String((_c = model.telemetry.cache) !== null && _c !== void 0 ? _c : 0)), element('span', undefined, 'Output'), element('strong', undefined, String((_d = model.telemetry.output) !== null && _d !== void 0 ? _d : 0))));
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
    var group = element('div', 'crusorai-workspace-group');
    group.append(element('div', 'crusorai-workspace-title', icon('chevron-down'), icon('folder'), element('strong', undefined, model.workspaceLabel)));
    var rows = model.sessions;
    if (!rows || !rows.length) {
        group.append(element('div', 'crusorai-session-row is-empty', element('span', 'crusorai-status-dot is-idle'), element('div', undefined, element('strong', undefined, 'No session yet'), element('span', undefined, 'A run appears here the moment the engine names one'))));
        return group;
    }
    var narration = summarizeToolRun(model.tools, model.running, function (tool) { var _a; return (_a = compactTarget(displayTarget(tool))) !== null && _a !== void 0 ? _a : tool.name; });
    var _loop_12 = function (row) {
        var dot = row.statusName === 'inProgress' ? 'running'
            : row.statusName === 'needsInput' ? 'waiting'
                : row.statusName === 'failed' ? 'failed' : 'ready';
        var detail = row.isActive && narration ? narration
            : row.statusName === 'needsInput' ? 'Waiting for approval'
                : row.statusName === 'failed' ? 'Run failed'
                    : row.changes ? "".concat(row.changes.files, " file(s) +").concat(row.changes.insertions, " \u2212").concat(row.changes.deletions)
                        : row.statusName === 'completed' ? 'Finished' : row.description;
        var state = row.elapsedLabel || (row.isActive ? (model.running ? 'Working…' : 'Ready') : '');
        var classes = ['crusorai-session-row'];
        if (row.isActive) {
            classes.push('is-active');
        }
        if (row.statusName === 'needsInput') {
            classes.push('is-needs-input');
        }
        if (row.needsAttention) {
            classes.push('is-attention');
        }
        var button_1 = element('button', classes.join(' '), element('span', "crusorai-status-dot is-".concat(dot)), element('div', undefined, element('strong', undefined, row.label), element('span', 'crusorai-session-detail', detail)), element('span', 'crusorai-session-state', state));
        // Every row opens its session in place (navigateToSession rebinds the surface and
        // hydrates the transcript); the active row is already open so it stays inert.
        button_1.type = 'button';
        if (!row.isActive && host.navigateToSession) {
            var target_1 = crusorSessionIdFromUri(row.resource);
            button_1.title = 'Open this session in this panel';
            if (target_1) {
                button_1.addEventListener('click', function () { return host.navigateToSession(target_1); });
            }
        }
        else {
            button_1.title = 'Open in this panel';
        }
        group.append(button_1);
    };
    for (var _i = 0, rows_3 = rows; _i < rows_3.length; _i++) {
        var row = rows_3[_i];
        _loop_12(row);
    }
    return group;
}
var skillOriginLabel = { hub: 'hub', bundled: 'bundled', user: 'yours', agent: 'agent-learned' };
function skillsErrorRow(message) {
    return element('div', 'crusorai-error-row', icon('warning'), element('span', undefined, message));
}
function skillRow(row, updateAvailable, ui) {
    var _a, _b, _c, _d;
    var busy = ((_a = ui.action) === null || _a === void 0 ? void 0 : _a.name) === row.name;
    var node = element('div', "crusorai-skill-row".concat(row.enabled ? '' : ' is-disabled'));
    var title = element('div', 'crusorai-skill-title', element('span', 'crusorai-skill-name', row.name), element('span', "crusorai-skill-badge".concat(row.enabled ? ' is-on' : ''), row.enabled ? 'enabled' : 'disabled'), element('span', 'crusorai-skill-badge', (_b = skillOriginLabel[row.origin]) !== null && _b !== void 0 ? _b : row.origin));
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
    if ((_c = row.triggers) === null || _c === void 0 ? void 0 : _c.length) {
        node.append(element('div', 'crusorai-skill-triggers', "routes on: ".concat(row.triggers.join(', '))));
    }
    var actions = element('div', 'crusorai-skill-actions');
    var toggle = button(row.enabled ? 'Disable' : 'Enable', 'crusorai-skill-action', function () { return ui.runAction('toggle', row.name, { enabled: !row.enabled }); }, row.enabled ? 'circle-slash' : 'check');
    toggle.disabled = busy;
    actions.append(toggle);
    if (updateAvailable) {
        var update = button('Update', 'crusorai-skill-action', function () { return ui.runAction('update', row.name); }, 'arrow-up');
        update.disabled = busy;
        actions.append(update);
    }
    if (row.origin === 'hub') {
        var confirming = ui.confirmRemove === row.name;
        var remove = button(confirming ? 'Confirm remove' : 'Remove', confirming ? 'crusorai-skill-action is-confirm' : 'crusorai-skill-action', function () { return ui.confirmRemoveFor(row.name); }, 'trash');
        remove.disabled = busy;
        actions.append(remove);
    }
    actions.append(element('span', 'crusorai-skill-uses', "used ".concat(row.use_count, "\u00D7")));
    if (busy) {
        actions.append(element('span', 'crusorai-skill-busy', "".concat((_d = ui.action) === null || _d === void 0 ? void 0 : _d.op, "\u2026")));
    }
    node.append(actions);
    return node;
}
function skillsPanel(ui, host) {
    var pane = element('div', 'crusorai-skills-pane');
    var rows = ui.skills.rows;
    var enabledCount = rows.filter(function (row) { return row.enabled; }).length;
    var head = element('div', 'crusorai-skills-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'SKILLS'), element('h2', undefined, 'Installed skills')), element('span', 'crusorai-skills-summary', ui.skills.loaded && rows.length > 0 ? "".concat(enabledCount, " enabled / ").concat(rows.length, " installed") : ''));
    var refresh = button(ui.skills.loading ? 'Refreshing…' : 'Refresh', 'crusorai-skills-refresh', function () { return ui.refresh(); }, 'refresh');
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
        var retry = button('Retry', 'crusorai-skills-refresh', function () { return ui.refresh(); });
        pane.append(retry);
    }
    else if (rows.length === 0) {
        pane.append(element('div', 'crusorai-skills-empty', 'No skills installed yet.'));
        var browse_1 = button('Browse the marketplace', 'crusorai-skills-refresh', function () { return openHubDialog(host, browse_1, 'marketplace'); }, 'package');
        pane.append(browse_1);
    }
    else {
        if (ui.skills.hubError) {
            pane.append(skillsErrorRow("Update badges unavailable: ".concat(ui.skills.hubError)));
        }
        var _loop_13 = function (row) {
            var hubRow = ui.skills.hub.find(function (candidate) { return candidate.name === row.name; });
            pane.append(skillRow(row, !!(hubRow === null || hubRow === void 0 ? void 0 : hubRow.update_available), ui));
        };
        for (var _i = 0, rows_4 = rows; _i < rows_4.length; _i++) {
            var row = rows_4[_i];
            _loop_13(row);
        }
    }
    // "What the model sees": the engine's own skills_manifest() — the exact
    // byte-stable index injected into the system prompt, never a TS re-build
    // of it (single source of truth; a reconstruction would drift silently).
    var manifestSection = element('div', 'crusorai-skills-manifest');
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
function renderManager(root, model, host, openTools, activity, planOpen, setPlanOpen, ui) {
    var _a, _b, _c;
    var shell = element('div', 'crusorai-manager-shell');
    var sidebar = element('aside', 'crusorai-manager-sidebar', element('header', 'crusorai-manager-pane-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'CONTROL PLANE'), element('h2', undefined, 'Workspaces')), button('', 'crusorai-icon-button', function () { var _a; return (_a = host.newSession) === null || _a === void 0 ? void 0 : _a.call(host); }, 'add')), element('div', 'crusorai-manager-search', icon('search'), element('span', undefined, 'Find workspace or agent')), sessionList(model, host), element('footer', 'crusorai-manager-sidebar-footer', icon('organization'), element('span', undefined, ((_a = model.sessions) === null || _a === void 0 ? void 0 : _a.length) ? "".concat(model.sessions.length, " session(s) remembered \u00B7 ").concat(model.running ? '1 running' : 'none running') : 'No session yet')));
    var main = element('main', 'crusorai-manager-main');
    // Session + Skills are real tabs (tab state drives the column below);
    // Tools/Changes stay display-only exactly as they were — inventing
    // half-empty views for them is scope the plan did not ask for.
    var tabs = element('nav', 'crusorai-manager-tabs', button('Session', ui.tab === 'session' ? 'is-active' : '', function () { return ui.setTab('session'); }, 'comment-discussion'), element('button', undefined, icon('terminal'), "Tools ".concat(model.tools.length)), element('button', undefined, icon('diff'), 'Changes'), button(ui.skills.loaded && ui.skills.rows.length > 0 ? "Skills ".concat(ui.skills.rows.length) : 'Skills', ui.tab === 'skills' ? 'is-active' : '', function () { return ui.setTab('skills'); }, 'library'));
    main.append.apply(main, __spreadArray(__spreadArray([element('header', 'crusorai-manager-titlebar', element('div', undefined, element('div', 'crusorai-manager-breadcrumb', model.workspaceLabel, ' / ', (_c = (_b = model.sessionId) === null || _b === void 0 ? void 0 : _b.slice(0, 12)) !== null && _c !== void 0 ? _c : 'new-session'), element('h1', undefined, model.userMessage || 'Crusor Manager')), engineStatus(model)),
        tabs], (ui.tab === 'skills'
        ? [skillsPanel(ui, host)]
        : agentColumn(model, host, openTools, activity, planOpen, setPlanOpen)), false), [composer(model, host, true)], false));
    shell.append(sidebar, main, inspector(model));
    root.append(shell);
}
export function mountCrusorAIRenderer(root, surface, host) {
    // Global keys (Esc-to-interrupt, approval-dock and clarify shortcuts)
    // used to install only when an approval/clarify card first rendered —
    // a plain turn had NO Escape handler at all. The installer is flag-
    // guarded, so mounting the pane once is enough for the app's lifetime.
    ensureGlobalCardKeys();
    var openTools = new Set();
    var planOpen;
    var planSession;
    var disposed = false;
    var lastModel;
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
    var lastPaint;
    var lastTextPart = function (model) {
        for (var i = model.parts.length - 1; i >= 0; i--) {
            var part = model.parts[i];
            if (part.kind === 'text' && part.text) {
                return part;
            }
        }
        return undefined;
    };
    var paintSignature = function (model) {
        var shape = model.parts.map(function (p) { return (p.kind === 'tool' ? "tool:".concat(p.toolId) : 'text') + (p.kind === 'reasoning' ? ":r".concat(p.reasoningIndex) : ''); }).join('>');
        return "".concat(JSON.stringify(__assign(__assign({}, model), { assistantText: undefined, parts: undefined, reasoningParts: undefined })), "|").concat(shape);
    };
    // The activity row's timers outlive individual renders; a tick repaints from the last model,
    // which is what makes the seconds move while the engine is quiet.
    var activity = createActivityState(function () { if (!disposed) {
        tick();
    } });
    var tick = function () { if (!disposed && lastModel) {
        paint(lastModel);
    } };
    // ---- Manager Skills tab state (mount scope: survives wholesale repaints) ----
    var managerTab = 'session';
    var managerAction;
    var managerActionError;
    var managerConfirmRemove;
    var confirmRemoveTimer;
    var managerSkills = { loading: false, loaded: false, rows: [], hub: [], manifest: '' };
    var loadSkills = function () {
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
        ]).then(function (_a) {
            var _b, _c, _d;
            var all = _a[0], list = _a[1], manifest = _a[2];
            if (all.ok === false) {
                managerSkills.rows = [];
                managerSkills.error = String((_b = all.error) !== null && _b !== void 0 ? _b : 'could not list installed skills');
            }
            else {
                managerSkills.rows = Array.isArray(all.skills) ? all.skills : [];
            }
            if (list.ok === false) {
                managerSkills.hub = [];
                managerSkills.hubError = String((_c = list.error) !== null && _c !== void 0 ? _c : 'could not list hub-installed skills');
            }
            else {
                managerSkills.hub = Array.isArray(list.installed) ? list.installed : [];
                managerSkills.hubError = undefined;
            }
            if (manifest.ok === false) {
                managerSkills.manifest = '';
                managerSkills.manifestError = String((_d = manifest.error) !== null && _d !== void 0 ? _d : 'could not read the skills index');
            }
            else {
                managerSkills.manifest = typeof manifest.manifest === 'string' ? manifest.manifest : '';
                managerSkills.manifestError = undefined;
            }
            managerSkills.loading = false;
            managerSkills.loaded = true;
            tick();
        }, function (error) {
            var _a;
            managerSkills.loading = false;
            managerSkills.loaded = true;
            managerSkills.error = String((_a = error === null || error === void 0 ? void 0 : error.message) !== null && _a !== void 0 ? _a : error);
            tick();
        });
    };
    var runManagerAction = function (op, name, extra) {
        if (!host.skillsHubOp || managerAction) {
            return;
        }
        managerAction = { name: name, op: op };
        managerActionError = undefined;
        managerConfirmRemove = undefined;
        if (confirmRemoveTimer !== undefined) {
            clearTimeout(confirmRemoveTimer);
            confirmRemoveTimer = undefined;
        }
        tick();
        void host.skillsHubOp(op, __assign({ name: name }, (extra !== null && extra !== void 0 ? extra : {}))).then(function (result) {
            var _a;
            if (result && result.ok === false) {
                managerActionError = "".concat(name, ": ").concat(String((_a = result.error) !== null && _a !== void 0 ? _a : "".concat(op, " failed")));
                return false;
            }
            return true;
        }, function (error) {
            var _a;
            managerActionError = "".concat(name, ": ").concat(String((_a = error === null || error === void 0 ? void 0 : error.message) !== null && _a !== void 0 ? _a : error));
            return false;
        }).then(function (refreshed) {
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
    var confirmManagerRemove = function (name) {
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
            confirmRemoveTimer = setTimeout(function () {
                managerConfirmRemove = undefined;
                confirmRemoveTimer = undefined;
                tick();
            }, 4000);
            tick();
            return;
        }
        runManagerAction('remove', name);
    };
    var managerUi = {
        get tab() { return managerTab; },
        setTab: function (tab) {
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
    var paint = function (model) {
        var _a, _b, _c;
        if (model.sessionId !== planSession) {
            planSession = model.sessionId;
            planOpen = undefined;
            lastPaint = undefined;
        }
        var signature = paintSignature(model);
        var streaming = lastTextPart(model);
        if (lastPaint
            && lastPaint.signature === signature
            && streaming
            && streaming.text !== lastPaint.text
            && streaming.text.startsWith(lastPaint.text)) {
            var slot = root.querySelector('[data-slot="session-turn-content"]');
            if (slot) {
                slot.replaceChildren(markdownCopy(streaming.text, 'session-turn-content'));
                var scroller = root.querySelector('.crusorai-transcript-scroll');
                if (scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 32) {
                    scroller.scrollTop = scroller.scrollHeight;
                }
                lastPaint = { signature: signature, text: streaming.text };
                return;
            }
            // No live slot even though the shape says one should exist — the
            // DOM does not match the model; take the full paint to resync.
        }
        var previousScroll = root.querySelector('.crusorai-transcript-scroll');
        var scrollTop = (_a = previousScroll === null || previousScroll === void 0 ? void 0 : previousScroll.scrollTop) !== null && _a !== void 0 ? _a : 0;
        var wasNearBottom = !previousScroll || previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 32;
        var activeElement = document.activeElement;
        var activeComposer = root.contains(activeElement) && activeElement instanceof HTMLTextAreaElement ? activeElement : undefined;
        // Don't steal focus from ask tool (clarify card) — vibrations/streaming re-renders were
        // yanking focus back to the main composer while user typed in the card
        var isClarifyInput = (activeComposer === null || activeComposer === void 0 ? void 0 : activeComposer.closest('.crusorai-clarify-card')) !== null;
        var selectionStart = activeComposer === null || activeComposer === void 0 ? void 0 : activeComposer.selectionStart;
        var selectionEnd = activeComposer === null || activeComposer === void 0 ? void 0 : activeComposer.selectionEnd;
        root.replaceChildren();
        root.dataset.surface = surface;
        if (surface === 'agent') {
            renderAgent(root, model, host, openTools, planOpen, function (open) { planOpen = open; }, activity);
        }
        else {
            renderManager(root, model, host, openTools, activity, planOpen, function (open) { planOpen = open; }, managerUi);
        }
        var nextScroll = root.querySelector('.crusorai-transcript-scroll');
        if (nextScroll) {
            nextScroll.scrollTop = wasNearBottom ? nextScroll.scrollHeight : scrollTop;
        }
        if (activeComposer && !isClarifyInput && activeComposer.classList.contains('crusorai-composer-input')) {
            var input = root.querySelector('.crusorai-composer-input');
            input === null || input === void 0 ? void 0 : input.focus({ preventScroll: true });
            if (input && selectionStart !== undefined && selectionEnd !== undefined) {
                input.setSelectionRange(selectionStart, selectionEnd);
            }
        }
        else if (isClarifyInput && activeComposer) {
            // Restore focus to the clarify card's textarea (it was recreated by replaceChildren)
            var nextClarify = root.querySelector('.crusorai-clarify-card textarea');
            if (nextClarify) {
                nextClarify.focus({ preventScroll: true });
                if (selectionStart !== undefined && selectionEnd !== undefined) {
                    nextClarify.setSelectionRange(selectionStart, selectionEnd);
                }
            }
        }
        lastPaint = { signature: signature, text: (_c = (_b = lastTextPart(model)) === null || _b === void 0 ? void 0 : _b.text) !== null && _c !== void 0 ? _c : '' };
    };
    return {
        update: function (model) {
            if (disposed) {
                return;
            }
            lastModel = model;
            activity.sync(model);
            paint(model);
        },
        dispose: function () {
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
