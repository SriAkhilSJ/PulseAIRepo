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
const DIALOG_TIMEOUT_MS = 20000;
function el(tag, className, ...children) {
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
function glyph(name) {
    const span = document.createElement('span');
    span.className = `codicon codicon-${name}`;
    return span;
}
let openDialog;
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
const HUB_DIALOG_CSS = `
.crusorai-hub-backdrop {
	position: fixed; inset: 0; z-index: 2500;
	display: flex; align-items: center; justify-content: center;
	background: rgba(0, 0, 0, 0.45);
	animation: crusorai-hub-fade 120ms ease-out;
}
@keyframes crusorai-hub-fade {
	from { opacity: 0; }
	to { opacity: 1; }
}
.crusorai-hub-dialog {
	position: relative; width: min(560px, calc(100vw - 48px)); max-height: min(520px, calc(100vh - 64px));
	display: flex; flex-direction: column;
	padding: 12px; border-radius: 10px;
	border: 1px solid var(--vscode-panel-border, transparent);
	background: var(--vscode-editorWidget-background, #1f1f1f);
	color: var(--vscode-foreground, #cccccc);
	color-scheme: dark;
	font: inherit;
	box-shadow: 0 10px 34px rgba(0, 0, 0, 0.45);
	animation: crusorai-hub-dialog-in 130ms ease-out;
}
@keyframes crusorai-hub-dialog-in {
	from { opacity: 0; transform: translateY(6px); }
	to { opacity: 1; transform: translateY(0); }
}
.crusorai-hub-dialog-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.crusorai-hub-dialog-heading { font-weight: 700; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.crusorai-hub-dialog-close {
	display: inline-flex; align-items: center; justify-content: center;
	width: 22px; height: 22px; padding: 0; border: none; border-radius: 5px;
	background: transparent; color: var(--vscode-foreground, #cccccc); cursor: pointer;
}
.crusorai-hub-dialog-close:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }
.crusorai-hub-dialog-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 9px 0 2px; }
.crusorai-hub-tab {
	padding: 3px 9px; border: none; border-radius: 5px; cursor: pointer;
	background: transparent; color: var(--vscode-foreground, #cccccc); font: inherit; font-size: .95em;
}
.crusorai-hub-tab:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }
.crusorai-hub-tab.is-active { background: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff); }
.crusorai-hub-dialog-body { margin-top: 6px; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; scrollbar-color: var(--vscode-scrollbarSlider-background, #424242) transparent; }
.crusorai-hub-dialog-search {
	width: 100%; box-sizing: border-box; padding: 6px 8px;
	border-radius: 6px; border: 1px solid var(--vscode-panel-border, transparent);
	background: var(--vscode-input-background, #3c3c3c); color: var(--vscode-input-foreground, #cccccc);
	font: inherit;
}
.crusorai-hub-dialog-list { display: flex; flex-direction: column; gap: 4px; }
.crusorai-hub-status { padding: 8px; opacity: .8; }
.crusorai-hub-status.is-error { color: var(--vscode-errorForeground, #f48771); opacity: 1; }
.crusorai-hub-row {
	display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 4px 8px;
	padding: 7px 8px; border-radius: 6px;
	background: var(--vscode-editor-background, #1f1f1f);
	border: 1px solid var(--vscode-panel-border, transparent);
}
.crusorai-hub-row-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.crusorai-hub-row-title { display: flex; align-items: baseline; gap: .5em; flex-wrap: wrap; }
.crusorai-hub-row-name { font-weight: 600; }
.crusorai-hub-row-meta { font-size: .92em; opacity: .7; }
.crusorai-hub-row-desc { font-size: .92em; opacity: .8; }
.crusorai-hub-row-actions { display: flex; gap: 4px; align-items: center; }
.crusorai-hub-row-error { width: 100%; font-size: .92em; word-break: break-word; color: var(--vscode-errorForeground, #f48771); }
.crusorai-hub-mini {
	padding: 3px 9px; border: none; border-radius: 5px; cursor: pointer;
	background: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff);
	font: inherit; font-size: .95em; white-space: nowrap;
}
.crusorai-hub-mini:hover { background: var(--vscode-button-hoverBackground, #1177bb); }
.crusorai-hub-mini:disabled { opacity: .6; cursor: default; }
.crusorai-hub-mini.is-done { background: transparent; color: var(--vscode-foreground, #cccccc); opacity: .85; }
.crusorai-hub-mini.is-danger { background: transparent; color: var(--vscode-errorForeground, #f48771); }
.crusorai-hub-mini.is-primary { align-self: flex-start; }
.crusorai-hub-attach, .crusorai-hub-create { display: flex; flex-direction: column; gap: 6px; padding-top: 8px; border-top: 1px solid var(--vscode-panel-border, transparent); }
select.crusorai-hub-dialog-search { height: 30px; padding: 4px 8px; }
.crusorai-hub-create { margin-top: 6px; }
.crusorai-hub-state {
	display: inline-flex; align-items: center; gap: .4em; margin-left: auto;
	padding: 1px 8px; border-radius: 20px; font-size: .92em; white-space: nowrap;
}
.crusorai-hub-state::before { content: ''; width: .6em; height: .6em; border-radius: 50%; background: currentColor; }
.crusorai-hub-state.is-connected { color: var(--vscode-testing-iconPassed, #3fb950); background: rgba(63, 185, 80, 0.12); }
.crusorai-hub-state.is-setup { color: var(--vscode-editorWarning-foreground, #d29922); background: rgba(210, 153, 34, 0.12); }
.crusorai-hub-oneshot { display: flex; flex-direction: column; gap: 7px; }
.crusorai-hub-oneshot-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.crusorai-hub-chip {
	padding: 3px 9px; border: 1px solid var(--vscode-panel-border, transparent); border-radius: 20px;
	background: transparent; color: var(--vscode-foreground, #cccccc); cursor: pointer; font: inherit; font-size: .95em;
}
.crusorai-hub-chip:hover { background: var(--vscode-list-hoverBackground, #2a2d2e); }
.crusorai-hub-chip.is-active { background: var(--vscode-button-background, #0e639c); color: var(--vscode-button-foreground, #ffffff); border-color: transparent; }
.crusorai-hub-oneshot-label { font-weight: 600; }
.crusorai-hub-oneshot-input {
	width: 100%; box-sizing: border-box; padding: 6px 8px; resize: vertical;
	border-radius: 6px; border: 1px solid var(--vscode-panel-border, transparent);
	background: var(--vscode-input-background, #3c3c3c); color: var(--vscode-input-foreground, #cccccc);
	font: inherit;
}
.crusorai-hub-oneshot-result:empty { display: none; }
.crusorai-hub-oneshot-output {
	margin: 0; padding: 8px; border-radius: 6px; white-space: pre-wrap; word-break: break-word;
	background: var(--vscode-editor-background, rgba(127, 127, 127, 0.08));
	border: 1px solid var(--vscode-panel-border, transparent);
	font: inherit; font-size: .95em; max-height: 160px; overflow-y: auto;
}
`;
const HUB_STYLE_ID = 'crusorai-hub-dialog-styles';
function ensureHubDialogStyles() {
    if (document.getElementById(HUB_STYLE_ID)) {
        return;
    }
    const style = document.createElement('style');
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
const THEME_VARS = [
    'foreground', 'editorWidget-background', 'editor-background', 'panel-border',
    'input-background', 'input-foreground', 'button-background', 'button-foreground',
    'button-hoverBackground', 'list-hoverBackground', 'errorForeground',
];
function inheritPanelTheme(root, anchor) {
    const panel = getComputedStyle(anchor);
    for (const name of THEME_VARS) {
        const value = panel.getPropertyValue(`--vscode-${name}`).trim();
        if (value) {
            root.style.setProperty(`--vscode-${name}`, value);
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
    openDialog?.close();
}
export function openHubDialog(host, anchor, tab = 'marketplace') {
    closeOpenDialog();
    if (typeof host.skillsHubOp !== 'function') {
        return; // host predates the hub — nothing to show
    }
    ensureHubDialogStyles();
    const titleBar = el('div', 'crusorai-hub-dialog-title', el('span', 'crusorai-hub-dialog-heading', 'Crusor'));
    const body = el('div', 'crusorai-hub-dialog-body');
    const closeBtn = el('button', 'crusorai-hub-dialog-close', glyph('close'));
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Close');
    titleBar.append(closeBtn);
    // rev 7 (owner: "spawn a dialog box rather than menu bar … pops in
    // fork"): the card opens as a CENTERED MODAL over the whole pane —
    // dimmed backdrop, four tabs in the card — instead of a small popup
    // pinned above the + button. It still mounts on document.body
    // (survives composer repaints) and still inherits the panel theme
    // from the anchor (+ button lives inside the themed subtree).
    const backdrop = el('div', 'crusorai-hub-backdrop');
    const root = el('div', 'crusorai-hub-dialog', titleBar, body);
    inheritPanelTheme(backdrop, anchor);
    const close = () => {
        root.remove();
        backdrop.remove();
        document.removeEventListener('pointerdown', away, true);
        document.removeEventListener('keydown', onEscape, true);
        if (openDialog?.root === root) {
            openDialog = undefined;
        }
    };
    const away = (event) => {
        if (event.target === backdrop) {
            close();
        } // click on the dim, not the card
    };
    const onEscape = (event) => {
        if (event.key === 'Escape') {
            close();
        }
    };
    closeBtn.addEventListener('click', close);
    document.addEventListener('pointerdown', away, true);
    document.addEventListener('keydown', onEscape, true);
    backdrop.append(root);
    document.body.append(backdrop);
    openDialog = { root, close };
    const tabs = [
        { id: 'marketplace', label: 'Marketplace' },
        { id: 'connectors', label: 'Connectors' },
        { id: 'myskills', label: 'My Skills' },
        { id: 'oneshot', label: 'One-Shot' },
    ];
    const tabRow = el('div', 'crusorai-hub-dialog-tabs');
    for (const entry of tabs) {
        const btn = el('button', entry.id === tab ? 'crusorai-hub-tab is-active' : 'crusorai-hub-tab', entry.label);
        btn.type = 'button';
        btn.addEventListener('click', () => {
            for (const sibling of tabRow.querySelectorAll('button')) {
                sibling.classList.remove('is-active');
            }
            btn.classList.add('is-active');
            render(body, host, entry.id);
        });
        tabRow.append(btn);
    }
    titleBar.after(tabRow);
    const heading = titleBar.querySelector('.crusorai-hub-dialog-heading');
    const titles = {
        marketplace: 'Marketplace — install skills',
        connectors: 'Connectors — beyond the workspace',
        myskills: 'My Skills — everything installed',
        oneshot: 'One-Shot — quick jobs',
    };
    const setHeading = (key) => { heading.textContent = titles[key]; };
    const origRender = render;
    // keep the heading in sync with tab switches
    tabRow.addEventListener('click', (event) => {
        const btn = event.target.closest('button');
        if (!btn) {
            return;
        }
        const index = Array.from(tabRow.children).indexOf(btn);
        setHeading(tabs[index]?.id ?? 'marketplace');
    });
    void origRender; // (render is used directly below)
    setHeading(tab);
    render(body, host, tab);
}
function statusRow(message, isError = false) {
    return el('div', isError ? 'crusorai-hub-status is-error' : 'crusorai-hub-status', message);
}
async function render(body, host, tab) {
    body.replaceChildren(statusRow('Loading…'));
    try {
        switch (tab) {
            case 'marketplace':
                await renderMarketplace(body, host);
                break;
            case 'connectors':
                await renderConnectors(body, host);
                break;
            case 'myskills':
                await renderMySkills(body, host);
                break;
            case 'oneshot':
                renderOneshot(body, host);
                break;
        }
    }
    catch (error) {
        body.replaceChildren(statusRow(String(error.message ?? error), true));
    }
}
// The Create box's "Add skill" accepts either the Enhance output or a
// pasted skill file: pull name/description/triggers out of the YAML
// frontmatter when present, else treat the whole text as the body.
function parseSkillMd(text) {
    const m = text.trim().match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
    if (!m) {
        return { name: '', description: '', triggers: [], instruction: text.trim() };
    }
    const meta = m[1];
    const pick = (key) => {
        const mm = meta.match(new RegExp(`^${key}:\s*(.+)$`, 'm'));
        return mm ? mm[1].trim().replace(/^["']|["']$/g, '') : '';
    };
    return {
        name: pick('name'),
        description: pick('description'),
        triggers: pick('triggers').split(',').map(t => t.trim()).filter(Boolean),
        instruction: m[2].trim(),
    };
}
async function renderMarketplace(body, host) {
    const [catalogRes, installedRes] = await Promise.all([
        host.skillsHubOp('catalog'),
        host.skillsHubOp('list'),
    ]);
    if (catalogRes.ok === false) {
        throw new Error(String(catalogRes.error ?? 'catalog unavailable'));
    }
    const entries = (Array.isArray(catalogRes.results) ? catalogRes.results : []);
    const installedRows = (installedRes.ok !== false && Array.isArray(installedRes.installed))
        ? installedRes.installed : [];
    const installedKeys = new Set(installedRows.map(row => `${row.repo}:${row.subdir}`));
    const updateKeys = new Set(installedRows.filter(row => row.update_available).map(row => `${row.repo}:${row.subdir}`));
    const search = el('input', 'crusorai-hub-dialog-search');
    search.type = 'text';
    search.placeholder = 'Search the catalog…';
    const list = el('div', 'crusorai-hub-dialog-list');
    const rebuild = (query) => {
        list.replaceChildren();
        const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
        const matches = entries.filter(entry => {
            const hay = `${entry.name} ${entry.category ?? ''} ${entry.description ?? ''}`.toLowerCase();
            return tokens.every(token => hay.includes(token));
        });
        if (matches.length === 0) {
            list.append(statusRow('No catalog match. Install any GitHub repo from chat: hub_install("owner/repo@<sha>").'));
            return;
        }
        for (const entry of matches) {
            const key = `${entry.repo}:${entry.subdir}`;
            const isInstalled = installedKeys.has(key);
            const row = el('div', 'crusorai-hub-row');
            const left = el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-title', el('span', 'crusorai-hub-row-name', entry.name), el('span', 'crusorai-hub-row-meta', `[${entry.category || 'general'}] ${entry.trust ?? ''}`.trim())), el('div', 'crusorai-hub-row-desc', entry.description ?? ''));
            const action = el('button', isInstalled ? 'crusorai-hub-mini is-done' : 'crusorai-hub-mini');
            action.type = 'button';
            if (isInstalled) {
                action.textContent = updateKeys.has(key) ? 'Update' : 'Installed ✓';
                action.disabled = !updateKeys.has(key);
                action.addEventListener('click', async () => {
                    action.disabled = true;
                    action.textContent = 'Updating…';
                    const res = await host.skillsHubOp('update', { name: entry.name });
                    await refresh();
                    if (res.ok === false) {
                        markRowError(row, String(res.error ?? 'update failed'));
                    }
                });
            }
            else {
                action.textContent = 'Install';
                action.addEventListener('click', async () => {
                    action.disabled = true;
                    action.textContent = 'Installing…';
                    const res = await host.skillsHubOp('install', { source: entry.name });
                    if (res.ok === false) {
                        action.disabled = false;
                        action.textContent = 'Install';
                        markRowError(row, String(res.error ?? 'install failed'));
                        return;
                    }
                    installedKeys.add(key);
                    action.className = 'crusorai-hub-mini is-done';
                    action.textContent = 'Installed ✓';
                    action.disabled = true;
                    const warnings = res.warnings ?? [];
                    if (warnings.length > 0) {
                        markRowError(row, `Installed, with warnings: ${warnings.join('; ')}`);
                    }
                });
            }
            row.append(left, action);
            list.append(row);
        }
    };
    const refresh = async () => {
        const [cat2, inst2] = await Promise.all([host.skillsHubOp('catalog'), host.skillsHubOp('list')]);
        if (cat2.ok !== false) {
            const nextEntries = (Array.isArray(cat2.results) ? cat2.results : []);
            const nextInstalled = (inst2.ok !== false && Array.isArray(inst2.installed))
                ? inst2.installed : [];
            entries.length = 0;
            entries.push(...nextEntries);
            installedKeys.clear();
            nextInstalled.forEach(row => installedKeys.add(`${row.repo}:${row.subdir}`));
            rebuild(search.value);
        }
    };
    search.addEventListener('input', () => rebuild(search.value));
    // Create a skill (field 2026-10-02, owner: non-coders fear writing
    // skill files — give them ONE box and an Enhance button). Rough words
    // in -> Enhance (the engine's enhance_skill one-shot) -> a proper
    // skill file lands in the editable box -> Add skill pushes it through
    // the engine's skill_create op. The engine normalizes the name,
    // derives triggers when missing, and owns the store — the panel never
    // writes files. Lives OUTSIDE the search list so it survives rebuilds.
    const create = el('div', 'crusorai-hub-create');
    create.append(el('div', 'crusorai-hub-oneshot-label', 'Create a skill'));
    create.append(el('div', 'crusorai-hub-row-desc', 'No coding needed. Describe the job in your own words and press \u2728 Enhance — or paste an existing skill file and add it directly.'));
    const scopeSel = el('select', 'crusorai-hub-dialog-search');
    scopeSel.innerHTML = '<option value="user">Just me — private, all your projects</option>'
        + '<option value="workspace">This workspace — team, committed to git</option>';
    const draftIn = el('textarea', 'crusorai-hub-oneshot-input');
    draftIn.rows = 3;
    draftIn.placeholder = 'e.g. when I say \u201cship it\u201d, run the tests, build, and give me a go/no-go checklist';
    const contentIn = el('textarea', 'crusorai-hub-oneshot-input');
    contentIn.rows = 6;
    contentIn.placeholder = 'The polished skill file appears here (still editable) — or paste an existing one.';
    const enhanceBtn = el('button', 'crusorai-hub-mini', glyph('sparkle'), 'Enhance with AI');
    enhanceBtn.type = 'button';
    enhanceBtn.disabled = true;
    draftIn.addEventListener('input', () => { enhanceBtn.disabled = draftIn.value.trim().length === 0; });
    const addBtn = el('button', 'crusorai-hub-mini is-primary', 'Add skill');
    addBtn.type = 'button';
    addBtn.disabled = true;
    contentIn.addEventListener('input', () => { addBtn.disabled = contentIn.value.trim().length === 0; });
    const createMsg = el('div', 'crusorai-hub-row-error');
    createMsg.style.display = 'none';
    const say = (text, isError = false) => {
        createMsg.textContent = text;
        createMsg.style.display = '';
        createMsg.style.color = isError ? 'var(--vscode-errorForeground, #f48771)' : 'var(--vscode-testing-iconPassed, #3fb950)';
    };
    enhanceBtn.addEventListener('click', async () => {
        enhanceBtn.disabled = true;
        say('Enhancing\u2026');
        try {
            const res = await host.oneshotRun('enhance_skill', '', { draft: draftIn.value.trim() });
            if (res.error) {
                say(String(res.error), true);
            }
            else {
                contentIn.value = res.text ?? '';
                addBtn.disabled = contentIn.value.trim().length === 0;
                say('Polished. Edit anything you like, then press Add skill.');
            }
        }
        catch (err) {
            say(String(err.message ?? err), true);
        }
        enhanceBtn.disabled = draftIn.value.trim().length === 0;
    });
    addBtn.addEventListener('click', async () => {
        const parsed = parseSkillMd(contentIn.value);
        if (!parsed.instruction) {
            say('The skill body is empty.', true);
            return;
        }
        addBtn.disabled = true;
        say('Adding\u2026');
        const res = await host.skillsHubOp('skill_create', {
            name: parsed.name, description: parsed.description,
            triggers: parsed.triggers, instruction: parsed.instruction,
            scope: scopeSel.value,
        });
        addBtn.disabled = false;
        if (res.ok === false) {
            say(String(res.error ?? 'could not add the skill'), true);
            return;
        }
        const what = res.updated ? 'Updated' : 'Added';
        const where = res.scope === 'workspace'
            ? ' — lives in .crusorai/skills/ — COMMIT it so teammates get it on pull'
            : '';
        say(`${what} \u2713 \u2014 \u201c${res.skill}\u201d is live (auto-activates on: ${res.triggers.join(', ')}).${where}`);
        draftIn.value = '';
        contentIn.value = '';
        enhanceBtn.disabled = true;
        addBtn.disabled = true;
    });
    create.append(scopeSel, draftIn, enhanceBtn, contentIn, addBtn, createMsg);
    body.replaceChildren(search, list, create);
    rebuild('');
}
// Live connector rows come from the engine's `connectors` hub op (probed
// at open time: real MCP servers from the workspace's .crusorai/mcp.json,
// gh/token, browser stack, DB env, terminal). This static set is only the
// FALLBACK for an engine that predates the op — the panel is a pure view,
// the engine owns the truth (field 2026-10-02: "Connector is hardcoded").
const FALLBACK_CONNECTORS = [
    { id: 'mcp', label: 'MCP', glyph: 'plug', desc: 'Model Context Protocol', hint: 'filesystem, github, postgres, puppeteer servers from .crusorai/mcp.json — say "list my MCP servers" in chat' },
    { id: 'github', label: 'GitHub connector', glyph: 'mark-github', desc: 'PRs and issues', hint: 'say "open the PR reviews for this repo" — uses gh / MCP github' },
    { id: 'browser', label: 'Browser connector', glyph: 'browser', desc: 'CDP / puppeteer verification', hint: 'say "verify the UI works" — Crusor drives a real browser and checks the page' },
    { id: 'db', label: 'DB connector', glyph: 'database', desc: 'postgres / sqlite', hint: 'say "query the users table" — guarded read/list tools, mutations ask first' },
    { id: 'terminal', label: 'Terminal connector', glyph: 'terminal', desc: 'guarded shell access', hint: 'run_terminal with approval gates — already wired into every session' },
];
async function renderConnectors(body, host) {
    let rows;
    let live = false;
    try {
        // short race: an old engine never answers this op — fall back after
        // 3.5s instead of spinning to the 12s transport timeout.
        const res = await Promise.race([
            host.skillsHubOp('connectors'),
            new Promise((_, reject) => setTimeout(() => reject(new Error('connectors probe timeout')), 3500)),
        ]);
        if (res.ok !== false && Array.isArray(res.connectors)) {
            rows = res.connectors;
            live = true;
        }
        else {
            rows = FALLBACK_CONNECTORS;
        }
    }
    catch {
        rows = FALLBACK_CONNECTORS;
    }
    const glyphs = { mcp: 'plug', github: 'mark-github', browser: 'browser', db: 'database', terminal: 'terminal' };
    const list = el('div', 'crusorai-hub-dialog-list');
    for (const row of rows) {
        const id = row.id ?? '';
        const fb = FALLBACK_CONNECTORS.find(f => f.id === id);
        list.append(el('div', 'crusorai-hub-row', el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-title', glyph(row.glyph ?? glyphs[id] ?? 'plug'), el('span', 'crusorai-hub-row-name', row.label ?? fb?.label ?? id), el('span', 'crusorai-hub-row-meta', row.desc ?? fb?.desc ?? ''), row.status ? el('span', `crusorai-hub-state is-${row.status === 'connected' ? 'connected' : 'setup'}`, row.status === 'connected' ? 'connected' : 'set up') : undefined), el('div', 'crusorai-hub-row-desc', row.detail ?? row.desc ?? fb?.desc ?? ''), el('div', 'crusorai-hub-row-desc', row.hint ?? fb?.hint ?? ''))));
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
        const mcpRow = rows.find(r => r.id === 'mcp');
        const attached = Array.isArray(mcpRow?.servers) ? (mcpRow.servers ?? []) : [];
        const attach = el('div', 'crusorai-hub-attach');
        attach.append(el('div', 'crusorai-hub-oneshot-label', 'Attach a connector'));
        if (attached.length > 0) {
            const chips = el('div', 'crusorai-hub-oneshot-chips');
            for (const server of attached) {
                const chip = el('button', 'crusorai-hub-chip', server, glyph('close'));
                chip.type = 'button';
                chip.title = `Detach ${server}`;
                chip.addEventListener('click', async () => {
                    chip.disabled = true;
                    await host.skillsHubOp('connector_detach', { name: server });
                    await renderConnectors(body, host);
                });
                chips.append(chip);
            }
            attach.append(chips);
        }
        attach.append(el('div', 'crusorai-hub-row-desc', 'Adds an MCP server to this workspace\u2019s .crusorai/mcp.json — it connects on the next session.'));
        const nameIn = el('input', 'crusorai-hub-dialog-search');
        nameIn.placeholder = 'name — e.g. filesystem';
        const cmdIn = el('input', 'crusorai-hub-dialog-search');
        cmdIn.placeholder = 'command — e.g. npx -y @modelcontextprotocol/server-filesystem ~/docs';
        const addBtn = el('button', 'crusorai-hub-mini is-primary', 'Attach');
        addBtn.type = 'button';
        const err = el('div', 'crusorai-hub-row-error');
        err.style.display = 'none';
        addBtn.addEventListener('click', async () => {
            addBtn.disabled = true;
            err.style.display = 'none';
            const parts = cmdIn.value.trim().split(/\s+/).filter(Boolean);
            const res = await host.skillsHubOp('connector_attach', { name: nameIn.value.trim(), command: parts[0] ?? '', args: parts.slice(1) });
            addBtn.disabled = false;
            if (res.ok === false) {
                err.textContent = String(res.error ?? 'attach failed');
                err.style.display = '';
                return;
            }
            await renderConnectors(body, host); // re-probe: chip + status refresh
        });
        attach.append(nameIn, cmdIn, addBtn, err);
        list.append(attach);
    }
    body.replaceChildren(list);
}
async function renderMySkills(body, host) {
    const res = await host.skillsHubOp('all');
    if (res.ok === false) {
        throw new Error(String(res.error ?? 'could not list skills'));
    }
    const rows = (Array.isArray(res.skills) ? res.skills : []);
    const list = el('div', 'crusorai-hub-dialog-list');
    if (rows.length === 0) {
        list.append(statusRow('No skills installed yet — the Marketplace tab has the curated catalog.'));
        body.replaceChildren(list);
        return;
    }
    const originLabel = { hub: 'hub', bundled: 'bundled', user: 'yours', agent: 'agent-learned', project: 'team · committed' };
    for (const row of rows) {
        const rowEl = el('div', 'crusorai-hub-row');
        const main = el('div', 'crusorai-hub-row-main', el('div', 'crusorai-hub-row-title', el('span', 'crusorai-hub-row-name', row.name), el('span', 'crusorai-hub-row-meta', `[${originLabel[row.origin ?? ''] ?? row.origin}] uses: ${row.use_count ?? 0}${row.enabled ? '' : ' · disabled'}`)), el('div', 'crusorai-hub-row-desc', row.description ?? ''));
        const actions = el('div', 'crusorai-hub-row-actions');
        const toggle = el('button', 'crusorai-hub-mini');
        toggle.type = 'button';
        toggle.textContent = row.enabled ? 'Disable' : 'Enable';
        toggle.addEventListener('click', async () => {
            toggle.disabled = true;
            const res2 = await host.skillsHubOp('toggle', { name: row.name, enabled: !row.enabled });
            if (res2.ok === false) {
                toggle.disabled = false;
                markRowError(rowEl, String(res2.error ?? 'toggle failed'));
                return;
            }
            row.enabled = !row.enabled;
            await renderMySkills(body, host);
        });
        actions.append(toggle);
        if (row.origin === 'hub' || row.origin === 'project') {
            const remove = el('button', 'crusorai-hub-mini is-danger');
            remove.type = 'button';
            remove.textContent = 'Remove';
            remove.addEventListener('click', async () => {
                remove.disabled = true;
                const res2 = await host.skillsHubOp('remove', { name: row.name });
                if (res2.ok === false) {
                    remove.disabled = false;
                    markRowError(rowEl, String(res2.error ?? 'remove failed'));
                    return;
                }
                await renderMySkills(body, host);
            });
            actions.append(remove);
        }
        rowEl.append(main, actions);
        list.append(rowEl);
    }
    body.replaceChildren(list);
}
const ONESHOT_TEMPLATES = [
    { id: 'commit_message', label: 'Commit message', prompt: 'from a diff or a description of the change', variable: 'diff' },
    { id: 'summarize', label: 'Summarize', prompt: 'the essentials of a page or document', variable: 'text' },
    { id: 'rename_ideas', label: 'Name ideas', prompt: 'what needs a name?', variable: 'subject' },
];
function renderOneshot(body, host) {
    const wrap = el('div', 'crusorai-hub-oneshot');
    const chips = el('div', 'crusorai-hub-oneshot-chips');
    let selected;
    const inputLabel = el('div', 'crusorai-hub-oneshot-label', 'Pick a template.');
    const input = el('textarea', 'crusorai-hub-oneshot-input');
    input.rows = 4;
    input.placeholder = 'Paste the input…';
    const runBtn = el('button', 'crusorai-hub-mini is-primary', 'Run');
    runBtn.type = 'button';
    runBtn.disabled = true;
    const result = el('div', 'crusorai-hub-oneshot-result');
    const copyBtn = el('button', 'crusorai-hub-mini', glyph('copy'), 'Copy');
    copyBtn.type = 'button';
    copyBtn.style.display = 'none';
    copyBtn.addEventListener('click', () => { host.copyToClipboard(result.textContent ?? ''); });
    let variable = '';
    for (const template of ONESHOT_TEMPLATES) {
        const chip = el('button', 'crusorai-hub-chip', template.label);
        chip.type = 'button';
        chip.addEventListener('click', () => {
            for (const sibling of chips.querySelectorAll('button')) {
                sibling.classList.remove('is-active');
            }
            chip.classList.add('is-active');
            selected = template.id;
            variable = template.variable;
            inputLabel.textContent = `${template.label} — ${template.prompt}`;
            runBtn.disabled = false;
        });
        chips.append(chip);
    }
    runBtn.addEventListener('click', async () => {
        if (!selected) {
            return;
        }
        runBtn.disabled = true;
        runBtn.textContent = 'Thinking…';
        result.replaceChildren(statusRow('Running one-shot…'));
        copyBtn.style.display = 'none';
        const value = input.value.trim();
        const res = await host.oneshotRun(selected, '', { [variable]: value });
        runBtn.disabled = false;
        runBtn.textContent = 'Run';
        if (res.error) {
            result.replaceChildren(statusRow(String(res.error), true));
            return;
        }
        result.replaceChildren(el('pre', 'crusorai-hub-oneshot-output', res.text ?? ''));
        copyBtn.style.display = '';
    });
    wrap.append(chips, inputLabel, input, runBtn, result, copyBtn);
    body.replaceChildren(wrap);
}
function markRowError(row, message) {
    const existing = row.querySelector('.crusorai-hub-row-error');
    if (existing) {
        existing.remove();
    }
    row.append(el('div', 'crusorai-hub-row-error', message));
}
