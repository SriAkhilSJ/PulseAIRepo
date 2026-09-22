/*---------------------------------------------------------------------------------------------
 * CrusorAI IDE first-party workbench registration. Never an extension.
 *
 * Entry points (all fire the same command -> crusorai.focus):
 *   - Top-level "Crusor" menu between Terminal and Help
 *   - Ctrl/Cmd+L (market standard: Cursor, Windsurf)
 *   - Title-bar (command center) Crusor icon, one-click open
 *   - F1 Command Palette: "Crusor: Open Agent"
 *   - View menu (auto-added by viewsService for AuxiliaryBar views)
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { localize, localize2 } from '../../../../nls.js';
import { MenuId, MenuRegistry, registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { ICrusorAISessionStore, CrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import './crusorAISessionController.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import {
	Extensions as ViewContainerExtensions,
	IViewContainersRegistry,
	IViewsRegistry,
	ViewContainerLocation,
} from '../../../common/views.js';
import { EditorExtensions, IEditorFactoryRegistry } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import {
	CRUSOR_AI_VIEW_CONTAINER_ID,
	CRUSOR_AI_VIEW_ID,
	CrusorAICommandId,
} from '../common/crusorAI.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { ICrusorAIWorkbenchService } from '../common/crusorAIWorkbenchService.js';
import { CrusorAIManagerEditor } from './crusorAIManagerEditor.js';
import { CrusorAIManagerInput, CrusorAIManagerInputSerializer } from './crusorAIManagerInput.js';
import { CrusorAIRendererService } from './crusorAIRendererService.js';
import { CrusorAIViewPane } from './crusorAIViewPane.js';
import { CrusorAIWorkbenchService } from './crusorAIWorkbenchService.js';
import { CrusorAIUnavailableEngineService } from './crusorAIUnavailableEngineService.js';
import './media/crusorAI-tokens.css';
import './media/crusorAI.css';
// Hide Copilot's CHAT tab, empty-editor watermark, and title-bar sign-in UI
// when Crusor is the primary AI. No Copilot source is modified; this file
// forces Copilot's own "hidden" context keys at startup.
import './crusorAIHideCopilot.js';
// Top-right account avatar + dropdown — AI-IDE essentials at title bar (image-2 parity)
import './crusorAIAccount.js';
// Connectors hub — MCP/connectors visible in fork (Hermes hub parity)
import './crusorAIConnectors.js';

const CRUSOR_AI_MENU_ID = new MenuId('MenubarCrusorAI');

// Keep common/web hosts constructable. The desktop entrypoint registers its
// utility-process implementation later, replacing this no-process fallback.
registerSingleton(ICrusorAIEngineService, CrusorAIUnavailableEngineService, InstantiationType.Delayed);
registerSingleton(ICrusorAIWorkbenchService, CrusorAIWorkbenchService, InstantiationType.Delayed);
registerSingleton(ICrusorAIRendererService, CrusorAIRendererService, InstantiationType.Delayed);
// The Agent Manager's session list and the workbench's own Agent Sessions list are projections of
// this store. It is a singleton rather than renderer state so that a session the user ran is
// remembered even while neither surface is mounted.
registerSingleton(ICrusorAISessionStore, CrusorAISessionStore, InstantiationType.Delayed);

// --- Crusor container (right-side auxiliary bar) ---------------------------
// Lives on the right (secondary) sidebar — same default location as Cursor's
// chat panel, Windsurf's Cascade, and VS Code's Copilot Chat.
const container = Registry.as<IViewContainersRegistry>(
	ViewContainerExtensions.ViewContainersRegistry
).registerViewContainer({
	id: CRUSOR_AI_VIEW_CONTAINER_ID,
	title: localize2('crusorAI.viewContainer.title', 'Crusor'),
	icon: Codicon.cursor,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [
		CRUSOR_AI_VIEW_CONTAINER_ID,
		{ mergeViewWithContainerWhenSingleView: true },
	]),
	storageId: CRUSOR_AI_VIEW_CONTAINER_ID,
	order: 6,
}, ViewContainerLocation.AuxiliaryBar);

Registry.as<IViewsRegistry>(ViewContainerExtensions.ViewsRegistry).registerViews([{
	id: CRUSOR_AI_VIEW_ID,
	name: localize2('crusorAI.view.name', 'Crusor Agent'),
	containerIcon: Codicon.cursor,
	canToggleVisibility: true,
	canMoveView: false,
	ctorDescriptor: new SyncDescriptor(CrusorAIViewPane),
}], container);

// --- Crusor Manager (full-width editor tab, Copilot "Agents Window" analogue)
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(
	CrusorAIManagerInput.ID,
	CrusorAIManagerInputSerializer,
);
Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(
		CrusorAIManagerEditor,
		CrusorAIManagerEditor.ID,
		localize('crusorAI.manager.editor', 'Crusor Manager'),
	),
	[new SyncDescriptor(CrusorAIManagerInput)],
);

// --- Primary open command: crusorai.focus ----------------------------------
// Explicit action, not auto-wired. Keybinding Ctrl/Cmd+L (market-standard
// "talk to the AI" chord: Cursor, Windsurf). Weighted at WorkbenchContrib
// (200) which outranks the editor's built-in expandLineSelection (EditorCore
// = 0) — same global-steal trick Cursor and Windsurf ship.
async function openCrusorAgent(accessor: ServicesAccessor): Promise<void> {
	// openView with focus=true behaves like every other VS Code "open view"
	// command (Explorer, Search, SCM, Debug, Terminal, Chat): if the view is
	// already open it just focuses it; if closed it opens and mounts the pane.
	// Deliberately avoids casting to any or reaching into private API.
	await accessor.get(IViewsService).openView(CRUSOR_AI_VIEW_ID, true);
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.Focus,
			title: localize2('crusorAI.focus', 'Crusor: Open Agent'),
			f1: true,
			category: localize2('crusorAI.category', 'Crusor'),
			icon: Codicon.cursor,
			keybinding: {
				weight: KeybindingWeight.WorkbenchContrib,
				primary: KeyMod.CtrlCmd | KeyCode.KeyL,
			},
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openCrusorAgent(accessor); }
});

// --- Top-level Crusor menu (between Terminal and Help) ---------------------
// Menubar order reference (menubar.contribution.ts + debug.contribution.ts):
//   File(1) · Edit(2) · Selection(3) · View(4) · Go(5) · Run(6) · Terminal(7)
//   ······ Crusor(7.5) ······ Help(8) · Preferences(9, Mac-only)
MenuRegistry.appendMenuItem(MenuId.MenubarMainMenu, {
	submenu: CRUSOR_AI_MENU_ID,
	title: {
		value: 'Crusor',
		original: 'Crusor',
		mnemonicTitle: localize({ key: 'mCrusor', comment: ['&& denotes a mnemonic'] }, '&&Crusor'),
	},
	order: 7.5,
});

// First item in the Crusor dropdown reuses the explicit open command so the
// Ctrl+L shortcut shows up next to it automatically.
MenuRegistry.appendMenuItem(CRUSOR_AI_MENU_ID, {
	command: {
		id: CrusorAICommandId.Focus,
		title: localize('crusorAI.menu.openAgent', 'Open Crusor Agent'),
	},
	group: '0_open',
	order: 1,
});

// --- Title-bar (command center) Crusor icon --------------------------------
// Copilot shows a Copilot/sparkle icon in the top-center command center that
// one-clicks opens chat. We mirror that with a crusor icon firing the same
// open command as Ctrl+L. Appears when window.commandCenter is enabled
// (default in modern Code OSS).
MenuRegistry.appendMenuItem(MenuId.CommandCenterCenter, {
	command: {
		id: CrusorAICommandId.Focus,
		title: localize2('crusorAI.commandCenter.tooltip', 'Open Crusor Agent (Ctrl+L)'),
		icon: Codicon.cursor,
	},
	order: -100,
});

// --- Session / review / control / settings entries -----------------------

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.NewSession,
			title: localize2('crusorAI.newSession', 'New Agent Session'),
			f1: true,
			icon: Codicon.add,
			menu: [{ id: CRUSOR_AI_MENU_ID, group: '1_session', order: 1 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openCrusorAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.OpenManager,
			title: localize2('crusorAI.openManager', 'Open Crusor Manager'),
			f1: true,
			icon: Codicon.organization,
			menu: [
				{ id: CRUSOR_AI_MENU_ID, group: '1_session', order: 2 },
			],
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const input = accessor.get(IInstantiationService).createInstance(CrusorAIManagerInput);
		await accessor.get(IEditorService).openEditor(input, { pinned: true });
	}
});

MenuRegistry.appendMenuItem(CRUSOR_AI_MENU_ID, {
	command: { id: 'crusorai.showConnectors', title: localize('crusorAI.menu.connectors', 'Connectors') },
	group: '1_session',
	order: 3,
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.ReviewChanges,
			title: localize2('crusorAI.reviewChanges', 'Review Changes'),
			f1: true,
			icon: Codicon.diff,
			menu: [{ id: CRUSOR_AI_MENU_ID, group: '2_review', order: 1 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openCrusorAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.OpenCheckpoints,
			title: localize2('crusorAI.openCheckpoints', 'Checkpoints'),
			f1: true,
			icon: Codicon.history,
			menu: [{ id: CRUSOR_AI_MENU_ID, group: '2_review', order: 2 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openCrusorAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.StopActiveRun,
			title: localize2('crusorAI.stopActiveRun', 'Stop Active Run'),
			f1: true,
			icon: Codicon.debugStop,
			menu: [{ id: CRUSOR_AI_MENU_ID, group: '3_control', order: 1 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openCrusorAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.AcceptDiff,
			title: localize2('crusorAI.acceptDiff', 'Accept Change'),
			f1: true,
			icon: Codicon.check,
			menu: [{
				id: MenuId.EditorTitle,
				group: 'navigation@1',
				when: ContextKeyExpr.has('crusorai.hasActiveDiff'),
			}],
		});
	}
	run(accessor: ServicesAccessor): void {
		accessor.get(ICrusorAIWorkbenchService).acceptActiveDiff();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.RejectDiff,
			title: localize2('crusorAI.rejectDiff', 'Reject Change'),
			f1: true,
			icon: Codicon.close,
			menu: [{
				id: MenuId.EditorTitle,
				group: 'navigation@2',
				when: ContextKeyExpr.has('crusorai.hasActiveDiff'),
			}],
		});
	}
	run(accessor: ServicesAccessor): void {
		accessor.get(ICrusorAIWorkbenchService).rejectActiveDiff();
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: CrusorAICommandId.OpenSettings,
			title: localize2('crusorAI.openSettings', 'Crusor Settings'),
			f1: true,
			icon: Codicon.settingsGear,
			menu: [{ id: CRUSOR_AI_MENU_ID, group: '4_settings', order: 1 }],
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.openSettings', 'crusorai');
	}
});

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'crusorai',
	title: localize2('crusorai.copilotWebview.title', 'CrusorAI CopilotKit Webview').value,
	type: 'object',
	properties: {
		'crusorai.copilotWebview.enabled': {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.APPLICATION,
			description: localize('crusorai.copilotWebview.enabled.desc', "Show the CopilotKit React surface (crusor-webview) under the native Crusor Agent view. Turn off to give the whole pane to the native renderer."),
		},
		'crusorai.copilotWebview.url': {
			type: 'string',
			default: 'local',
			scope: ConfigurationScope.APPLICATION,
			description: localize('crusorai.copilotWebview.url.desc', "What the CopilotKit tab loads. 'local' (default) uses the SPA built into the app by `npm run build` in crusor-webview, which needs no server and works in packaged or remote windows. Any other value is an absolute URL framed as-is -- the workbench CSP allows only 'self' and vscode-webview:, so an http URL will be refused unless you extend the frame policy, and a dev server on :5173 therefore belongs in a browser tab, not here.")
		},
		'crusorai.copilotWebview.height': {
			type: 'number',
			default: 50,
			minimum: 10,
			maximum: 85,
			scope: ConfigurationScope.APPLICATION,
			description: localize('crusorai.copilotWebview.height.desc', "Share of the Crusor view given to the CopilotKit webview, in percent. The native Agent renderer keeps the rest."),
		},
		'crusorai.notifyOnComplete': {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.APPLICATION,
			description: localize('crusorAI.notifyOnComplete.desc', "Show a 'Response Ready — Crusor' notification when the agent finishes a run. Disable to keep runs silent."),
		},
	},
});
