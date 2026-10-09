/*---------------------------------------------------------------------------------------------
 * Crusor Preview — the contract shared by the workbench host, the preview window, and the overlay.
 *
 * Three surfaces exchange these messages, and only two of them are ours at runtime:
 *
 *   workbench (this contribution)  --postMessage-->  preview window frame
 *   preview window (media/crusor-preview/preview.js) --> overlay (injected into the agent's page)
 *   overlay --> preview window --> workbench
 *
 * The overlay is INJECTED INTO THE PAGE THE AGENT BUILT, which the user may have written with any
 * framework, on any origin. It cannot import from us, and we cannot reach into it: every message
 * below is a plain object crossing a window boundary. That is exactly why the names live here, in
 * a module with no imports of its own — the messages are strings, and a typo in one of them is a
 * silently dead feature. `src/tests/test_preview_contract.py` pins these literals against the two
 * JavaScript files that must agree with them, and exercises the pure helpers below through node.
 *
 * Nothing in this file touches `vscode` or the DOM: it is imported by the browser layer AND by
 * that node-driven test.
 *--------------------------------------------------------------------------------------------*/
export var CRUSOR_PREVIEW_VERSION = 1;
/** `data-*` marker the injected overlay leaves on its own tag, used to find the frame it lives in. */
export var CRUSOR_PREVIEW_OVERLAY_ID = 'crusor-preview-overlay';
/** `postMessage` identities. A receiver ignores anything whose `source` is not its peer's. */
export var CrusorPreviewSource = {
    /** set by the injected overlay on everything it sends */
    Overlay: 'crusor-preview-overlay',
    /** set by the preview window when it commands the overlay (it IS the overlay's host) */
    OverlayHost: 'crusor-preview-host',
    /** set by the workbench when it commands the preview window */
    Workbench: 'crusor-preview-workbench',
    /** set by the preview window on everything it sends up to the workbench */
    Window: 'crusor-preview-window',
};
/**
 * The turn text for "the preview is down — bring it back". Sent as an ordinary
 * prompt frame when the user clicks the red Preview tab, so the agent restarts
 * the dev server and re-opens the preview instead of the user hand-holding it.
 */
