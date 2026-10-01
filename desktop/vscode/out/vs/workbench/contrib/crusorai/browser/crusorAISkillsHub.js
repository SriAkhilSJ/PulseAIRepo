// Crusor Skills Hub — the visual skills surface (Phase 3).
// Two Command Palette entries, QuickPick-driven (same shape as
// Crusor: Show Session History), talking to the engine through the
// skills_hub_op bridge envelope:
//
//   Crusor: Skills Hub  — browse the curated catalog, install, update,
//                         remove hub-installed skills (with update badges)
//   Crusor: My Skills   — every installed skill (any origin): enable /
//                         disable, remove hub installs, usage counts
//
// Everything rides the sandboxed pipeline (SHA pins, caps, collision
// guard) — the UI adds zero trust decisions of its own. Results come
// back as skills_hub_result frames; each request awaits exactly one
// matching frame with a timeout, and the flows are serial by design so
// same-op requests can never cross-resolve.
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
const HUB_TIMEOUT_MS = 12000;
function hubRequest(renderer, progress, op, extra = {}) {
    // The progress badge is the click's first ACK: palette flows must show
    // life IMMEDIATELY (field 2026-10-01: a silent 45s wait read as "nothing
    // happened" when the running bridge predated the Skills Hub build).
    return progress.withProgress({ location: ProgressLocation.Window, title: `Skills Hub: ${op}…` }, () => new Promise((resolve, reject) => {
        let listener;
        const timer = setTimeout(() => {
            listener?.dispose();
            reject(new Error(`Skills Hub: the engine did not answer the '${op}' request. Fully restart CrusorAI so the bridge process runs the Skills Hub build (pull → npx gulp compile in desktop/vscode → restart).`));
        }, HUB_TIMEOUT_MS);
        listener = renderer.onSkillsHubResult(frame => {
            if (frame.op !== op) {
                return; // not ours (a future concurrent flow) — keep waiting
            }
            clearTimeout(timer);
            listener?.dispose();
            resolve((frame.result ?? {}));
        });
        renderer.sendSkillsHubOp(op, extra);
    }));
}
function hubError(result, fallback) {
    const err = typeof result?.error === 'string' ? result.error : fallback;
    return `Skills Hub: ${err}`;
}
registerAction2(class extends Action2 {
    constructor() {
        super({
            id: 'crusorai.skillsHub',
            title: localize2('crusorAI.skillsHub', 'Skills Hub'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        });
    }
    async run(accessor) {
        const quickInput = accessor.get(IQuickInputService);
        const notif = accessor.get(INotificationService);
        const renderer = accessor.get(ICrusorAIRendererService);
        const progress = accessor.get(IProgressService);
        // ServicesAccessor is single-shot: every get() runs before the first await.
        let installed = [];
        try {
            const res = await hubRequest(renderer, progress, 'list');
            installed = Array.isArray(res.installed) ? res.installed : [];
        }
        catch (error) {
            notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
            return;
        }
        const updates = installed.filter(row => row.update_available);
        const picks = [
            { label: '$(search) Search the Skills Hub…', description: 'curated catalog — install with one click', id: '__search' },
        ];
        if (updates.length > 0) {
            picks.push({
                label: `$(cloud-download) Update all (${updates.length})`,
                description: updates.map(row => row.name).join(', '),
                id: '__update',
            });
        }
        for (const row of installed.slice(0, 40)) {
            picks.push({
                label: `${row.update_available ? '$(arrow-up)' : '$(check)'} ${row.name}`,
                description: `${row.repo} @ ${String(row.sha ?? '').slice(0, 12)} [${row.trust}]${row.update_available ? ' — update available' : ''}`,
                id: String(row.name),
            });
        }
        if (installed.length === 0) {
            picks.push({ label: 'No hub-installed skills yet', description: 'Search the catalog to install your first one', id: '__none' });
        }
        const pick = await quickInput.pick(picks, { placeHolder: 'Crusor Skills Hub — browse, install, update' });
        if (!pick) {
            return;
        }
        if (pick.id === '__search') {
            const query = await quickInput.input({ prompt: 'Search the Skills Hub catalog (keywords, e.g. "security review" or "react")' });
            if (!query || !query.trim()) {
                return;
            }
            let results = [];
            try {
                const res = await hubRequest(renderer, progress, 'search', { query: query.trim() });
                results = Array.isArray(res.results) ? res.results : [];
            }
            catch (error) {
                notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
                return;
            }
            if (results.length === 0) {
                notif.notify({ severity: Severity.Info, message: `Skills Hub: no catalog match for "${query.trim()}". You can install any GitHub repo from chat: hub_install("owner/repo@<sha>").`, source: 'Crusor Skills Hub' });
                return;
            }
            const resultPicks = results.map(entry => ({
                label: `$(package) ${entry.name} [${entry.category || 'general'}]`,
                description: `${entry.trust} — ${entry.description}`,
                id: String(entry.name),
            }));
            const chosen = await quickInput.pick(resultPicks, { placeHolder: 'Crusor Skills Hub — pick a skill to install' });
            if (!chosen) {
                return;
            }
            try {
                const res = await hubRequest(renderer, progress, 'install', { source: chosen.id });
                if (res.ok) {
                    notif.notify({ severity: Severity.Info, message: `Skills Hub: installed "${chosen.id}" (${res.files} files, pinned at ${String(res.sha ?? '').slice(0, 12)}). It is live in the skills index now.`, source: 'Crusor Skills Hub' });
                }
                else {
                    notif.notify({ severity: Severity.Error, message: hubError(res, 'install failed'), source: 'Crusor Skills Hub' });
                }
            }
            catch (error) {
                notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
            }
            return;
        }
        if (pick.id === '__update') {
            try {
                const res = await hubRequest(renderer, progress, 'update');
                const done = Array.isArray(res.updated) ? res.updated : [];
                const moved = done.filter(row => row.ok && row.updated);
                notif.notify({
                    severity: Severity.Info,
                    message: moved.length > 0
                        ? `Skills Hub: updated ${moved.length} skill(s) — ${moved.map(row => `${row.name} → ${String(row.to_sha ?? '').slice(0, 12)}`).join(', ')}`
                        : 'Skills Hub: everything is already at the catalog-pinned versions.',
                    source: 'Crusor Skills Hub',
                });
            }
            catch (error) {
                notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
            }
            return;
        }
        if (pick.id !== '__none') {
            // A hub-installed skill: per-skill actions.
            const actions = [
                { label: '$(arrow-up) Update to the catalog-pinned version', id: 'update' },
                { label: '$(trash) Remove this skill', id: 'remove' },
            ];
            const action = await quickInput.pick(actions, { placeHolder: `${pick.id} — choose an action` });
            if (!action) {
                return;
            }
            try {
                const res = await hubRequest(renderer, progress, action.id, { name: pick.id });
                if (res.ok) {
                    const detail = action.id === 'update' && !res.updated
                        ? ' (already at the pinned version)'
                        : '';
                    notif.notify({ severity: Severity.Info, message: `Skills Hub: ${action.id}d "${pick.id}"${detail}`, source: 'Crusor Skills Hub' });
                }
                else {
                    notif.notify({ severity: Severity.Error, message: hubError(res, `${action.id} failed`), source: 'Crusor Skills Hub' });
                }
            }
            catch (error) {
                notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
            }
        }
    }
});
registerAction2(class extends Action2 {
    constructor() {
        super({
            id: 'crusorai.mySkills',
            title: localize2('crusorAI.mySkills', 'My Skills'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        });
    }
    async run(accessor) {
        const quickInput = accessor.get(IQuickInputService);
        const notif = accessor.get(INotificationService);
        const renderer = accessor.get(ICrusorAIRendererService);
        const progress = accessor.get(IProgressService);
        let skills = [];
        try {
            const res = await hubRequest(renderer, progress, 'all');
            skills = Array.isArray(res.skills) ? res.skills : [];
        }
        catch (error) {
            notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
            return;
        }
        if (skills.length === 0) {
            notif.notify({ severity: Severity.Info, message: 'No skills installed yet — open Crusor: Skills Hub to browse the catalog.', source: 'Crusor Skills Hub' });
            return;
        }
        const originLabel = { hub: 'hub', bundled: 'bundled', user: 'yours', agent: 'agent-learned' };
        const picks = skills.slice(0, 60).map(row => ({
            label: `${row.enabled ? '$(check)' : '$(circle-slash)'} ${row.name}`,
            description: `[${originLabel[row.origin] ?? row.origin}${row.enabled ? '' : ', disabled'}] uses: ${row.use_count} — ${row.description}`,
            id: String(row.name),
        }));
        const chosen = await quickInput.pick(picks, { placeHolder: 'Crusor My Skills — pick a skill to manage' });
        if (!chosen) {
            return;
        }
        const row = skills.find(candidate => candidate.name === chosen.id);
        const actions = [
            { label: row?.enabled ? '$(circle-slash) Disable' : '$(check) Enable', id: 'toggle' },
            { label: '$(trash) Remove (hub-installed skills only)', id: 'remove' },
        ];
        const action = await quickInput.pick(actions, { placeHolder: `${chosen.id} — choose an action` });
        if (!action) {
            return;
        }
        try {
            const res = action.id === 'toggle'
                ? await hubRequest(renderer, progress, 'toggle', { name: chosen.id, enabled: !(row?.enabled ?? true) })
                : await hubRequest(renderer, progress, 'remove', { name: chosen.id });
            if (res.ok) {
                const detail = action.id === 'toggle'
                    ? ` → ${res.enabled ? 'enabled' : 'disabled'}`
                    : '';
                notif.notify({ severity: Severity.Info, message: `Skills Hub: "${chosen.id}"${detail}`, source: 'Crusor Skills Hub' });
            }
            else {
                notif.notify({ severity: Severity.Error, message: hubError(res, 'action failed'), source: 'Crusor Skills Hub' });
            }
        }
        catch (error) {
            notif.notify({ severity: Severity.Error, message: String(error.message ?? error), source: 'Crusor Skills Hub' });
        }
    }
});
