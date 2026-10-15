/*---------------------------------------------------------------------------------------------
 * A2UI Catalog v1 surface manager (native pane). The agent sends surface
 * operations (createSurface / updateComponents / updateDataModel /
 * deleteSurface, A2UI v0.9 shapes); this module renders them from a FIXED
 * component catalog. No arbitrary HTML, styles, or scripts ever cross the
 * wire: unknown operations, components, and actions are dropped and logged,
 * never thrown — a malformed surface must not take the transcript down.
 *
 * Data binding follows A2UI semantics: a value shaped {path: "/a/b"} reads
 * the surface data model by JSON Pointer; anything else is a literal.
 *
 * Plan: docs/DESIGN/AGUI_A2UI_PLAN.md §4 (Phase 2). The envelope rides
 * tool_call_end.result as {"a2ui_operations": [...]} — no protocol bump.
 *--------------------------------------------------------------------------------------------*/
/** The fixed Catalog v1. The agent can name ONLY these component types. */
export const CRUSOR_A2UI_CATALOG_V1 = [
    'Card', 'Column', 'Row', 'Text', 'Diff', 'TerminalOutput',
    'PlanList', 'Receipt', 'QuestionForm', 'ApprovalBar', 'Image', 'Button',
];
/** Size caps (guardrail, plan §6): a surface is data, not a document. */
export const MAX_A2UI_OPS = 64;
export const MAX_A2UI_COMPONENTS = 64;
export const MAX_A2UI_TEXT = 4000;
export const MAX_A2UI_STEPS = 50;
function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function boundText(value, max = MAX_A2UI_TEXT) {
    const text = typeof value === 'string' ? value : value === undefined ? '' : String(value);
    return text.length <= max ? text : `${text.slice(0, max)}…`;
}
/** Extract the A2UI envelope from a tool result (object or JSON string). */
export function parseCrusorA2UIOperations(result) {
    let parsed = result;
    if (typeof result === 'string') {
        try {
            parsed = JSON.parse(result);
        }
        catch {
            return undefined;
        }
    }
    if (!isRecord(parsed)) {
        return undefined;
    }
    const operations = parsed['a2ui_operations'];
    if (!Array.isArray(operations) || operations.length === 0) {
        return undefined;
    }
    return operations;
}
/** JSON Pointer read: "/" is the whole model, "/a/0/b" walks objects/arrays. */
export function resolveA2UIPointer(data, path) {
    if (path === '/' || path === '') {
        return data;
    }
    let current = data;
    for (const rawPart of path.replace(/^\//, '').split('/')) {
        const part = rawPart.replace(/~1/g, '/').replace(/~0/g, '~');
        if (Array.isArray(current)) {
            const index = Number(part);
            if (!Number.isInteger(index)) {
                return undefined;
            }
            current = current[index];
        }
        else if (isRecord(current)) {
            current = current[part];
        }
        else {
            return undefined;
        }
        if (current === undefined) {
            return undefined;
        }
    }
    return current;
}
function setA2UIPointer(data, path, value) {
    const parts = path.replace(/^\//, '').split('/').map(p => p.replace(/~1/g, '/').replace(/~0/g, '~'));
    let current = data;
    for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        const next = Array.isArray(current) ? current[Number(part)] : current[part];
        if (!isRecord(next) && !Array.isArray(next)) {
            if (Array.isArray(current)) {
                current[Number(part)] = {};
            }
            else {
                current[part] = {};
            }
            current = (Array.isArray(current) ? current[Number(part)] : current[part]);
        }
        else {
            current = next;
        }
    }
    const last = parts[parts.length - 1];
    if (Array.isArray(current)) {
        current[Number(last)] = value;
    }
    else {
        current[last] = value;
    }
}
/** A2UI binding: {path} reads the model; anything else is a literal. */
export function resolveA2UIValue(value, data) {
    if (isRecord(value) && typeof value['path'] === 'string') {
        return resolveA2UIPointer(data, value['path']);
    }
    if (Array.isArray(value)) {
        return value.map(item => resolveA2UIValue(item, data));
    }
    if (isRecord(value)) {
        const resolved = {};
        for (const [key, item] of Object.entries(value)) {
            resolved[key] = resolveA2UIValue(item, data);
        }
        return resolved;
    }
    return value;
}
/**
 * Surface store keyed by surfaceId. Ops apply in order; every failure mode
 * (unknown op/component, oversize payload, bad pointer) drops + logs and
 * leaves the rest of the surface intact.
 */
export class CrusorA2UISurfaceStore {
    constructor() {
        this.surfaces = new Map();
        this.dropped = [];
    }
    drop(reason) {
        this.dropped.push(reason);
        console.warn(`[CrusorAI] A2UI dropped: ${reason}`);
    }
    surface(surfaceId) {
        let existing = this.surfaces.get(surfaceId);
        if (!existing) {
            existing = { surfaceId, components: new Map(), order: [], data: {} };
            this.surfaces.set(surfaceId, existing);
        }
        return existing;
    }
    apply(operations) {
        for (const operation of operations.slice(0, MAX_A2UI_OPS)) {
            try {
                if (!isRecord(operation)) {
                    this.drop('non-object operation');
                    continue;
                }
                if (isRecord(operation['createSurface'])) {
                    const spec = operation['createSurface'];
                    const surfaceId = String(spec['surfaceId'] ?? '');
                    if (!surfaceId) {
                        this.drop('createSurface without surfaceId');
                        continue;
                    }
                    const surface = this.surface(surfaceId);
                    if (typeof spec['catalogId'] === 'string') {
                        surface.catalogId = spec['catalogId'];
                    }
                }
                else if (isRecord(operation['updateComponents'])) {
                    const spec = operation['updateComponents'];
                    const surface = this.surface(String(spec['surfaceId'] ?? ''));
                    const components = Array.isArray(spec['components']) ? spec['components'] : [];
                    for (const raw of components.slice(0, MAX_A2UI_COMPONENTS)) {
                        if (!isRecord(raw) || typeof raw['id'] !== 'string' || typeof raw['component'] !== 'string') {
                            this.drop('component without id/type');
                            continue;
                        }
                        if (!CRUSOR_A2UI_CATALOG_V1.includes(raw['component'])) {
                            this.drop(`unknown component ${String(raw['component'])}`);
                            continue;
                        }
                        if (!surface.components.has(raw['id'])) {
                            surface.order.push(raw['id']);
                        }
                        surface.components.set(raw['id'], raw);
                    }
                }
                else if (isRecord(operation['updateDataModel'])) {
                    const spec = operation['updateDataModel'];
                    const surface = this.surface(String(spec['surfaceId'] ?? ''));
                    const path = typeof spec['path'] === 'string' ? spec['path'] : '/';
                    if (path === '/' || path === '') {
                        surface.data = isRecord(spec['value']) ? { ...spec['value'] } : {};
                    }
                    else {
                        setA2UIPointer(surface.data, path, spec['value']);
                    }
                }
                else if (isRecord(operation['deleteSurface'])) {
                    this.surfaces.delete(String(operation['deleteSurface']['surfaceId'] ?? ''));
                }
                else {
                    this.drop('unknown operation');
                }
            }
            catch {
                this.drop('operation failed to apply');
            }
        }
    }
}
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
function childIds(component) {
    const ids = [];
    if (typeof component['child'] === 'string') {
        ids.push(component['child']);
    }
    if (Array.isArray(component['children'])) {
        for (const child of component['children']) {
            if (typeof child === 'string') {
                ids.push(child);
            }
        }
    }
    return ids;
}
function renderChildren(component, ctx) {
    const rendered = [];
    for (const id of childIds(component)) {
        const child = ctx.surface.components.get(id);
        if (child) {
            rendered.push(renderComponent(child, ctx));
        }
    }
    return rendered;
}
function boundString(component, key, ctx) {
    return boundText(resolveA2UIValue(component[key], ctx.surface.data));
}
function statusClass(status) {
    const normalized = status.toLowerCase();
    if (normalized === 'passed' || normalized === 'completed' || normalized === 'success' || normalized === 'done') {
        return 'is-passed';
    }
    if (normalized === 'failed' || normalized === 'error' || normalized === 'cancelled') {
        return 'is-failed';
    }
    if (normalized === 'running' || normalized === 'in_progress' || normalized === 'in progress') {
        return 'is-running';
    }
    return 'is-pending';
}
function emitAction(ctx, name, rawContext) {
    if (typeof name !== 'string' || !name) {
        return;
    }
    const resolved = resolveA2UIValue(rawContext ?? {}, ctx.surface.data);
    ctx.host.onAction?.({
        name,
        context: isRecord(resolved) ? resolved : {},
        surfaceId: ctx.surface.surfaceId,
    });
}
function renderComponent(component, ctx) {
    if (ctx.visiting.has(component.id)) {
        console.warn(`[CrusorAI] A2UI dropped: component cycle at ${component.id}`);
        return el('span', 'crusorai-a2ui-dropped');
    }
    ctx.visiting.add(component.id);
    try {
        switch (component.component) {
            case 'Card': {
                const card = el('div', 'crusorai-a2ui-card');
                card.dataset.surfaceId = ctx.surface.surfaceId;
                card.dataset.component = 'a2ui-card';
                for (const child of renderChildren(component, ctx)) {
                    card.append(child);
                }
                return card;
            }
            case 'Column': {
                const column = el('div', 'crusorai-a2ui-column');
                for (const child of renderChildren(component, ctx)) {
                    column.append(child);
                }
                return column;
            }
            case 'Row': {
                const row = el('div', 'crusorai-a2ui-row');
                for (const child of renderChildren(component, ctx)) {
                    row.append(child);
                }
                return row;
            }
            case 'Text': {
                const variant = typeof component['variant'] === 'string' ? component['variant'] : 'body';
                const text = boundString(component, 'text', ctx);
                if (variant === 'h3') {
                    return el('div', 'crusorai-a2ui-h3', text);
                }
                if (variant === 'caption') {
                    return el('div', 'crusorai-a2ui-caption', text);
                }
                if (variant === 'mono') {
                    return el('code', 'crusorai-a2ui-mono', text);
                }
                return el('div', 'crusorai-a2ui-text', text);
            }
            case 'Button': {
                const action = isRecord(component['action']) ? component['action'] : undefined;
                const event = action && isRecord(action['event']) ? action['event'] : undefined;
                const button = el('button', `crusorai-a2ui-button${component['variant'] === 'primary' ? ' is-primary' : ''}`);
                button.type = 'button';
                const children = renderChildren(component, ctx);
                if (children.length) {
                    for (const child of children) {
                        button.append(child);
                    }
                }
                else {
                    button.append(document.createTextNode(boundString(component, 'label', ctx) || 'Open'));
                }
                button.addEventListener('click', () => emitAction(ctx, event?.['name'], event?.['context']));
                return button;
            }
            case 'Diff': {
                const wrap = el('div', 'crusorai-a2ui-diff-wrap');
                const file = boundString(component, 'file', ctx);
                if (file) {
                    wrap.append(el('div', 'crusorai-a2ui-caption', file));
                }
                wrap.append(el('pre', 'crusorai-a2ui-diff', boundText(resolveA2UIValue(component['text'] ?? component['diff'], ctx.surface.data), 6000)));
                return wrap;
            }
            case 'TerminalOutput': {
                const wrap = el('div', 'crusorai-a2ui-terminal');
                const command = boundString(component, 'command', ctx);
                if (command) {
                    wrap.append(el('div', 'crusorai-a2ui-terminal-command', el('span', undefined, '$'), el('code', undefined, command)));
                }
                wrap.append(el('pre', 'crusorai-a2ui-terminal-output', boundText(resolveA2UIValue(component['output'] ?? component['text'], ctx.surface.data), 6000)));
                return wrap;
            }
            case 'PlanList': {
                const rawSteps = resolveA2UIValue(component['steps'], ctx.surface.data);
                const steps = Array.isArray(rawSteps) ? rawSteps.slice(0, MAX_A2UI_STEPS) : [];
                const list = el('div', 'crusorai-a2ui-plan');
                if (!steps.length) {
                    for (const child of renderChildren(component, ctx)) {
                        list.append(child);
                    }
                    return list;
                }
                for (const raw of steps) {
                    if (!isRecord(raw)) {
                        continue;
                    }
                    const status = String(raw['status'] ?? 'pending');
                    const label = boundText(raw['description'] ?? raw['content'] ?? raw['text'] ?? '', 300);
                    if (!label) {
                        continue;
                    }
                    list.append(el('div', `crusorai-a2ui-plan-row ${statusClass(status)}`, el('span', 'crusorai-a2ui-plan-glyph'), el('span', undefined, label)));
                }
                return list;
            }
            case 'Receipt': {
                // Verification ledger (Phase 3 fills this with real checks):
                // rows carry their OWN status; the verdict never outruns them.
                const wrap = el('div', 'crusorai-a2ui-receipt');
                const verdict = boundString(component, 'verdict', ctx);
                if (verdict) {
                    wrap.append(el('div', 'crusorai-a2ui-receipt-verdict', verdict));
                }
                const rawChecks = resolveA2UIValue(component['checks'], ctx.surface.data);
                const checks = Array.isArray(rawChecks) ? rawChecks.slice(0, MAX_A2UI_STEPS) : [];
                for (const raw of checks) {
                    if (!isRecord(raw)) {
                        continue;
                    }
                    const status = String(raw['status'] ?? 'pending');
                    const label = boundText(raw['label'] ?? raw['name'] ?? '', 300);
                    if (!label) {
                        continue;
                    }
                    wrap.append(el('div', `crusorai-a2ui-receipt-row ${statusClass(status)}`, el('span', undefined, label), el('strong', undefined, status)));
                }
                for (const child of renderChildren(component, ctx)) {
                    wrap.append(child);
                }
                return wrap;
            }
            case 'QuestionForm': {
                const wrap = el('div', 'crusorai-a2ui-questions');
                const rawQuestions = resolveA2UIValue(component['questions'], ctx.surface.data);
                const questions = Array.isArray(rawQuestions) ? rawQuestions.slice(0, 10) : [];
                for (const raw of questions) {
                    if (!isRecord(raw)) {
                        continue;
                    }
                    const questionId = String(raw['qid'] ?? raw['id'] ?? '');
                    const block = el('div', 'crusorai-a2ui-question', el('div', 'crusorai-a2ui-text', boundText(raw['question'] ?? '', 500)));
                    const choices = Array.isArray(raw['choices']) ? raw['choices'] : [];
                    for (const rawChoice of choices.slice(0, 8)) {
                        const choice = boundText(rawChoice, 200);
                        if (!choice) {
                            continue;
                        }
                        const choiceButton = el('button', 'crusorai-a2ui-button', choice);
                        choiceButton.type = 'button';
                        choiceButton.addEventListener('click', () => emitAction(ctx, 'crusor_question_answer', { questionId, choice }));
                        block.append(choiceButton);
                    }
                    wrap.append(block);
                }
                return wrap;
            }
            case 'ApprovalBar': {
                const wrap = el('div', 'crusorai-a2ui-approval');
                const name = boundString(component, 'name', ctx);
                const warning = boundString(component, 'warning', ctx);
                if (name) {
                    wrap.append(el('div', 'crusorai-a2ui-text', name));
                }
                if (warning) {
                    wrap.append(el('div', 'crusorai-a2ui-caption', warning));
                }
                const actions = el('div', 'crusorai-a2ui-approval-actions');
                for (const [label, decision] of [['Approve', 'approved'], ['Reject', 'rejected'], ['Always allow', 'always_allow']]) {
                    const actionButton = el('button', 'crusorai-a2ui-button', label);
                    actionButton.type = 'button';
                    actionButton.addEventListener('click', () => emitAction(ctx, 'crusor_approval', { decision }));
                    actions.append(actionButton);
                }
                wrap.append(actions);
                return wrap;
            }
            case 'Image': {
                const rawSrc = boundString(component, 'src', ctx);
                const resolvedSrc = rawSrc ? (ctx.host.resourceSrc?.(rawSrc) ?? (/^(https?:|data:)/.test(rawSrc) ? rawSrc : undefined)) : undefined;
                if (!resolvedSrc) {
                    return el('span', 'crusorai-a2ui-dropped');
                }
                const img = el('img', 'crusorai-a2ui-image');
                img.src = resolvedSrc;
                img.alt = boundString(component, 'alt', ctx);
                img.loading = 'lazy';
                img.onerror = () => { img.remove(); };
                return img;
            }
            default:
                console.warn(`[CrusorAI] A2UI dropped: unknown component ${component.component}`);
                return el('span', 'crusorai-a2ui-dropped');
        }
    }
    finally {
        ctx.visiting.delete(component.id);
    }
}
/** Render one applied surface. Root = the `root` component when present,
 * else the first component nothing else references. */
export function renderCrusorA2UISurface(surface, host) {
    const ctx = { surface, host, visiting: new Set() };
    let root = surface.components.get('root');
    if (!root) {
        const referenced = new Set();
        for (const component of surface.components.values()) {
            for (const id of childIds(component)) {
                referenced.add(id);
            }
        }
        for (const id of surface.order) {
            if (!referenced.has(id)) {
                root = surface.components.get(id);
                break;
            }
        }
        root ??= surface.components.get(surface.order[0]);
    }
    if (!root) {
        return el('div', 'crusorai-a2ui-empty');
    }
    return renderComponent(root, ctx);
}
/**
 * Tool-body entry point: if the tool result carries an A2UI envelope,
 * render it through the catalog; otherwise return undefined so the caller
 * falls back to today's family bodies. Never throws.
 */
export function renderA2UIToolBody(result, host) {
    const operations = parseCrusorA2UIOperations(result);
    if (!operations) {
        return undefined;
    }
    try {
        const store = new CrusorA2UISurfaceStore();
        store.apply(operations);
        const surface = store.surfaces.values().next().value;
        if (!surface || surface.components.size === 0) {
            return undefined;
        }
        const body = renderCrusorA2UISurface(surface, host);
        body.classList.add('crusorai-tool-body', 'crusorai-a2ui-body');
        return body;
    }
    catch {
        console.warn('[CrusorAI] A2UI dropped: surface failed to render');
        return undefined;
    }
}