export function buildPreviewRelaunchPrompt(target) {
    var where = (target === null || target === void 0 ? void 0 : target.url) || (target === null || target === void 0 ? void 0 : target.file) || (target === null || target === void 0 ? void 0 : target.label) || 'the last preview target';
    return [
        "The Crusor Preview window could not load ".concat(where, " \u2014 the dev server behind it is down or answering with an error."),
        'Bring the preview back, exactly like this:',
        '1. Find the dev server this project uses (check package.json scripts and your earlier work in this session).',
        '2. Start it in the background (never block the turn on it), wait until the port answers.',
        '3. Verify it serves: request the URL and expect HTTP 200 (a compile error is 500 — fix the compile error first).',
        '4. Call invoke_host_capability with {"capability_id":"preview.open","arguments":{"url":"<the working URL>"}} and check the receipt\'s target_reachable — do not report success while it is false.',
        "Do not change application code unless step 3 shows a real error to fix. Target: ".concat(where),
    ].join('\n');
}
/** Commands the preview window sends INTO the injected overlay. */
export var CrusorPreviewOverlayCommand = {
    Configure: 'configure',
    Inspect: 'inspect',
    Pins: 'pins',
    ClearPins: 'clear-pins',
    Flash: 'flash',
    ClosePanel: 'close-panel',
};
/** Events the injected overlay emits to the preview window. */
export var CrusorPreviewOverlayEvent = {
    Ready: 'ready',
    Inspect: 'inspect',
    Selected: 'selected',
    Fix: 'fix',
    PinClick: 'pin-click',
    /** Ctrl+R/F5 pressed while the framed page had focus — the chrome reloads the iframe. */
    Reload: 'reload',
};
/** Commands the workbench sends to the preview window. */
export var CrusorPreviewWindowCommand = {
    Configure: 'configure',
    Theme: 'theme',
    SetTarget: 'set-target',
    Inspect: 'inspect',
    AgentApplied: 'agent-applied',
    Toast: 'toast',
};
/** Events the preview window emits to the workbench. */
export var CrusorPreviewWindowEvent = {
    Ready: 'ready',
    Navigate: 'navigate',
    ThemeApplied: 'theme-applied',
    Inspect: 'inspect',
    ElementSelected: 'element-selected',
    FixAdded: 'fix-added',
    ReviewOpen: 'review-open',
    ReviewClose: 'review-close',
    /** the injected overlay answered after a (re)load — inspect is only possible once it does */
    OverlayReady: 'overlay-ready',
    /** the reviewed batch — this is the handoff that becomes an agent turn */
    ReviewSubmit: 'review-submit',
    OpenSource: 'open-source',
    CloseRequest: 'close-request',
    Viewport: 'viewport',
    /** the framed app answered 5xx — the preview works, the app's build is broken */
    TargetError: 'target-error',
    /** the framed app loaded clean (overlay answered, no 5xx, no unreachable) — the only green state */
    TargetOk: 'target-ok',
};
export var DEFAULT_UI_PATH = '/crusor-preview/ui/';
/** `http://127.0.0.1:8931/crusor-preview/ui/?target=…&label=…` */
export function previewWindowUrl(endpoint, options) {
    var origin = String(endpoint.origin || '').replace(/\/+$/, '');
    var base = origin + (endpoint.ui_path || DEFAULT_UI_PATH);
    var query = [];
    if (options.target) {
        query.push('target=' + encodeURIComponent(options.target));
    }
    if (options.label) {
        query.push('label=' + encodeURIComponent(options.label));
    }
    if (options.kind) {
        query.push('kind=' + encodeURIComponent(options.kind));
    }
    if (options.sessionId) {
        query.push('session=' + encodeURIComponent(options.sessionId));
    }
    return query.length ? base + '?' + query.join('&') : base;
}
/**
 * Query string the preview window needs in order to reach its proxy: the endpoint origin (because the
 * window registers the target itself) and the run secret (because registration is gated — the window's
 * origin is opaque, so the proxy cannot tell our window from a hostile one by origin alone).
 */
