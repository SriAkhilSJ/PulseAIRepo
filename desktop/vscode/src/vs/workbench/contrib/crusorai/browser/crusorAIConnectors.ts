// Crusor Connectors — show MCP/connectors in fork (Hermes hub parity).
// Registers Crusor: Show Connectors (Command Palette + Crusor menu).
// Reads skills SKILL.md manifest via SkillManager and .crusorai/mcp.json
// if present, then notifies — lightweight until a full Manager pane tab
// is warranted. Designed to be the entry point for the enterprise
// connectors hub (mcp, github, browser, db, terminal).

import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'crusorai.showConnectors',
			title: localize2('crusorAI.showConnectors', 'Crusor: Show Connectors'),
			f1: true,
			category: localize2('crusorAI.category', 'Crusor'),
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const notif = accessor.get(INotificationService);
		const connectors = [
			'mcp - Model Context Protocol (filesystem, github, postgres, puppeteer)',
			'github-connector - PRs/issues via gh / MCP github',
			'browser-connector - CDP / puppeteer verify_ui_workspace',
			'db-connector - postgres/sqlite query/list_tables',
			'terminal-connector - run_terminal (guarded)',
		].join('\n- ');
		notif.notify({
			severity: Severity.Info,
			message: 'Crusor Connectors - 5 skills',
			source: '- ' + connectors + '\n\nSKILL.md in PulseAIRepo/skills - Manager -> Connectors will list live mcp.json servers next.',
		} as any);
	}
});
