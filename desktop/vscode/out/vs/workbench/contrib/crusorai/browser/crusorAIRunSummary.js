/*---------------------------------------------------------------------------------------------
 * Activity grouping + the summary clause machinery. The clause machinery (verbs,
 * counting) is mirrored from the CopilotKit webview's `hermes-ui/model/run-summary.ts`
 * and still narrates the session list; the GROUPING law changed on founder order
 * 2026-10-17 to OpenCode's: consecutive same-kind calls register as one dropdown
 * (their CurrentReadToolGroup / CurrentFileToolGroup / same-name repeats in
 * third-party/opencode/session-ui), never one mixed sentence. Kept in its own
 * module with no DOM imports so the rule can be executed by a test instead of
 * only grep-checked — see src/tests/test_hermes_run_summary_parity.py.
 *--------------------------------------------------------------------------------------------*/
/** Clause order is fixed so the same run always reads the same way. */
const CATEGORY_ORDER = ['edit', 'explore', 'run', 'delegate', 'other'];
const CATEGORY_COPY = {
    delegate: { noun: ['task', 'tasks'], past: 'Delegated', present: 'Delegating' },
    edit: { noun: ['file', 'files'], past: 'Edited', present: 'Editing' },
    explore: { noun: ['file', 'files'], past: 'Explored', present: 'Exploring' },
    other: { noun: ['tool', 'tools'], past: 'Used', present: 'Using' },
    run: { noun: ['command', 'commands'], past: 'Ran', present: 'Running' },
};
/** The webview's tables, copied rather than re-derived: names Crusor actually registers. */
const FILE_EDIT_TOOL_NAMES = new Set(['write_file', 'edit_file', 'copy_file']);
const CARD_TOOL_NAMES = new Set(['ask_user', 'display_crusor_task', 'invoke_host_capability', 'delegate_to_subagent', 'delegate_to_subagent_batch']);
const SILENT_TOOL_NAMES = new Set(['think']);
const EXPLORE_TOOLS = new Set([
    'list_files', 'read_file', 'search_code', 'session_search', 'web_fetch', 'web_search',
    'discover_host_capabilities', 'read_terminal_output', 'check_terminal',
    'list_terminal_processes', 'typecheck_workspace', 'verify_ui_routes', 'verify_ui_workspace',
]);
export function isFileEditTool(toolName) {
    return FILE_EDIT_TOOL_NAMES.has(toolName);
}
/** Tools that draw their own surface and must never fold into a summary: the thing on
 *  screen IS the point (a diff, a question, a sub-agent card). */
export function isCardTool(toolName) {
    return CARD_TOOL_NAMES.has(toolName) || isFileEditTool(toolName);
}
/** Renders nothing of its own -- `think` receipts already surface as reasoning. */
export function isSilentTool(toolName) {
    return SILENT_TOOL_NAMES.has(toolName);
}
export function runCategory(toolName) {
    const name = toolName ?? '';
    if (isFileEditTool(name)) {
        return 'edit';
    }
    if (name === 'run_terminal' || name === 'execute_code' || name.startsWith('start_terminal')) {
        return 'run';
    }
    if (name.startsWith('delegate_to_subagent')) {
        return 'delegate';
    }
    if (EXPLORE_TOOLS.has(name) || name.startsWith('browser_')) {
        return 'explore';
    }
    return 'other';
}
/** How a tool reads while it is happening -- "Editing", "Exploring", not "Reading". */
export function toolPresentVerb(toolName) {
    return CATEGORY_COPY[runCategory(toolName)].present;
}
export function categoryCopy(category) {
    return CATEGORY_COPY[category];
}
function isPending(tool) {
    return tool.result === undefined;
}
/**
 * A target has to fit on one grey line inside a 380px panel: collapsed whitespace and a
 * hard clamp, the same shape the webview applies (`compactPreview` / `timelinePreview`).
 * Clamped for *display* only -- the row behind it still carries the whole command.
 */
export function compactTarget(value, max = 48) {
    if (!value) {
        return undefined;
    }
    const collapsed = value.replace(/\s+/g, ' ').trim();
    if (!collapsed.length) {
        return undefined;
    }
    return collapsed.length <= max ? collapsed : `${collapsed.slice(0, max - 1).trimEnd()}\u2026`;
}
function lowerFirst(text) {
    return text.charAt(0).toLowerCase() + text.slice(1);
}
/**
 * The grouping law (OpenCode's, founder 2026-10-17, replacing the
 * hermes mixed-run fold for the transcript): consecutive calls
 * carrying the same group key register as ONE dropdown; different
 * kinds never mix; a lone call stands alone as a bare row. The
 * key is the caller's to assign — explore reads/searches, one key
 * per edited file, one per repeated tool name — exactly like
 * summarizeToolRun's injected targetOf. A null key means "draws
 * its own surface" (a diff card, a question, a process line): it
 * renders singly and breaks any group in progress. Order is
 * preserved rather than sorted: read, edit, read again shows the
 * sequence it happened in.
 */
export function splitActivityGroups(tools, keyOf) {
    const items = [];
    let current = null;
    const flush = () => {
        if (!current) {
            return;
        }
        if (current.tools.length === 1) {
            items.push({ kind: 'single', tool: current.tools[0] });
        }
        else {
            items.push(current);
        }
        current = null;
    };
    for (const tool of tools) {
        const key = tool.name ? keyOf(tool) : null;
        if (key === null) {
            flush();
            items.push({ kind: 'single', tool });
            continue;
        }
        if (current && current.groupKey === key) {
            current.tools.push(tool);
            continue;
        }
        flush();
        current = { kind: 'group', groupKey: key, tools: [tool] };
    }
    flush();
    return items;
}
function clause(category, tools, live, target) {
    const copy = CATEGORY_COPY[category];
    const verb = live ? copy.present : copy.past;
    if (target && tools.length === 1 && (live || category !== 'run')) {
        return `${verb} ${target}`;
    }
    return `${verb} ${tools.length} ${copy.noun[tools.length === 1 ? 0 : 1]}`;
}
/**
 * Collapse a run into the one grey line that stands in for it -- "Explored 3 files,
 * ran 5 commands". While the run is live, the category holding its most recent
 * unfinished call speaks in the present tense. `live` is the caller's to say: a call
 * left without a result by an ended turn must still read as finished.
 *
 * `targetOf` is injected because the fork's target extraction lives with the renderer
 * (it reads per-family payloads); the clause rules -- when a target earns the space
 * and when counting wins -- are the ones shared with the webview.
 */
export function summarizeToolRun(tools, live, targetOf) {
    if (!tools.length) {
        return '';
    }
    const narrating = live ? (tools.find(isPending) ?? tools.at(-1)) : undefined;
    const liveCategory = narrating ? runCategory(narrating.name) : null;
    const byCategory = new Map();
    for (const tool of tools) {
        const category = runCategory(tool.name);
        const group = byCategory.get(category);
        if (group) {
            group.push(tool);
        }
        else {
            byCategory.set(category, [tool]);
        }
    }
    const clauses = [];
    for (const category of CATEGORY_ORDER) {
        const group = byCategory.get(category);
        if (!group) {
            continue;
        }
        clauses.push(clause(category, group, category === liveCategory, group.length === 1 ? targetOf(group[0]) : undefined));
    }
    return clauses.map((text, index) => (index === 0 ? text : lowerFirst(text))).join(', ');
}