export function previewWindowQuery(endpoint, extra) {
    if (extra === void 0) { extra = {}; }
    // A list of pairs, not a list of strings: `query.map(([key, value]) => ...)` destructures pairs, and a
    // flat string destructures into its first two characters instead — which is how a URL silently turns
    // into `e=n&n=d&d=p…` while every test still passes.
    var query = [['endpoint', String(endpoint.origin || '').replace(/\/+$/, '')]];
    if (endpoint.secret) {
        query.push(['secret', endpoint.secret]);
    }
    for (var _i = 0, _a = Object.keys(extra); _i < _a.length; _i++) {
        var key = _a[_i];
        if (extra[key]) {
            query.push([key, extra[key]]);
        }
    }
    return query.map(function (_a) {
        var key = _a[0], value = _a[1];
        return "".concat(key, "=").concat(encodeURIComponent(value));
    }).join('&');
}
/** The proxied URL for a registered target — what the preview window frames. */
export function proxiedTargetUrl(endpoint, token, path) {
    if (path === void 0) { path = ''; }
    var origin = String(endpoint.origin || '').replace(/\/+$/, '');
    var suffix = String(path || '').replace(/^\/+/, '');
    return "".concat(origin, "/p/").concat(encodeURIComponent(token), "/").concat(suffix);
}
export function isBatchEmpty(batch) {
    return !batch || !Array.isArray(batch.fixes) || batch.fixes.filter(function (fix) { return ((fix === null || fix === void 0 ? void 0 : fix.instruction) || '').trim().length > 0; }).length === 0;
}
/** `<button> "Get started"` — the element line every surface shows. */
export function describeFixElement(fix) {
    var element = fix === null || fix === void 0 ? void 0 : fix.element;
    if (!element) {
        return 'element';
    }
    var text = String(element.text || '').trim();
    var classes = element.classes || [];
    if (text) {
        return "<".concat(element.tag, "> \"").concat(text.length > 40 ? text.slice(0, 39) + '…' : text, "\"");
    }
    if (classes.length) {
        return "<".concat(element.tag, "> .").concat(classes[0]);
    }
    return "<".concat(element.tag, ">");
}
/** `3 preview fixes · aurora-landing · dev server` */
export function summarizeBatch(batch) {
    var _a;
    var count = ((_a = batch === null || batch === void 0 ? void 0 : batch.fixes) === null || _a === void 0 ? void 0 : _a.length) || 0;
    var label = String((batch === null || batch === void 0 ? void 0 : batch.targetLabel) || (batch === null || batch === void 0 ? void 0 : batch.target) || '').trim();
    var fixes = "".concat(count, " preview fix").concat(count === 1 ? '' : 'es');
    return label ? "".concat(fixes, " \u00B7 ").concat(label) : fixes;
}
function quote(value, limit) {
    if (limit === void 0) { limit = 0; }
    var text = String(value !== null && value !== void 0 ? value : '').replace(/\s+/g, ' ').trim();
    if (!limit || text.length <= limit) {
        return text;
    }
    return text.slice(0, limit - 1).trimEnd() + '…';
}
function fingerprintLine(element) {
    var _a, _b;
    var parts = [];
    var classes = element.classes || [];
    if (classes.length) {
        parts.push('classes=' + classes.slice(0, 8).join(' '));
    }
    var text = quote(((_a = element.fingerprint) === null || _a === void 0 ? void 0 : _a.text) || element.text, 90);
    if (text) {
        parts.push("text=\"".concat(text, "\""));
    }
    var attrs = ((_b = element.fingerprint) === null || _b === void 0 ? void 0 : _b.attrs) || [];
    if (attrs.length) {
        parts.push('attrs=' + attrs.slice(0, 6).map(function (a) { return "".concat(a.name, "=\"").concat(quote(a.value, 60), "\""); }).join(', '));
    }
    if (element.id) {
        parts.push("id=\"".concat(quote(element.id, 60), "\""));
    }
    return parts.filter(Boolean).join(' · ');
}
function sourceLine(element) {
    var _a;
    var source = (_a = element.fingerprint) === null || _a === void 0 ? void 0 : _a.source;
    if (!(source === null || source === void 0 ? void 0 : source.file)) {
        return '';
    }
    var bits = [quote(source.file, 200)];
    if (typeof source.line === 'number' && source.line > 0) {
        bits.push("line ".concat(source.line));
    }
    if (source.component) {
        bits.push("component ".concat(quote(source.component, 80)));
    }
    return bits.join(' → ');
}
var SCOPE_RULES = [
    'Apply every fix below. Each one was created by clicking an element in the live preview of the UI you built, so:',
    '- change ONLY the named elements; leave the rest of the page alone;',
    '- locate each element in the source with the fingerprints given (grep the classes, the text, the data attributes) before editing — do not guess a file;',
    "- keep the fix minimal and in the project's own style system (its tokens/variables/utility classes), not inline overrides, unless the project already does that;",
    '- if a fix is ambiguous or the element cannot be found, say so for that fix and continue with the others;',
    '- when done, list the files you changed.',
].join('\n');
/**
 * The scoped turn text. Canonical builder for engine-side hosts is
 * `src/preview/prompt.py` (`build_preview_prompt`); this mirror exists because the composer must
 * show the EXACT text before the turn is dispatched, and a renderer cannot call Python. The
 * cross-language test pins that both carry the same required fields and scope rules.
 */
