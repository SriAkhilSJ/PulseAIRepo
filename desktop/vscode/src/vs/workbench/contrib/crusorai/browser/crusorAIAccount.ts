/*---------------------------------------------------------------------------------------------
 * CrusorAI Account — top-right title-bar avatar + dropdown (image-2 parity, not clone).
 *
 * Why this exists (founder request 2026-09-21): like Antigravity IDE's pink "S"
 * avatar in the title bar, Crusor needs a single place at top-right to
 * Sign in / see who is logged in / reach IDE essentials without digging
 * through the File menu. The native VS Code Accounts (bottom-left) stays,
 * but the primary sign-in affordance for an AI IDE belongs next to the
 * window controls — where every AI IDE (Cursor, Windsurf, Antigravity)
 * puts it.
 *
 * What it shows — curated for an AI IDE (not a copy of Antigravity's text):
 *   - Header: account identity when logged in (future: reads ~/.crusorai/auth.json)
 *   - Crusor-specific: Subscription / Usage, Model & Provider, Agent Settings
 *   - IDE essentials: Keyboard Shortcuts, Themes, Docs, Changelog, Report Issue
 *   - Sign in / Sign out (opens https://www.crusor.in/login via opener)
 *
 * Placement: MenuId.TitleBar (right side of custom title bar, next to layout
 * controls & window buttons) with group 'navigation' so it stays visible even
 * when Command Center / layout controls are toggled. Uses Codicon.account so
 * the avatar is a person silhouette until we ship a real avatar image.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { localize2 } from '../../../../nls.js';
import { MenuId, MenuRegistry, registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { CrusorAICommandId } from '../common/crusorAI.js';

const CRUSOR_ACCOUNT_MENU_ID = new MenuId('CrusorAccountMenu');
const CRUSOR_ACCOUNT_DASHBOARD_URL = 'https://www.crusor.in/login';

// ----- Commands ---------------------------------------------------------------

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.AccountSignIn,
			title: localize2('crusorAI.account.signIn', 'Crusor: Sign in'),
			f1: true,
			category: localize2('crusorAI.category', 'Crusor'),
			icon: Codicon.account,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IOpenerService).open(CRUSOR_ACCOUNT_DASHBOARD_URL, { openExternal: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.AccountManage,
			title: localize2('crusorAI.account.manage', 'Crusor: Manage Account'),
			f1: true,
			category: localize2('crusorAI.category', 'Crusor'),
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(IOpenerService).open(CRUSOR_ACCOUNT_DASHBOARD_URL, { openExternal: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.AccountSignOut,
			title: localize2('crusorAI.account.signOut', 'Crusor: Sign out'),
			f1: true,
			category: localize2('crusorAI.category', 'Crusor'),
		});
	}
	async run(): Promise<void> {
		// TODO: clear ~/.crusorai/auth.json + in-memory account service.
		// For now this is a placeholder that surfaces the intent in palette.
	}
});

// Helper commands that delegate to existing workbench commands — keeps the
// dropdown as a true quick-access hub for AI-IDE ergonomics.
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'crusorai.account.openSettings',
			title: localize2('crusorAI.account.openSettings', 'Crusor: Settings'),
			f1: false,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.openSettings', 'crusorai');
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'crusorai.account.openShortcuts',
			title: localize2('crusorAI.account.openShortcuts', 'Crusor: Keyboard Shortcuts'),
			f1: false,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.openGlobalKeybindings');
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'crusorai.account.selectTheme',
			title: localize2('crusorAI.account.selectTheme', 'Crusor: Color Theme'),
			f1: false,
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.selectTheme');
	}
});

// ----- Title-bar avatar button (top-right) ----------------------------------
// Visible as a person icon at far right of the title bar, next to window
// controls. Click opens the Crusor Account submenu below.

MenuRegistry.appendMenuItem(MenuId.TitleBar, {
	submenu: CRUSOR_ACCOUNT_MENU_ID,
	title: localize2('crusorAI.account.titleBar', 'Crusor Account').value,
	icon: Codicon.account,
	group: 'navigation',
	order: 100,
});

// ----- Dropdown contents — ordered by AI-IDE relevance -----------------------

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: CrusorAICommandId.AccountSignIn, title: localize2('crusorAI.account.signIn.label', 'Sign in with Google / GitHub').value },
	group: '0_account',
	order: 1,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: CrusorAICommandId.AccountManage, title: localize2('crusorAI.account.manage.label', 'Manage Account & Subscription').value },
	group: '0_account',
	order: 2,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: 'crusorai.account.openSettings', title: localize2('crusorAI.account.settings.label', 'Crusor Settings').value },
	group: '1_settings',
	order: 1,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: CrusorAICommandId.OpenSettings, title: localize2('crusorAI.account.crusorSettings.label', 'Agent & Model Settings').value },
	group: '1_settings',
	order: 2,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: 'crusorai.account.openShortcuts', title: 'Keyboard Shortcuts' },
	group: '1_settings',
	order: 3,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: 'crusorai.account.selectTheme', title: 'Color Theme' },
	group: '1_settings',
	order: 4,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: 'workbench.action.openDocumentationUrl', title: 'Documentation' },
	group: '2_help',
	order: 1,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: 'workbench.action.showChangelog', title: 'Release Notes' },
	group: '2_help',
	order: 2,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: 'workbench.action.openIssueReporter', title: 'Report Issue / Feedback' },
	group: '2_help',
	order: 3,
});

MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
	command: { id: CrusorAICommandId.AccountSignOut, title: localize2('crusorAI.account.signOut.label', 'Sign out').value },
	group: '3_signout',
	order: 1,
});
