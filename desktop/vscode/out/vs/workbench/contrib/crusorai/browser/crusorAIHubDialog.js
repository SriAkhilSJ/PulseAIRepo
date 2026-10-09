// Crusor Hub Dialog — the IN-PANEL dialog behind the composer + menu
// (field 2026-10-02 rev 4, owner spec: a real dialog box in the panel
// space — NEVER the top-center QuickPick).
//
// One card, four tabs:
//   Marketplace  — curated catalog: search, install (live, inline errors)
//   Connectors   — what the agent can reach beyond the workspace (MCP, …)
//   My Skills    — every installed skill: enable/disable, remove, usage
//   One-Shot     — quick jobs: template -> input -> result -> clipboard
//
// Data flows exclusively through the host's promise hooks
// (skillsHubOp / oneshotRun) — this module holds zero trust decisions and
// owns zero engine logic. The card anchors to the + button, opens upward
// into the chat space, closes on ×/Escape/click-away, and survives the
// composer's per-paint rebuilds by living on document.body while open.
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
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
function el(tag, className) {
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
function glyph(name) {
    var span = document.createElement('span');
    span.className = "codicon codicon-".concat(name);
    return span;
}
var openDialog;
// The card carries its own chrome. Field 2026-10-02: the owner's machine
// rendered this dialog INVISIBLE — the workbench stylesheet their runtime
// served predated every .crusorai-hub-* rule, and without
// `.crusorai-hub-dialog { position: fixed; … }` the card appended to the
// end of <body> as an unstyled static div (the inline left/bottom do
// nothing), so every + menu entry read as "buttons not working". Injecting
// the stylesheet from THIS module ships the chrome down the same channel
// as the markup — a stale workbench stylesheet can never blank the card
// again. This block is the single source of truth for hub-dialog chrome;
// media/crusorAI.css deliberately does not duplicate it.
var HUB_DIALOG_CSS = "\n.crusorai-hub-backdrop {\n\tposition: fixed; inset: 0; z-index: 2500;\n\tdisplay: flex; align-items: center; justify-content: center;\n\tbackground: rgba(0, 0, 0, 0.45);\n\tanimation: crusorai-hub-fade 120ms ease-out;\n}\n@keyframes crusorai-hub-fade {\n\tfrom { opacity: 0; }\n\tto { opacity: 1; }\n}\n.crusorai-hub-dialog {\n\tposition: relative; width: min(560px, calc(100vw - 48px)); max-height: min(520px, calc(100vh - 64px));\n\tdisplay: flex; flex-direction: column;\n\tpadding: 12px; border-radius: 10px;\n\tborder: 1px solid var(--vscode-panel-border, transparent);\n\tbackground: var(--vscode-editorWidget-background, #1f1f1f);\n\tcolor: var(--vscode-foreground, #cccccc);\n\tcolor-scheme: dark;\n\tfont: inherit;\n\tbox-shadow: 0 10px 34px rgba(0, 0, 0, 0.45);\n\tanimation: crusorai-hub-dialog-in 130ms ease-out;\n}\n@keyframes crusorai-hub-dialog-in {\n\tfrom { opacity: 0; transform: translateY(6px); }\n\tto { opacity: 1; transform: translateY(0); }\n}\n.crusorai-hub-dialog-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }\n.crusorai-hub-dialog-heading { font-weight: 700; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }\n.crusorai-hub-dialog-close {\n\tdisplay: inline-flex; align-items: center; justify-content: center;\n\twidth: 22px; height: 22px; padding: 0; border: none; border-radius: 5px;\n\tbackground: transparent; color: var(--vscode-foreground, #cccccc); cursor: pointer;\n}\n.crusorai-hub-dialog-close:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }\n.crusorai-hub-dialog-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 9px 0 2px; }\n.crusorai-hub-tab {\n\tpadding: 3px 9px; border: none; border-radius: 5px; cursor: pointer;\n\tbackground: transparent; color: var(--vscode-foreground, #cccccc); font: inherit; font-size: .95em;\n}\n.crusorai-hub-tab:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }\n.crusorai-hub-tab.is-active { background: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff); }\n.crusorai-hub-dialog-body { margin-top: 6px; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; scrollbar-color: var(--vscode-scrollbarSlider-background, #424242) transparent; }\n.crusorai-hub-dialog-search {\n\twidth: 100%; box-sizing: border-box; padding: 6px 8px;\n\tborder-radius: 6px; border: 1px solid var(--vscode-panel-border, transparent);\n\tbackground: var(--vscode-input-background, #3c3c3c); color: var(--vscode-input-foreground, #cccccc);\n\tfont: inherit;\n}\n.crusorai-hub-dialog-list { display: flex; flex-direction: column; gap: 4px; }\n.crusorai-hub-status { padding: 8px; opacity: .8; }\n.crusorai-hub-status.is-error { color: var(--vscode-errorForeground, #f48771); opacity: 1; }\n.crusorai-hub-row {\n\tdisplay: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 4px 8px;\n\tpadding: 7px 8px; border-radius: 6px;\n\tbackground: var(--vscode-editor-background, #1f1f1f);\n\tborder: 1px solid var(--vscode-panel-border, transparent);\n}\n.crusorai-hub-row-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }\n.crusorai-hub-row-title { display: flex; align-items: baseline; gap: .5em; flex-wrap: wrap; }\n.crusorai-hub-row-name { font-weight: 600; }\n.crusorai-hub-row-meta { font-size: .92em; opacity: .7; }\n.crusorai-hub-row-desc { font-size: .92em; opacity: .8; }\n.crusorai-hub-row-actions { display: flex; gap: 4px; align-items: center; }\n.crusorai-hub-row-error { width: 100%; font-size: .92em; word-break: break-word; color: var(--vscode-errorForeground, #f48771); }\n.crusorai-hub-mini {\n\tpadding: 3px 9px; border: none; border-radius: 5px; cursor: pointer;\n\tbackground: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff);\n\tfont: inherit; font-size: .95em; white-space: nowrap;\n}\n.crusorai-hub-mini:hover { background: var(--vscode-button-hoverBackground, #1177bb); }\n.crusorai-hub-mini:disabled { opacity: .6; cursor: default; }\n.crusorai-hub-mini.is-done { background: transparent; color: var(--vscode-foreground, #cccccc); opacity: .85; }\n.crusorai-hub-mini.is-danger { background: transparent; color: var(--vscode-errorForeground, #f48771); }\n.crusorai-hub-mini.is-primary { align-self: flex-start; }\n.crusorai-hub-attach, .crusorai-hub-create { display: flex; flex-direction: column; gap: 6px; padding-top: 8px; border-top: 1px solid var(--vscode-panel-border, transparent); }\nselect.crusorai-hub-dialog-search { height: 30px; padding: 4px 8px; }\n.crusorai-hub-create { margin-top: 6px; }\n.crusorai-hub-state {\n\tdisplay: inline-flex; align-items: center; gap: .4em; margin-left: auto;\n\tpadding: 1px 8px; border-radius: 20px; font-size: .92em; white-space: nowrap;\n}\n.crusorai-hub-state::before { content: ''; width: .6em; height: .6em; border-radius: 50%; background: currentColor; }\n.crusorai-hub-state.is-connected { color: var(--vscode-testing-iconPassed, #3fb950); background: rgba(63, 185, 80, 0.12); }\n.crusorai-hub-state.is-setup { color: var(--vscode-editorWarning-foreground, #d29922); background: rgba(210, 153, 34, 0.12); }\n.crusorai-hub-oneshot { display: flex; flex-direction: column; gap: 7px; }\n.crusorai-hub-oneshot-chips { display: flex; flex-wrap: wrap; gap: 4px; }\n.crusorai-hub-chip {\n\tpadding: 3px 9px; border: 1px solid var(--vscode-panel-border, transparent); border-radius: 20px;\n\tbackground: transparent; color: var(--vscode-foreground, #cccccc); cursor: pointer; font: inherit; font-size: .95em;\n}\n.crusorai-hub-chip:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }\n.crusorai-hub-chip.is-active { background: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff); border-color: transparent; }\n.crusorai-hub-oneshot-label { font-weight: 600; }\n.crusorai-hub-oneshot-input {\n\twidth: 100%; box-sizing: border-box; padding: 6px 8px; resize: vertical;\n\tborder-radius: 6px; border: 1px solid var(--vscode-panel-border, transparent);\n\tbackground: var(--vscode-input-background, #3c3c3c); color: var(--vscode-input-foreground, #cccccc);\n\tfont: inherit;\n}\n.crusorai-hub-oneshot-result:empty { display: none; }\n.crusorai-hub-oneshot-output {\n\tmargin: 0; padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-word;\n\tbackground: var(--vscode-editor-background, rgba(127, 127, 127, 0.08));\n\tborder: 1px solid var(--vscode-panel-border, transparent);\n\tfont: inherit; font-size: .95em; max-height: 160px; overflow-y: auto;\n}\n";
var HUB_STYLE_ID = 'crusorai-hub-dialog-styles';
function ensureHubDialogStyles() {
    if (document.getElementById(HUB_STYLE_ID)) {
        return;
    }
    var style = document.createElement('style');
    style.id = HUB_STYLE_ID;
    style.textContent = HUB_DIALOG_CSS;
    document.head.append(style);
}
// The card mounts on document.body — OUTSIDE the subtree where the
// workbench defines its --vscode-* custom properties (field 2026-10-02
// rev 5: every var() resolved to nothing and the card painted transparent
// with default black text). So the resolved values are COPIED from the
// anchor — the + button lives inside the themed panel — onto the card's
// inline custom properties. The stylesheet's var() references then resolve
// against the card itself, in every theme, at any mount point.
var THEME_VARS = [
    'foreground', 'editorWidget-background', 'editor-background', 'panel-border',
    'input-background', 'input-foreground', 'button-background', 'button-foreground',
    'button-hoverBackground', 'list-hoverBackground', 'errorForeground',
];
function inheritPanelTheme(root, anchor) {
    var panel = getComputedStyle(anchor);
    for (var _i = 0, THEME_VARS_1 = THEME_VARS; _i < THEME_VARS_1.length; _i++) {
        var name = THEME_VARS_1[_i];
        var value = panel.getPropertyValue("--vscode-".concat(name)).trim();
        if (value) {
            root.style.setProperty("--vscode-".concat(name), value);
        }
    }
    if (panel.fontFamily) {
        root.style.fontFamily = panel.fontFamily;
    }
    if (panel.fontSize) {
        root.style.fontSize = panel.fontSize;
    }
    if (panel.colorScheme) {
        root.style.colorScheme = panel.colorScheme;
    }
}
function closeOpenDialog() {
    openDialog === null || openDialog === void 0 ? void 0 : openDialog.close();
}
export function openHubDialog(host, anchor, tab) {
    if (tab === void 0) { tab = 'marketplace'; }
    closeOpenDialog();
    if (typeof host.skillsHubOp !== 'function') {
        return; // host predates the hub — nothing to show
    }
    ensureHubDialogStyles();
    var titleBar = el('div', 'crusorai-hub-dialog-title', el('span', 'crusorai-hub-dialog-heading', 'Crusor'));
    var body = el('div', 'crusorai-hub-dialog-body');
    var closeBtn = el('button', 'crusorai-hub-dialog-close', glyph('close'));
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Close');
    titleBar.append(closeBtn);
    // rev 7 (owner: "spawn a dialog box rather than menu bar … pops in
    // fork"): the card opens as a CENTERED MODAL over the whole pane —
    // dimmed backdrop, four tabs in the card — instead of a small popup
    // pinned above the + button. It still mounts on document.body
    // (survives composer repaints) and still inherits the panel theme
    // from the anchor (+ button lives inside the themed subtree).
    var backdrop = el('div', 'crusorai-hub-backdrop');
    var root = el('div', 'crusorai-hub-dialog', titleBar, body);
    inheritPanelTheme(backdrop, anchor);
    var close = function () {
        root.remove();
        backdrop.remove();
        document.removeEventListener('pointerdown', away, true);
        document.removeEventListener('keydown', onEscape, true);
        if ((openDialog === null || openDialog === void 0 ? void 0 : openDialog.root) === root) {
            openDialog = undefined;
        }
    };
    var away = function (event) {
        if (event.target === backdrop) {
            close();
        } // click on the dim, not the card
    };
    var onEscape = function (event) {
        if (event.key === 'Escape') {
            close();
        }
    };
    closeBtn.addEventListener('click', close);
    document.addEventListener('pointerdown', away, true);
    document.addEventListener('keydown', onEscape, true);
    backdrop.append(root);
    document.body.append(backdrop);
    openDialog = { root: root, close: close };
    var tabs = [
        { id: 'marketplace', label: 'Marketplace' },
        { id: 'connectors', label: 'Connectors' },
        { id: 'myskills', label: 'My Skills' },
        { id: 'oneshot', label: 'One-Shot' },
    ];
    var tabRow = el('div', 'crusorai-hub-dialog-tabs');
    var _loop_1 = function (entry) {
        var btn = el('button', entry.id === tab ? 'crusorai-hub-tab is-active' : 'crusorai-hub-tab', entry.label);
        btn.type = 'button';
        btn.addEventListener('click', function () {
            for (var _i = 0, _a = tabRow.querySelectorAll('button'); _i < _a.length; _i++) {
                var sibling = _a[_i];
                sibling.classList.remove('is-active');
            }
            btn.classList.add('is-active');
            render(body, host, entry.id);
        });
        tabRow.append(btn);
    };
    for (var _i = 0, tabs_1 = tabs; _i < tabs_1.length; _i++) {
        var entry = tabs_1[_i];
        _loop_1(entry);
    }
    titleBar.after(tabRow);
    var heading = titleBar.querySelector('.crusorai-hub-dialog-heading');
    var titles = {
        marketplace: 'Marketplace — install skills',
        connectors: 'Connectors — beyond the workspace',
        myskills: 'My Skills — everything installed',
        oneshot: 'One-Shot — quick jobs',
    };
    var setHeading = function (key) { heading.textContent = titles[key]; };
    var origRender = render;
    // keep the heading in sync with tab switches
    tabRow.addEventListener('click', function (event) {
        var _a, _b;
        var btn = event.target.closest('button');
        if (!btn) {
            return;
        }
        var index = Array.from(tabRow.children).indexOf(btn);
        setHeading((_b = (_a = tabs[index]) === null || _a === void 0 ? void 0 : _a.id) !== null && _b !== void 0 ? _b : 'marketplace');
    });
    void origRender; // (render is used directly below)
    setHeading(tab);
    render(body, host, tab);
}
function statusRow(message, isError) {
    if (isError === void 0) { isError = false; }
    return el('div', isError ? 'crusorai-hub-status is-error' : 'crusorai-hub-status', message);
}
function render(body, host, tab) {
    return __awaiter(this, void 0, Promise, function () {
        var _a, error_1;
        var _b;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0:
                    body.replaceChildren(statusRow('Loading…'));
                    _c.label = 1;
                case 1:
                    _c.trys.push([1, 10, , 11]);
                    _a = tab;
                    switch (_a) {
                        case 'marketplace': return [3 /*break*/, 2];
                        case 'connectors': return [3 /*break*/, 4];
                        case 'myskills': return [3 /*break*/, 6];
                        case 'oneshot': return [3 /*break*/, 8];
                    }
                    return [3 /*break*/, 9];
                case 2: return [4 /*yield*/, renderMarketplace(body, host)];
                case 3:
                    _c.sent();
                    return [3 /*break*/, 9];
                case 4: return [4 /*yield*/, renderConnectors(body, host)];
                case 5:
                    _c.sent();
                    return [3 /*break*/, 9];
                case 6: return [4 /*yield*/, renderMySkills(body, host)];
                case 7:
                    _c.sent();
                    return [3 /*break*/, 9];
                case 8:
                    renderOneshot(body, host);
                    return [3 /*break*/, 9];
                case 9: return [3 /*break*/, 11];
                case 10:
                    error_1 = _c.sent();
                    body.replaceChildren(statusRow(String((_b = error_1.message) !== null && _b !== void 0 ? _b : error_1), true));
                    return [3 /*break*/, 11];
                case 11: return [2 /*return*/];
            }
        });
    });
}
// The Create box's "Add skill" accepts either the Enhance output or a
// pasted skill file: pull name/description/triggers out of the YAML
// frontmatter when present, else treat the whole text as the body.
function parseSkillMd(text) {
    var t = text.trim();
    // a model may wrap the file in fences despite instructions — unwrap
    if (t.startsWith('```')) {
        t = t.replace(/^```[a-zA-Z0-9]*\s*\n/, '').replace(/```\s*$/, '').trim();
    }
    var m = t.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
    if (!m) {
        return { name: '', description: '', triggers: [], instruction: t };
    }
    var meta = m[1];
    var pick = function (key) {
        var mm = meta.match(new RegExp("^".concat(key, ":s*(.+)$"), 'm'));
        return mm ? mm[1].trim().replace(/^["']|["']$/g, '') : '';
    };
    return {
        name: pick('name'),
        description: pick('description'),
        triggers: pick('triggers').split(',').map(function (t) { return t.trim(); }).filter(Boolean),
        instruction: m[2].trim(),
    };
}
function renderMarketplace(body, host) {
    return __awaiter(this, void 0, Promise, function () {
        var _a, catalogRes, installedRes, entries, installedRows, installedKeys, updateKeys, search, list, rebuild, refresh, create, scopeSel, _i, _b, _c, value, label, opt, draftIn, contentIn, enhanceBtn, addBtn, createMsg, say;
        var _this = this;
        var _d;
        return __generator(this, function (_e) {
            switch (_e.label) {
                case 0: return [4 /*yield*/, Promise.all([
                        host.skillsHubOp('catalog'),
                        host.skillsHubOp('list'),
                    ])];
                case 1:
                    _a = _e.sent(), catalogRes = _a[0], installedRes = _a[1];
                    if (catalogRes.ok === false) {
                        throw new Error(String((_d = catalogRes.error) !== null && _d !== void 0 ? _d : 'catalog unavailable'));
                    }
                    entries = (Array.isArray(catalogRes.results) ? catalogRes.results : []);
                    installedRows = (installedRes.ok !== false && Array.isArray(installedRes.installed))
                        ? installedRes.installed : [];
                    installedKeys = new Set(installedRows.map(function (row) { return "".concat(row.repo, ":").concat(row.subdir); }));
                    updateKeys = new Set(installedRows.filter(function (row) { return row.update_available; }).map(function (row) { return "".concat(row.repo, ":").concat(row.subdir); }));
                    search = el('input', 'crusorai-hub-dialog-search');
                    search.type = 'text';
                    search.placeholder = 'Search the catalog…';
                    list = el('div', 'crusorai-hub-dialog-list');
                    rebuild = function (query) {
                        var _a, _b;
                        list.replaceChildren();
                        var tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
                        var matches = entries.filter(function (entry) {
                            var _a, _b;
                            var hay = "".concat(entry.name, " ").concat((_a = entry.category) !== null && _a !== void 0 ? _a : '', " ").concat((_b = entry.description) !== null && _b !== void 0 ? _b : '').toLowerCase();
                            return tokens.every(function (token) { return hay.includes(token); });
                        });
                        if (matches.length === 0) {
                            list.append(statusRow('No catalog match. Install any GitHub repo from chat: hub_install("owner/repo@<sha>").'));
                            return;
                        }
                        var _loop_2 = function (entry) {
                            var key = "".concat(entry.repo, ":").concat(entry.subdir);
                            var isInstalled = installedKeys.has(key);
                            var row = el('div', 'crusorai-hub-row');
                            var left = el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-title', el('span', 'crusorai-hub-row-name', entry.name), el('span', 'crusorai-hub-row-meta', "[".concat(entry.category || 'general', "] ").concat((_a = entry.trust) !== null && _a !== void 0 ? _a : '').trim())), el('div', 'crusorai-hub-row-desc', (_b = entry.description) !== null && _b !== void 0 ? _b : ''));
                            var action = el('button', isInstalled ? 'crusorai-hub-mini is-done' : 'crusorai-hub-mini');
                            action.type = 'button';
                            if (isInstalled) {
                                action.textContent = updateKeys.has(key) ? 'Update' : 'Installed ✓';
                                action.disabled = !updateKeys.has(key);
                                action.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                                    var res;
                                    var _a;
                                    return __generator(this, function (_b) {
                                        switch (_b.label) {
                                            case 0:
                                                action.disabled = true;
                                                action.textContent = 'Updating…';
                                                return [4 /*yield*/, host.skillsHubOp('update', { name: entry.name })];
                                            case 1:
                                                res = _b.sent();
                                                return [4 /*yield*/, refresh()];
                                            case 2:
                                                _b.sent();
                                                if (res.ok === false) {
                                                    markRowError(row, String((_a = res.error) !== null && _a !== void 0 ? _a : 'update failed'));
                                                }
                                                return [2 /*return*/];
                                        }
                                    });
                                }); });
                            }
                            else {
                                action.textContent = 'Install';
                                action.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                                    var res, warnings;
                                    var _a, _b;
                                    return __generator(this, function (_c) {
                                        switch (_c.label) {
                                            case 0:
                                                action.disabled = true;
                                                action.textContent = 'Installing…';
                                                return [4 /*yield*/, host.skillsHubOp('install', { source: entry.name })];
                                            case 1:
                                                res = _c.sent();
                                                if (res.ok === false) {
                                                    action.disabled = false;
                                                    action.textContent = 'Install';
                                                    markRowError(row, String((_a = res.error) !== null && _a !== void 0 ? _a : 'install failed'));
                                                    return [2 /*return*/];
                                                }
                                                installedKeys.add(key);
                                                action.className = 'crusorai-hub-mini is-done';
                                                action.textContent = 'Installed ✓';
                                                action.disabled = true;
                                                warnings = (_b = res.warnings) !== null && _b !== void 0 ? _b : [];
                                                if (warnings.length > 0) {
                                                    markRowError(row, "Installed, with warnings: ".concat(warnings.join('; ')));
                                                }
                                                return [2 /*return*/];
                                        }
                                    });
                                }); });
                            }
                            row.append(left, action);
                            list.append(row);
                        };
                        for (var _i = 0, matches_1 = matches; _i < matches_1.length; _i++) {
                            var entry = matches_1[_i];
                            _loop_2(entry);
                        }
                    };
                    refresh = function () { return __awaiter(_this, void 0, Promise, function () {
                        var _a, cat2, inst2, nextEntries, nextInstalled;
                        return __generator(this, function (_b) {
                            switch (_b.label) {
                                case 0: return [4 /*yield*/, Promise.all([host.skillsHubOp('catalog'), host.skillsHubOp('list')])];
                                case 1:
                                    _a = _b.sent(), cat2 = _a[0], inst2 = _a[1];
                                    if (cat2.ok !== false) {
                                        nextEntries = (Array.isArray(cat2.results) ? cat2.results : []);
                                        nextInstalled = (inst2.ok !== false && Array.isArray(inst2.installed))
                                            ? inst2.installed : [];
                                        entries.length = 0;
                                        entries.push.apply(entries, nextEntries);
                                        installedKeys.clear();
                                        nextInstalled.forEach(function (row) { return installedKeys.add("".concat(row.repo, ":").concat(row.subdir)); });
                                        rebuild(search.value);
                                    }
                                    return [2 /*return*/];
                            }
                        });
                    }); };
                    search.addEventListener('input', function () { return rebuild(search.value); });
                    create = el('div', 'crusorai-hub-create');
                    create.append(el('div', 'crusorai-hub-oneshot-label', 'Create a skill'));
                    create.append(el('div', 'crusorai-hub-row-desc', 'No coding needed. Describe the job in your own words and press \u2728 Enhance — or paste an existing skill file and add it directly.'));
                    scopeSel = el('select', 'crusorai-hub-dialog-search');
                    // TrustedHTML: the workbench installs a strict trusted-types policy, so
                    // assigning innerHTML here throws and the Create box renders with no
                    // scope picker (field 2026-10-02: "This document requires 'TrustedHTML'
                    // assignment"). Build the options as nodes instead — no string parsing,
                    // no policy bypass needed.
                    for (_i = 0, _b = [
                        ['user', 'Just me — private, all your projects'],
                        ['workspace', 'This workspace — team, committed to git'],
                    ]; _i < _b.length; _i++) {
                        _c = _b[_i], value = _c[0], label = _c[1];
                        opt = document.createElement('option');
                        opt.value = value;
                        opt.textContent = label;
                        scopeSel.append(opt);
                    }
                    draftIn = el('textarea', 'crusorai-hub-oneshot-input');
                    draftIn.rows = 3;
                    draftIn.placeholder = 'e.g. when I say \u201cship it\u201d, run the tests, build, and give me a go/no-go checklist';
                    contentIn = el('textarea', 'crusorai-hub-oneshot-input');
                    contentIn.rows = 6;
                    contentIn.placeholder = 'The polished skill file appears here (still editable) — or paste an existing one.';
                    enhanceBtn = el('button', 'crusorai-hub-mini', glyph('sparkle'), 'Enhance with AI');
                    enhanceBtn.type = 'button';
                    enhanceBtn.disabled = true;
                    draftIn.addEventListener('input', function () { enhanceBtn.disabled = draftIn.value.trim().length === 0; });
                    addBtn = el('button', 'crusorai-hub-mini is-primary', 'Add skill');
                    addBtn.type = 'button';
                    addBtn.disabled = true;
                    contentIn.addEventListener('input', function () { addBtn.disabled = contentIn.value.trim().length === 0; });
                    createMsg = el('div', 'crusorai-hub-row-error');
                    createMsg.style.display = 'none';
                    say = function (text, isError) {
                        if (isError === void 0) { isError = false; }
                        createMsg.textContent = text;
                        createMsg.style.display = '';
                        createMsg.style.color = isError ? 'var(--vscode-errorForeground, #f48771)' : 'var(--vscode-testing-iconPassed, #3fb950)';
                    };
                    enhanceBtn.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                        var res, err_1;
                        var _a, _b;
                        return __generator(this, function (_c) {
                            switch (_c.label) {
                                case 0:
                                    enhanceBtn.disabled = true;
                                    say('Enhancing\u2026');
                                    _c.label = 1;
                                case 1:
                                    _c.trys.push([1, 3, , 4]);
                                    return [4 /*yield*/, host.oneshotRun('enhance_skill', '', { draft: draftIn.value.trim() })];
                                case 2:
                                    res = _c.sent();
                                    if (res.error) {
                                        say(String(res.error), true);
                                    }
                                    else {
                                        contentIn.value = (_a = res.text) !== null && _a !== void 0 ? _a : '';
                                        addBtn.disabled = contentIn.value.trim().length === 0;
                                        say('Polished. Edit anything you like, then press Add skill.');
                                    }
                                    return [3 /*break*/, 4];
                                case 3:
                                    err_1 = _c.sent();
                                    say(String((_b = err_1.message) !== null && _b !== void 0 ? _b : err_1), true);
                                    return [3 /*break*/, 4];
                                case 4:
                                    enhanceBtn.disabled = draftIn.value.trim().length === 0;
                                    return [2 /*return*/];
                            }
                        });
                    }); });
                    addBtn.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                        var parsed, res, what, where;
                        var _a;
                        return __generator(this, function (_b) {
                            switch (_b.label) {
                                case 0:
                                    parsed = parseSkillMd(contentIn.value);
                                    if (!parsed.instruction) {
                                        say('The skill body is empty.', true);
                                        return [2 /*return*/];
                                    }
                                    if (!parsed.name) {
                                        // no frontmatter name — slug the idea's first words so Add still works
                                        parsed.name = (draftIn.value.trim() || parsed.instruction).toLowerCase()
                                            .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
                                            .split('-').filter(Boolean).slice(0, 4).join('-');
                                    }
                                    addBtn.disabled = true;
                                    say('Adding\u2026');
                                    return [4 /*yield*/, host.skillsHubOp('skill_create', {
                                            name: parsed.name, description: parsed.description,
                                            triggers: parsed.triggers, instruction: parsed.instruction,
                                            scope: scopeSel.value,
                                        })];
                                case 1:
                                    res = _b.sent();
                                    addBtn.disabled = false;
                                    if (res.ok === false) {
                                        say(String((_a = res.error) !== null && _a !== void 0 ? _a : 'could not add the skill'), true);
                                        return [2 /*return*/];
                                    }
                                    what = res.updated ? 'Updated' : 'Added';
                                    where = res.scope === 'workspace'
                                        ? ' — lives in .crusorai/skills/ — COMMIT it so teammates get it on pull'
                                        : '';
                                    say("".concat(what, " \u2713 \u2014 \u201C").concat(res.skill, "\u201D is live (auto-activates on: ").concat(res.triggers.join(', '), ").").concat(where));
                                    draftIn.value = '';
                                    contentIn.value = '';
                                    enhanceBtn.disabled = true;
                                    addBtn.disabled = true;
                                    return [2 /*return*/];
                            }
                        });
                    }); });
                    create.append(scopeSel, draftIn, enhanceBtn, contentIn, addBtn, createMsg);
                    body.replaceChildren(search, list, create);
                    rebuild('');
                    return [2 /*return*/];
            }
        });
    });
}
// Live connector rows come from the engine's `connectors` hub op (probed
// at open time: real MCP servers from the workspace's .crusorai/mcp.json,
// gh/token, browser stack, DB env, terminal). This static set is only the
// FALLBACK for an engine that predates the op — the panel is a pure view,
// the engine owns the truth (field 2026-10-02: "Connector is hardcoded").
var FALLBACK_CONNECTORS = [
    { id: 'mcp', label: 'MCP', glyph: 'plug', desc: 'Model Context Protocol', hint: 'filesystem, github, postgres, puppeteer servers from .crusorai/mcp.json — say "list my MCP servers" in chat' },
    { id: 'github', label: 'GitHub connector', glyph: 'mark-github', desc: 'PRs and issues', hint: 'say "open the PR reviews for this repo" — uses gh / MCP github' },
    { id: 'browser', label: 'Browser connector', glyph: 'browser', desc: 'CDP / puppeteer verification', hint: 'say "verify the UI works" — Crusor drives a real browser and checks the page' },
    { id: 'db', label: 'DB connector', glyph: 'database', desc: 'postgres / sqlite', hint: 'say "query the users table" — guarded read/list tools, mutations ask first' },
    { id: 'terminal', label: 'Terminal connector', glyph: 'terminal', desc: 'guarded shell access', hint: 'run_terminal with approval gates — already wired into every session' },
];
function renderConnectors(body, host) {
    return __awaiter(this, void 0, Promise, function () {
        var rows, live, res, _a, glyphs, list, _loop_3, _i, rows_1, row, mcpRow, attached, attach, chips, _loop_4, _b, attached_1, server, nameIn_1, cmdIn_1, envIn_1, addBtn_1, err_2;
        var _this = this;
        var _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q;
        return __generator(this, function (_r) {
            switch (_r.label) {
                case 0:
                    live = false;
                    _r.label = 1;
                case 1:
                    _r.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, Promise.race([
                            host.skillsHubOp('connectors'),
                            new Promise(function (_, reject) { return setTimeout(function () { return reject(new Error('connectors probe timeout')); }, 3500); }),
                        ])];
                case 2:
                    res = _r.sent();
                    if (res.ok !== false && Array.isArray(res.connectors)) {
                        rows = res.connectors;
                        live = true;
                    }
                    else {
                        rows = FALLBACK_CONNECTORS;
                    }
                    return [3 /*break*/, 4];
                case 3:
                    _a = _r.sent();
                    rows = FALLBACK_CONNECTORS;
                    return [3 /*break*/, 4];
                case 4:
                    glyphs = { mcp: 'plug', github: 'mark-github', browser: 'browser', db: 'database', terminal: 'terminal' };
                    list = el('div', 'crusorai-hub-dialog-list');
                    _loop_3 = function (row) {
                        var id = (_c = row.id) !== null && _c !== void 0 ? _c : '';
                        var fb = FALLBACK_CONNECTORS.find(function (f) { return f.id === id; });
                        list.append(el('div', 'crusorai-hub-row', el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-title', glyph((_e = (_d = row.glyph) !== null && _d !== void 0 ? _d : glyphs[id]) !== null && _e !== void 0 ? _e : 'plug'), el('span', 'crusorai-hub-row-name', (_g = (_f = row.label) !== null && _f !== void 0 ? _f : fb === null || fb === void 0 ? void 0 : fb.label) !== null && _g !== void 0 ? _g : id), el('span', 'crusorai-hub-row-meta', (_j = (_h = row.desc) !== null && _h !== void 0 ? _h : fb === null || fb === void 0 ? void 0 : fb.desc) !== null && _j !== void 0 ? _j : ''), row.status ? el('span', "crusorai-hub-state is-".concat(row.status === 'connected' ? 'connected' : 'setup'), row.status === 'connected' ? 'connected' : 'set up') : undefined), el('div', 'crusorai-hub-row-desc', (_m = (_l = (_k = row.detail) !== null && _k !== void 0 ? _k : row.desc) !== null && _l !== void 0 ? _l : fb === null || fb === void 0 ? void 0 : fb.desc) !== null && _m !== void 0 ? _m : ''), el('div', 'crusorai-hub-row-desc', (_p = (_o = row.hint) !== null && _o !== void 0 ? _o : fb === null || fb === void 0 ? void 0 : fb.hint) !== null && _p !== void 0 ? _p : ''))));
                    };
                    for (_i = 0, rows_1 = rows; _i < rows_1.length; _i++) {
                        row = rows_1[_i];
                        _loop_3(row);
                    }
                    list.append(el('div', 'crusorai-hub-row', el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-desc', live
                        ? 'Status is probed live from this workspace — nothing here is a promise; the agent confirms before acting.'
                        : 'Need more? Skill packs for connectors install from the Marketplace tab.'))));
                    // Custom attach (field 2026-10-02: "Connectors should be custom
                    // attachable"): an MCP server is the one file-configured connector, so
                    // the form writes <workspace>/.crusorai/mcp.json THROUGH the engine
                    // (connector_attach) — the panel never edits files itself. Attached
                    // servers render as chips; a chip's ✕ detaches (connector_detach).
                    if (live) {
                        mcpRow = rows.find(function (r) { return r.id === 'mcp'; });
                        attached = Array.isArray(mcpRow === null || mcpRow === void 0 ? void 0 : mcpRow.servers) ? ((_q = mcpRow.servers) !== null && _q !== void 0 ? _q : []) : [];
                        attach = el('div', 'crusorai-hub-attach');
                        attach.append(el('div', 'crusorai-hub-oneshot-label', 'Attach a connector'));
                        if (attached.length > 0) {
                            chips = el('div', 'crusorai-hub-oneshot-chips');
                            _loop_4 = function (server) {
                                var chip = el('button', 'crusorai-hub-chip', server, glyph('close'));
                                chip.type = 'button';
                                chip.title = "Detach ".concat(server);
                                chip.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                                    return __generator(this, function (_a) {
                                        switch (_a.label) {
                                            case 0:
                                                chip.disabled = true;
                                                return [4 /*yield*/, host.skillsHubOp('connector_detach', { name: server })];
                                            case 1:
                                                _a.sent();
                                                return [4 /*yield*/, renderConnectors(body, host)];
                                            case 2:
                                                _a.sent();
                                                return [2 /*return*/];
                                        }
                                    });
                                }); });
                                chips.append(chip);
                            };
                            for (_b = 0, attached_1 = attached; _b < attached_1.length; _b++) {
                                server = attached_1[_b];
                                _loop_4(server);
                            }
                            attach.append(chips);
                        }
                        attach.append(el('div', 'crusorai-hub-row-desc', 'Adds an MCP server to this workspace\u2019s .crusorai/mcp.json — it connects on the next session. Env vars (tokens, connection strings) are stored exactly as you type them.'));
                        nameIn_1 = el('input', 'crusorai-hub-dialog-search');
                        nameIn_1.placeholder = 'name — e.g. filesystem';
                        cmdIn_1 = el('input', 'crusorai-hub-dialog-search');
                        cmdIn_1.placeholder = 'command — e.g. npx -y @modelcontextprotocol/server-filesystem ~/docs';
                        envIn_1 = el('textarea', 'crusorai-hub-oneshot-input');
                        envIn_1.placeholder = 'env (optional) — one KEY=VALUE per line, e.g. GITHUB_PERSONAL_ACCESS_TOKEN=…';
                        envIn_1.rows = 2;
                        addBtn_1 = el('button', 'crusorai-hub-mini is-primary', 'Attach');
                        addBtn_1.type = 'button';
                        err_2 = el('div', 'crusorai-hub-row-error');
                        err_2.style.display = 'none';
                        addBtn_1.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                            var envLines, res;
                            var _a;
                            return __generator(this, function (_b) {
                                switch (_b.label) {
                                    case 0:
                                        addBtn_1.disabled = true;
                                        err_2.style.display = 'none';
                                        envLines = envIn_1.value.split('\n').map(function (l) { return l.trim(); }).filter(Boolean);
                                        return [4 /*yield*/, host.skillsHubOp('connector_attach', __assign({ name: nameIn_1.value.trim(), command: cmdIn_1.value.trim() }, (envLines.length ? { env: envLines } : {})))];
                                    case 1:
                                        res = _b.sent();
                                        addBtn_1.disabled = false;
                                        if (res.ok === false) {
                                            err_2.textContent = String((_a = res.error) !== null && _a !== void 0 ? _a : 'attach failed');
                                            err_2.style.display = '';
                                            return [2 /*return*/];
                                        }
                                        return [4 /*yield*/, renderConnectors(body, host)];
                                    case 2:
                                        _b.sent(); // re-probe: chip + status refresh
                                        return [2 /*return*/];
                                }
                            });
                        }); });
                        attach.append(nameIn_1, cmdIn_1, envIn_1, addBtn_1, err_2);
                        list.append(attach);
                    }
                    body.replaceChildren(list);
                    return [2 /*return*/];
            }
        });
    });
}
function renderMySkills(body, host) {
    return __awaiter(this, void 0, Promise, function () {
        var res, rows, list, originLabel, _loop_5, _i, rows_2, row;
        var _this = this;
        var _a, _b, _c, _d, _e;
        return __generator(this, function (_f) {
            switch (_f.label) {
                case 0: return [4 /*yield*/, host.skillsHubOp('all')];
                case 1:
                    res = _f.sent();
                    if (res.ok === false) {
                        throw new Error(String((_a = res.error) !== null && _a !== void 0 ? _a : 'could not list skills'));
                    }
                    rows = (Array.isArray(res.skills) ? res.skills : []);
                    list = el('div', 'crusorai-hub-dialog-list');
                    if (rows.length === 0) {
                        list.append(statusRow('No skills installed yet — the Marketplace tab has the curated catalog.'));
                        body.replaceChildren(list);
                        return [2 /*return*/];
                    }
                    originLabel = { hub: 'hub', bundled: 'bundled', user: 'yours', agent: 'agent-learned', project: 'team · committed' };
                    _loop_5 = function (row) {
                        var rowEl = el('div', 'crusorai-hub-row');
                        var main = el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-title', el('span', 'crusorai-hub-row-name', row.name), el('span', 'crusorai-hub-row-meta', "[".concat((_c = originLabel[(_b = row.origin) !== null && _b !== void 0 ? _b : '']) !== null && _c !== void 0 ? _c : row.origin, "] uses: ").concat((_d = row.use_count) !== null && _d !== void 0 ? _d : 0).concat(row.enabled ? '' : ' · disabled'))), el('div', 'crusorai-hub-row-desc', (_e = row.description) !== null && _e !== void 0 ? _e : ''));
                        var actions = el('div', 'crusorai-hub-row-actions');
                        var toggle = el('button', 'crusorai-hub-mini');
                        toggle.type = 'button';
                        toggle.textContent = row.enabled ? 'Disable' : 'Enable';
                        toggle.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                            var res2;
                            var _a;
                            return __generator(this, function (_b) {
                                switch (_b.label) {
                                    case 0:
                                        toggle.disabled = true;
                                        return [4 /*yield*/, host.skillsHubOp('toggle', { name: row.name, enabled: !row.enabled })];
                                    case 1:
                                        res2 = _b.sent();
                                        if (res2.ok === false) {
                                            toggle.disabled = false;
                                            markRowError(rowEl, String((_a = res2.error) !== null && _a !== void 0 ? _a : 'toggle failed'));
                                            return [2 /*return*/];
                                        }
                                        row.enabled = !row.enabled;
                                        return [4 /*yield*/, renderMySkills(body, host)];
                                    case 2:
                                        _b.sent();
                                        return [2 /*return*/];
                                }
                            });
                        }); });
                        actions.append(toggle);
                        if (row.origin === 'hub' || row.origin === 'project') {
                            var remove_1 = el('button', 'crusorai-hub-mini is-danger');
                            remove_1.type = 'button';
                            remove_1.textContent = 'Remove';
                            remove_1.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
                                var res2;
                                var _a;
                                return __generator(this, function (_b) {
                                    switch (_b.label) {
                                        case 0:
                                            remove_1.disabled = true;
                                            return [4 /*yield*/, host.skillsHubOp('remove', { name: row.name })];
                                        case 1:
                                            res2 = _b.sent();
                                            if (res2.ok === false) {
                                                remove_1.disabled = false;
                                                markRowError(rowEl, String((_a = res2.error) !== null && _a !== void 0 ? _a : 'remove failed'));
                                                return [2 /*return*/];
                                            }
                                            return [4 /*yield*/, renderMySkills(body, host)];
                                        case 2:
                                            _b.sent();
                                            return [2 /*return*/];
                                    }
                                });
                            }); });
                            actions.append(remove_1);
                        }
                        rowEl.append(main, actions);
                        list.append(rowEl);
                    };
                    for (_i = 0, rows_2 = rows; _i < rows_2.length; _i++) {
                        row = rows_2[_i];
                        _loop_5(row);
                    }
                    body.replaceChildren(list);
                    return [2 /*return*/];
            }
        });
    });
}
var ONESHOT_TEMPLATES = [
    { id: 'commit_message', label: 'Commit message', prompt: 'from a diff or a description of the change', variable: 'diff' },
    { id: 'summarize', label: 'Summarize', prompt: 'the essentials of a page or document', variable: 'text' },
    { id: 'rename_ideas', label: 'Name ideas', prompt: 'what needs a name?', variable: 'subject' },
];
function renderOneshot(body, host) {
    var _this = this;
    var wrap = el('div', 'crusorai-hub-oneshot');
    var chips = el('div', 'crusorai-hub-oneshot-chips');
    var selected;
    var inputLabel = el('div', 'crusorai-hub-oneshot-label', 'Pick a template.');
    var input = el('textarea', 'crusorai-hub-oneshot-input');
    input.rows = 4;
    input.placeholder = 'Paste the input…';
    var runBtn = el('button', 'crusorai-hub-mini is-primary', 'Run');
    runBtn.type = 'button';
    runBtn.disabled = true;
    var result = el('div', 'crusorai-hub-oneshot-result');
    var copyBtn = el('button', 'crusorai-hub-mini', glyph('copy'), 'Copy');
    copyBtn.type = 'button';
    copyBtn.style.display = 'none';
    copyBtn.addEventListener('click', function () { var _a; host.copyToClipboard((_a = result.textContent) !== null && _a !== void 0 ? _a : ''); });
    var variable = '';
    var _loop_6 = function (template) {
        var chip = el('button', 'crusorai-hub-chip', template.label);
        chip.type = 'button';
        chip.addEventListener('click', function () {
            for (var _i = 0, _a = chips.querySelectorAll('button'); _i < _a.length; _i++) {
                var sibling = _a[_i];
                sibling.classList.remove('is-active');
            }
            chip.classList.add('is-active');
            selected = template.id;
            variable = template.variable;
            inputLabel.textContent = "".concat(template.label, " \u2014 ").concat(template.prompt);
            runBtn.disabled = false;
        });
        chips.append(chip);
    };
    for (var _i = 0, ONESHOT_TEMPLATES_1 = ONESHOT_TEMPLATES; _i < ONESHOT_TEMPLATES_1.length; _i++) {
        var template = ONESHOT_TEMPLATES_1[_i];
        _loop_6(template);
    }
    runBtn.addEventListener('click', function () { return __awaiter(_this, void 0, void 0, function () {
        var value, res;
        var _a;
        var _b;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0:
                    if (!selected) {
                        return [2 /*return*/];
                    }
                    runBtn.disabled = true;
                    runBtn.textContent = 'Thinking…';
                    result.replaceChildren(statusRow('Running one-shot…'));
                    copyBtn.style.display = 'none';
                    value = input.value.trim();
                    return [4 /*yield*/, host.oneshotRun(selected, '', (_a = {}, _a[variable] = value, _a))];
                case 1:
                    res = _c.sent();
                    runBtn.disabled = false;
                    runBtn.textContent = 'Run';
                    if (res.error) {
                        result.replaceChildren(statusRow(String(res.error), true));
                        return [2 /*return*/];
                    }
                    result.replaceChildren(el('pre', 'crusorai-hub-oneshot-output', (_b = res.text) !== null && _b !== void 0 ? _b : ''));
                    copyBtn.style.display = '';
                    return [2 /*return*/];
            }
        });
    }); });
    wrap.append(chips, inputLabel, input, runBtn, result, copyBtn);
    body.replaceChildren(wrap);
}
function markRowError(row, message) {
    var existing = row.querySelector('.crusorai-hub-row-error');
    if (existing) {
        existing.remove();
    }
    row.append(el('div', 'crusorai-hub-row-error', message));
}