export function buildPreviewPrompt(batch, options) {
    var _a;
    var fixes = ((batch === null || batch === void 0 ? void 0 : batch.fixes) || []).filter(function (fix) { return ((fix === null || fix === void 0 ? void 0 : fix.instruction) || '').trim().length > 0; });
    if (!fixes.length) {
        return '';
    }
    var maxChars = (_a = options === null || options === void 0 ? void 0 : options.maxChars) !== null && _a !== void 0 ? _a : 12000;
    var target = quote(batch.targetLabel || batch.target, 200) || 'the previewed page';
    var header = [
        "<!-- crusor-preview:fix-batch count=".concat(fixes.length, " -->"),
        "Crusor Preview \u2014 ".concat(fixes.length, " UI fix").concat(fixes.length === 1 ? '' : 'es', " from the live preview of ").concat(target, "."),
        '',
        SCOPE_RULES,
    ];
    if (batch.viewport && batch.viewport !== 'responsive') {
        header.push("(Previewed at the ".concat(batch.viewport, " viewport preset.)"));
    }
    var blocks = [];
    var dropped = 0;
    var _loop_1 = function (index) {
        var fix = fixes[index];
        var element = fix.element || {};
        var lines = [
            "Fix ".concat(index + 1, " \u2014 ").concat(quote(fix.label, 120) || describeFixElement(fix)),
            "  instruction: ".concat(quote(fix.instruction, 400)),
        ];
        if (element.selector) {
            lines.push("  selector: ".concat(quote(element.selector, 220)));
        }
        var fingerprint = fingerprintLine(element);
        if (fingerprint) {
            lines.push("  fingerprint: ".concat(fingerprint));
        }
        var source = sourceLine(element);
        if (source) {
            lines.push("  source: ".concat(source));
        }
        if (element.rect) {
            var box = "  box: ".concat(element.rect.width, "\u00D7").concat(element.rect.height, " at (").concat(element.rect.x, ",").concat(element.rect.y, ")");
            if (element.viewport) {
                box += " \u00B7 viewport ".concat(element.viewport.width, "\u00D7").concat(element.viewport.height);
            }
            lines.push(box);
        }
        if (element.styles) {
            var rendered = Object.keys(element.styles).slice(0, 10).map(function (key) { return "".concat(key, ": ").concat(element.styles[key]); });
            if (rendered.length) {
                lines.push("  styles: ".concat(rendered.join('; ')));
            }
        }
        var html = quote(element.outerHtml, 420);
        if (html) {
            lines.push("  html: ".concat(html));
        }
        var candidate = blocks.concat([lines.join('\n')]).join('\n\n');
        if (header.join('\n').length + candidate.length > maxChars) {
            dropped = fixes.length - index;
            return "break";
        }
        blocks.push(lines.join('\n'));
    };
    for (var index = 0; index < fixes.length; index++) {
        var state_1 = _loop_1(index);
        if (state_1 === "break")
            break;
    }
    var parts = [header.join('\n'), '', blocks.join('\n\n')];
    if (dropped) {
        parts.push("\n(".concat(dropped, " further fix").concat(dropped === 1 ? '' : 'es', " were left out to stay inside the prompt budget \u2014 ask me to re-send them.)"));
    }
    parts.push('\nAfter editing, re-read the lines you changed to confirm them. Do not start a dev '
        + 'server, watcher, or any other long-running process to check your work — the preview window '
        + 're-renders the page itself, and the user sees the result in place.');
    return parts.join('\n').trim() + '\n';
}
var DEV_SERVER_PATTERNS = [
    /\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|preview)\b/i,
    /\b(?:vite|next|nuxt|astro|remix|parcel|webpack-dev-server|ng serve|expo start)\b/i,
    /\b(?:python3?|py)\s+-m\s+http\.server\b/i,
    /\b(?:flask|uvicorn|gunicorn|fastapi)\s+run\b/i,
    /\bphp\s+-S\b/i,
    /\bcargo\s+(?:run|watch)\b/i,
    /\bdotnet\s+run\b/i,
    /\bgo\s+run\b/i,
];
var LOCAL_URL = /\bhttps?:\/\/(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::(\d{1,5}))?[^\s"'`,;)]*/i;
var HTML_FILE = /\.(?:html?|xhtml)(?:$|[?#])/i;
var UI_FILE = /\.(?:tsx|jsx|vue|svelte|astro|css|scss|sass|less)(?:$|[?#])/i;
/**
 * Decide whether the session produced something previewable.
 *
 * Later evidence wins (the agent restarts a dev server on a new port, or writes a second page), so
 * the array is read back-to-front. A dev-server command is preferred over a written file because it
 * is a *live* target; a written HTML file is still previewable with no server at all, which is the
 * whole point of supporting `kind: 'file'`.
 */
export function detectPreviewAvailability(evidence) {
    var best = { available: false, reason: '' };
    var _loop_2 = function (index) {
        var entry = evidence[index];
        if (!entry) {
            return "continue";
        }
        if (entry.kind === 'command') {
            var text_1 = String(entry.text || '');
            if (!DEV_SERVER_PATTERNS.some(function (pattern) { return pattern.test(text_1); })) {
                return "continue";
            }
            var url = text_1.match(LOCAL_URL);
            if (url) {
                var raw = url[0].replace(/[.,;)]+$/, '');
                var normalized = raw.replace('0.0.0.0', '127.0.0.1').replace(/\/+$/, '/');
                return { value: {
                        available: true, reason: 'dev-server', url: normalized,
                        label: "dev server \u00B7 ".concat(new URL(normalized.replace('localhost', '127.0.0.1')).port || '80'),
                        evidence: text_1.trim().slice(0, 200),
                    } };
            }
            return "continue";
        }
        var path = String(entry.path || '');
        if (!path) {
            return "continue";
        }
        if (HTML_FILE.test(path)) {
            best = { available: true, reason: 'html-file', file: path, label: "workspace file \u00B7 ".concat(path), evidence: path };
            return "break";
        }
        if (!best.available && UI_FILE.test(path)) {
            // UI source with no server and no HTML yet: worth offering, nothing to frame.
            best = { available: true, reason: 'html-file', label: "UI source \u00B7 ".concat(path), evidence: path };
        }
    };
    for (var index = evidence.length - 1; index >= 0; index--) {
        var state_2 = _loop_2(index);
        if (typeof state_2 === "object")
            return state_2.value;
        if (state_2 === "break")
            break;
    }
    return best;
}
/** Fold one streamed tool call into preview evidence, defensively (arguments are engine-shaped). */
export function evidenceFromToolCall(name, args) {
    var _a;
    var tool = String(name || '').toLowerCase();
    var serialized = typeof args === 'string' ? args : safeStringify(args);
    if (/run|shell|bash|exec|terminal|command/.test(tool)) {
        return { kind: 'command', text: serialized.slice(0, 4000) };
    }
    if (/write|create|edit|apply|patch|multi_edit/.test(tool)) {
        var path = extractPath(args) || ((_a = serialized.match(/[\w./@-]+\.(?:html?|tsx|jsx|vue|svelte|astro|css)/i)) === null || _a === void 0 ? void 0 : _a[0]);
        if (path) {
            return { kind: 'file', path: path, text: serialized.slice(0, 500) };
        }
    }
    return undefined;
}
function extractPath(args) {
    if (!args || typeof args !== 'object') {
        return undefined;
    }
    var record = args;
    for (var _i = 0, _a = ['file_path', 'path', 'filePath', 'file', 'target_file', 'targetFile']; _i < _a.length; _i++) {
        var key = _a[_i];
        var value = record[key];
        if (typeof value === 'string' && value.trim()) {
            return value.trim();
        }
    }
    return undefined;
}
function safeStringify(value) {
    var _a;
    try {
        return (_a = JSON.stringify(value)) !== null && _a !== void 0 ? _a : '';
    }
    catch (_b) {
        return '';
    }
}
