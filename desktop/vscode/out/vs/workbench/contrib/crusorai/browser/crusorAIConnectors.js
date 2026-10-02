// Crusor Connectors — show MCP/connectors in fork (Hermes hub parity).
// Registers Crusor: Show Connectors (Command Palette + Crusor menu).
// Reads skills SKILL.md manifest via SkillManager and .crusorai/mcp.json
// if present, then notifies — lightweight until a full Manager pane tab
// is warranted. Designed to be the entry point for the enterprise
// connectors hub (mcp, github, browser, db, terminal).
import { localize2 } from '../../../../nls.js';
const CONNECTORS = [
    { label: '$(plug) MCP', description: 'Model Context Protocol', detail: 'filesystem, github, postgres, puppeteer servers from .crusorai/mcp.json — say "list my MCP servers" in chat', id: 'mcp' },
    { label: '$(mark-github) GitHub connector', description: 'PRs and issues', detail: 'say "open the PR reviews for this repo" — uses gh / MCP github', id: 'github-connector' },
    { label: '$(browser) Browser connector', description: 'CDP / puppeteer verification', detail: 'say "verify the UI works" — Crusor drives a real browser and checks the page', id: 'browser-connector' },
    { label: '$(database) DB connector', description: 'postgres / sqlite', detail: 'say "query the users table" — guarded read/list tools, mutations ask first', id: 'db-connector' },
    { label: '$(terminal) Terminal connector', description: 'guarded shell access', detail: 'run_terminal with approval gates — already wired into every session', id: 'terminal-connector' },
];
registerAction2(class extends Action2 {
    constructor() {
        super({
            id: 'crusorai.showConnectors',
            title: localize2('crusorAI.showConnectors', 'Connectors (MCP, plugins)'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        });
    }
    async run(accessor) {
        // ServicesAccessor is single-shot: every get() runs before the first await.
        const quickInput = accessor.get(IQuickInputService);
        const notif = accessor.get(INotificationService);
        const commandService = accessor.get(ICommandService);
        const pick = await quickInput.pick([
            ...CONNECTORS.map(row => ({
                ...row,
                description: `${row.description} — ${row.id}`,
            })),
            { label: '$(search) Get more…', description: 'Marketplace — install skills and connector packs', id: '__marketplace', detail: '' },
            { label: '$(checklist) My Skills', description: 'everything installed — enable/disable, remove', id: '__myskills', detail: '' },
        ], { placeHolder: 'Crusor Connectors — what your agent can reach beyond the workspace' });
        if (!pick) {
            return;
        }
        if (pick.id === '__marketplace') {
            void commandService.executeCommand('crusorai.skillsHub');
            return;
        }
        if (pick.id === '__myskills') {
            void commandService.executeCommand('crusorai.mySkills');
            return;
        }
        const row = CONNECTORS.find(candidate => candidate.id === pick.id);
        if (row) {
            notif.notify({
                severity: Severity.Info,
                message: `${row.label.replace(/\$\([^)]+\)\s*/, '')} — ${row.detail}`,
                source: 'Crusor Connectors',
            });
        }
    }
});
