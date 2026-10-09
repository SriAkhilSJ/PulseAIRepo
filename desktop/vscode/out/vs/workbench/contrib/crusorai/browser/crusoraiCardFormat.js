/*---------------------------------------------------------------------------------------------
 * Card-content formatting, ported from hermes desktop (owner 2026-09-09:
 * "resolve the gaps fully — mimic exact wireframes"). Pure functions, no DOM —
 * the same discipline as hermes' changed-files.ts ("Pure derivation… No
 * React/DOM") and lib/ansi.ts ("returns a flat array of styled segments").
 * The renderer paints; this file decides WHAT is painted.
 *--------------------------------------------------------------------------------------------*/
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
var FG_BY_CODE = {
    30: 'black', 31: 'red', 32: 'green', 33: 'yellow',
    34: 'blue', 35: 'magenta', 36: 'cyan', 37: 'white',
    90: 'bright-black', 91: 'bright-red', 92: 'bright-green', 93: 'bright-yellow',
    94: 'bright-blue', 95: 'bright-magenta', 96: 'bright-cyan', 97: 'bright-white',
};
// CSI = ESC '[' params 'final'. Only SGR (final 'm') is applied; other finals
// are matched and consumed so they don't leak into the rendered text.
var CSI_RE = /\x1b\[([\d;]*)([\x40-\x7e])/g;
// Other escapes (single-char OSC/SS3 etc.) — stripped silently.
var OTHER_ESCAPE_RE = /\x1b[@-Z\\-_]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;
export function hasAnsiCodes(input) {
    return /\x1b\[/.test(input);
}
export function stripAnsi(input) {
    if (!input) {
        return input;
    }
    return input.replace(OTHER_ESCAPE_RE, '').replace(CSI_RE, '');
}
export function parseAnsi(input) {
    if (!input) {
        return [];
    }
    var cleaned = input.replace(OTHER_ESCAPE_RE, '');
    var segments = [];
    var cursor = 0;
    var bold = false;
    var fg = null;
    var pushText = function (text) {
        if (!text) {
            return;
        }
        var last = segments[segments.length - 1];
        if (last && last.bold === bold && last.fg === fg) {
            segments[segments.length - 1] = { bold: bold, fg: fg, text: last.text + text };
            return;
        }
        segments.push({ bold: bold, fg: fg, text: text });
    };
    CSI_RE.lastIndex = 0;
    var match;
    while ((match = CSI_RE.exec(cleaned)) !== null) {
        var start = match.index;
        if (start > cursor) {
            pushText(cleaned.slice(cursor, start));
        }
        if (match[2] === 'm') {
            var codes = match[1].split(';').map(function (part) { return (part === '' ? 0 : Number(part)); })
                .filter(function (value) { return Number.isFinite(value); });
            for (var i = 0; i < codes.length; i += 1) {
                var code = codes[i];
                if (code === 0) {
                    bold = false;
                    fg = null;
                }
                else if (code === 1) {
                    bold = true;
                }
                else if (code === 22) {
                    bold = false;
                }
                else if (code === 39) {
                    fg = null;
                }
                else if (code in FG_BY_CODE) {
                    fg = FG_BY_CODE[code];
                }
                else if (code === 38) {
                    // 256-color / truecolor — skip the trailing args we don't render.
                    if (codes[i + 1] === 5) {
                        i += 2;
                    }
                    else if (codes[i + 1] === 2) {
                        i += 4;
                    }
                }
            }
        }
        cursor = CSI_RE.lastIndex;
    }
    if (cursor < cleaned.length) {
        pushText(cleaned.slice(cursor));
    }
    return segments;
}
var DIFF_HEADER_PREFIXES = [
    'diff --git', 'index ', '--- ', '+++ ',
    'similarity ', 'rename ', 'new file', 'deleted file',
];
function isArrowHeaderLine(line) {
    var trimmed = line.trim();
    return trimmed.includes('→') && /^\S.*→\s*\S+$/.test(trimmed) && !/^[+\-@]/.test(trimmed);
}
/** hermes stripDiffFileHeaders: strip the header zone up to the first hunk. */
export function stripDiffFileHeaders(diff) {
    var lines = diff.split('\n');
    var start = 0;
    var _loop_1 = function () {
        var line = lines[start];
        if (line.startsWith('@@')) {
            return "break";
        }
        if (line.trim() === '' || isArrowHeaderLine(line)
            || DIFF_HEADER_PREFIXES.some(function (prefix) { return line.startsWith(prefix); })) {
            return "continue";
        }
        return "break";
    };
    for (; start < lines.length; start += 1) {
        var state_1 = _loop_1();
        if (state_1 === "break")
            break;
    }
    return lines.slice(start).join('\n');
}
function diffKind(line) {
    if (line.startsWith('+') && !line.startsWith('+++')) {
        return 'add';
    }
    if (line.startsWith('-') && !line.startsWith('---')) {
        return 'remove';
    }
    return 'context';
}
/** Drop the leading +/-/space gutter so changes read by color alone. */
function stripDiffMarker(line) {
    if (diffKind(line) !== 'context' || line.startsWith(' ')) {
        return line.slice(1);
    }
    return line;
}
/** hermes parseDiff: hunks parsed, line numbers tracked, blank separator
 *  between hunks; non-hunk payloads fall back to line-by-line kinds. */
export function parseDiff(diff) {
    var cleaned = stripDiffFileHeaders(diff);
    var rawLines = cleaned.split('\n');
    var out = [];
    var emitted = false;
    var oldNo = 1;
    var newNo = 1;
    var active = null;
    var inHunk = false;
    for (var _i = 0, rawLines_1 = rawLines; _i < rawLines_1.length; _i++) {
        var line = rawLines_1[_i];
        if (line.startsWith('@@')) {
            var match = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
            if (!match) {
                active = null;
                continue;
            }
            if (emitted) {
                out.push({ kind: 'context', text: '' });
            }
            active = { oldStart: Number(match[1]), newStart: Number(match[2]) };
            oldNo = active.oldStart;
            newNo = active.newStart;
            inHunk = true;
            continue;
        }
        if (!inHunk || !active || line.startsWith('\\')) {
            continue;
        }
        var kind = diffKind(line);
        var entry = { kind: kind, text: stripDiffMarker(line) };
        if (kind === 'add') {
            entry.newNo = newNo++;
        }
        else if (kind === 'remove') {
            entry.oldNo = oldNo++;
        }
        else {
            entry.oldNo = oldNo++;
            entry.newNo = newNo++;
        }
        out.push(entry);
        emitted = true;
    }
    if (!emitted) {
        // Fallback for unexpected non-hunk payloads (hermes does the same).
        return rawLines.map(function (line) { return ({ kind: diffKind(line), text: stripDiffMarker(line) }); });
    }
    return out;
}
/** hermes countDiffLineStats: +/- lines, git headers excluded. */
export function countDiffLineStats(diff) {
    var added = 0;
    var removed = 0;
    for (var _i = 0, _a = diff.split('\n'); _i < _a.length; _i++) {
        var line = _a[_i];
        if (line.startsWith('+++') || line.startsWith('---')) {
            continue;
        }
        if (line.startsWith('+')) {
            added += 1;
        }
        else if (line.startsWith('-')) {
            removed += 1;
        }
    }
    return { added: added, removed: removed };
}
function resultDiffString(result) {
    if (typeof result === 'string') {
        return result;
    }
    if (result && typeof result === 'object') {
        var diff = result['diff'];
        if (typeof diff === 'string') {
            return diff;
        }
    }
    return '';
}
function resultPathString(args, result) {
    var _a;
    for (var _i = 0, _b = [args, result]; _i < _b.length; _i++) {
        var source = _b[_i];
        if (source && typeof source === 'object') {
            var path = (_a = source['path']) !== null && _a !== void 0 ? _a : source['dest'];
            if (typeof path === 'string' && path) {
                return path;
            }
        }
    }
    return '';
}
/** One row per file the turn edited, in first-touched order, +/- summed.
 *  Only LANDED edits count: running has no result, failed changed nothing. */
export function deriveChangedFiles(tools) {
    var byPath = new Map();
    for (var _i = 0, tools_1 = tools; _i < tools_1.length; _i++) {
        var tool = tools_1[_i];
        if (!['write_file', 'edit_file', 'copy_file'].includes(tool.name)) {
            continue;
        }
        if (tool.state !== 'passed' && tool.state !== 'completed') {
            continue;
        }
        var path = resultPathString(tool.arguments, tool.result);
        if (!path) {
            continue;
        }
        // Exact counts first: the engine receipt carries
        // "(lines added: N, removed: M)" — the bounded diff PREVIEW in the
        // same result would undercount a large change (field 2026-09-10:
        // the old bare "File written: <path>" receipt counted +0 -0).
        var text = typeof tool.result === 'string' ? tool.result : '';
        var receiptStats = /lines added:\s*(\d+),\s*removed:\s*(\d+)/i.exec(text);
        var stats = void 0;
        if (receiptStats) {
            stats = { added: Number(receiptStats[1]), removed: Number(receiptStats[2]) };
        }
        else {
            var diff = resultDiffString(tool.result);
            if (!diff) {
                continue;
            }
            stats = countDiffLineStats(diff);
        }
        var existing = byPath.get(path);
        if (existing) {
            existing.added += stats.added;
            existing.removed += stats.removed;
        }
        else {
            var name = path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || path;
            byPath.set(path, { added: stats.added, name: name, path: path, removed: stats.removed });
        }
    }
    return __spreadArray([], byPath.values(), true);
}
/** Lines are clamped for *paint*, never for correctness. */
export function windowedTailLines(text, max) {
    if (max === void 0) { max = 400; }
    var lines = (text !== null && text !== void 0 ? text : '').split('\n');
    if (lines.length <= max) {
        return { lines: lines, hidden: 0 };
    }
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
export function hasTerminalEnvelope(text) {
    return /^STDOUT:\s*$/m.test(text !== null && text !== void 0 ? text : '') && /^Exit code: -?\d+\s*$/m.test(text !== null && text !== void 0 ? text : '');
}
/** Drop the engine's STDOUT:/STDERR: marker lines, keep the output itself. */
export function stripTerminalEnvelope(text) {
    var lines = (text !== null && text !== void 0 ? text : '').split('\n');
    if (!lines.length) {
        return text !== null && text !== void 0 ? text : '';
    }
    var enveloped = hasTerminalEnvelope(text);
    var keep = lines.filter(function (line, i) {
        if (i === 0 && line.trimEnd() === 'STDOUT:') {
            return false;
        }
        if (enveloped && line.trimEnd() === 'STDERR:') {
            return false;
        }
        return true;
    });
    return keep.join('\n');
}
