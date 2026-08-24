/*---------------------------------------------------------------------------------------------
 * PulseAI IDE first-party workbench registration. Never an extension.
 *
 * Entry points (all fire the same command -> pulseai.focus):
 *   - Top-level "Pulse" menu between Terminal and Help
 *   - Ctrl/Cmd+L (market standard: Cursor, Windsurf)
 *   - Title-bar (command center) Pulse icon, one-click open
 *   - F1 Command Palette: "Pulse: Open Agent"
 *   - View menu (auto-added by viewsService for AuxiliaryBar views)
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { localize, localize2 } from '../../../../nls.js';
import { MenuId, MenuRegistry, registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
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
	PULSE_AI_VIEW_CONTAINER_ID,
	PULSE_AI_VIEW_ID,
	PulseAICommandId,
} from '../common/pulseAI.js';
import { IPulseAIEngineService } from '../common/pulseAIEngineService.js';
import { IPulseAIRendererService } from '../common/pulseAIRendererService.js';
import { IPulseAIWorkbenchService } from '../common/pulseAIWorkbenchService.js';
import { PulseAIManagerEditor } from './pulseAIManagerEditor.js';
import { PulseAIManagerInput, PulseAIManagerInputSerializer } from './pulseAIManagerInput.js';
import { PulseAIRendererService } from './pulseAIRendererService.js';
import { PulseAIViewPane } from './pulseAIViewPane.js';
import { PulseAIWorkbenchService } from './pulseAIWorkbenchService.js';
import { PulseAIUnavailableEngineService } from './pulseAIUnavailableEngineService.js';
import './media/pulseAI-tokens.css';
import './media/pulseAI.css';

const PULSE_AI_MENU_ID = new MenuId('MenubarPulseAI');

// Keep common/web hosts constructable. The desktop entrypoint registers its
// utility-process implementation later, replacing this no-process fallback.
registerSingleton(IPulseAIEngineService, PulseAIUnavailableEngineService, InstantiationType.Delayed);
registerSingleton(IPulseAIWorkbenchService, PulseAIWorkbenchService, InstantiationType.Delayed);
registerSingleton(IPulseAIRendererService, PulseAIRendererService, InstantiationType.Delayed);

// --- Pulse container (right-side auxiliary bar) ---------------------------
// Lives on the right (secondary) sidebar — same default location as Cursor's
// chat panel, Windsurf's Cascade, and VS Code's Copilot Chat.
const container = Registry.as<IViewContainersRegistry>(
	ViewContainerExtensions.ViewContainersRegistry
).registerViewContainer({
	id: PULSE_AI_VIEW_CONTAINER_ID,
	title: localize2('pulseAI.viewContainer.title', 'Pulse'),
	icon: Codicon.pulse,
	ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [
		PULSE_AI_VIEW_CONTAINER_ID,
		{ mergeViewWithContainerWhenSingleView: true },
	]),
	storageId: PULSE_AI_VIEW_CONTAINER_ID,
	order: 6,
}, ViewContainerLocation.AuxiliaryBar);

Registry.as<IViewsRegistry>(ViewContainerExtensions.ViewsRegistry).registerViews([{
	id: PULSE_AI_VIEW_ID,
	name: localize2('pulseAI.view.name', 'Pulse Agent'),
	containerIcon: Codicon.pulse,
	canToggleVisibility: true,
	canMoveView: false,
	ctorDescriptor: new SyncDescriptor(PulseAIViewPane),
}], container);

// --- Pulse Manager (full-width editor tab, Copilot "Agents Window" analogue)
Registry.as<IEditorFactoryRegistry>(EditorExtensions.EditorFactory).registerEditorSerializer(
	PulseAIManagerInput.ID,
	PulseAIManagerInputSerializer,
);
Registry.as<IEditorPaneRegistry>(EditorExtensions.EditorPane).registerEditorPane(
	EditorPaneDescriptor.create(
		PulseAIManagerEditor,
		PulseAIManagerEditor.ID,
		localize('pulseAI.manager.editor', 'Pulse Manager'),
	),
	[new SyncDescriptor(PulseAIManagerInput)],
);

// --- Primary open command: pulseai.focus ----------------------------------
// Explicit action, not auto-wired. Keybinding Ctrl/Cmd+L (market-standard
// "talk to the AI" chord: Cursor, Windsurf). Weighted at WorkbenchContrib
// (200) which outranks the editor's built-in expandLineSelection (EditorCore
// = 0) — same global-steal trick Cursor and Windsurf ship.
async function openPulseAgent(accessor: ServicesAccessor): Promise<void> {
	// openView with focus=true behaves like every other VS Code "open view"
	// command (Explorer, Search, SCM, Debug, Terminal, Chat): if the view is
	// already open it just focuses it; if closed it opens and mounts the pane.
	// Deliberately avoids casting to any or reaching into private API.
	await accessor.get(IViewsService).openView(PULSE_AI_VIEW_ID, true);
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.Focus,
			title: localize2('pulseAI.focus', 'Pulse: Open Agent'),
			f1: true,
			category: localize2('pulseAI.category', 'Pulse'),
			icon: Codicon.pulse,
			keybinding: {
				weight: KeybindingWeight.WorkbenchContrib,
				primary: KeyMod.CtrlCmd | KeyCode.KeyL,
			},
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openPulseAgent(accessor); }
});

// --- Top-level Pulse menu (between Terminal and Help) ---------------------
// Menubar order reference (menubar.contribution.ts + debug.contribution.ts):
//   File(1) · Edit(2) · Selection(3) · View(4) · Go(5) · Run(6) · Terminal(7)
//   ······ Pulse(7.5) ······ Help(8) · Preferences(9, Mac-only)
MenuRegistry.appendMenuItem(MenuId.MenubarMainMenu, {
	submenu: PULSE_AI_MENU_ID,
	title: {
		value: 'Pulse',
		original: 'Pulse',
		mnemonicTitle: localize({ key: 'mPulse', comment: ['&& denotes a mnemonic'] }, '&&Pulse'),
	},
	order: 7.5,
});

// First item in the Pulse dropdown reuses the explicit open command so the
// Ctrl+L shortcut shows up next to it automatically.
MenuRegistry.appendMenuItem(PULSE_AI_MENU_ID, {
	command: {
		id: PulseAICommandId.Focus,
		title: localize('pulseAI.menu.openAgent', 'Open Pulse Agent'),
	},
	group: '0_open',
	order: 1,
});

// --- Title-bar (command center) Pulse icon --------------------------------
// Copilot shows a Copilot/sparkle icon in the top-center command center that
// one-clicks opens chat. We mirror that with a pulse icon firing the same
// open command as Ctrl+L. Appears when window.commandCenter is enabled
// (default in modern Code OSS).
MenuRegistry.appendMenuItem(MenuId.CommandCenterCenter, {
	command: {
		id: PulseAICommandId.Focus,
		title: localize2('pulseAI.commandCenter.tooltip', 'Open Pulse Agent (Ctrl+L)'),
		icon: Codicon.pulse,
	},
	order: -100,
});

// --- Session / review / control / settings entries -----------------------

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.NewSession,
			title: localize2('pulseAI.newSession', 'New Agent Session'),
			f1: true,
			icon: Codicon.add,
			menu: [{ id: PULSE_AI_MENU_ID, group: '1_session', order: 1 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openPulseAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.OpenManager,
			title: localize2('pulseAI.openManager', 'Open Pulse Manager'),
			f1: true,
			icon: Codicon.organization,
			menu: [{ id: PULSE_AI_MENU_ID, group: '1_session', order: 2 }],
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const input = accessor.get(IInstantiationService).createInstance(PulseAIManagerInput);
		await accessor.get(IEditorService).openEditor(input, { pinned: true });
	}
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.ReviewChanges,
			title: localize2('pulseAI.reviewChanges', 'Review Changes'),
			f1: true,
			icon: Codicon.diff,
			menu: [{ id: PULSE_AI_MENU_ID, group: '2_review', order: 1 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openPulseAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.OpenCheckpoints,
			title: localize2('pulseAI.openCheckpoints', 'Checkpoints'),
			f1: true,
			icon: Codicon.history,
			menu: [{ id: PULSE_AI_MENU_ID, group: '2_review', order: 2 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openPulseAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.StopActiveRun,
			title: localize2('pulseAI.stopActiveRun', 'Stop Active Run'),
			f1: true,
			icon: Codicon.debugStop,
			menu: [{ id: PULSE_AI_MENU_ID, group: '3_control', order: 1 }],
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return openPulseAgent(accessor); }
});

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.OpenSettings,
			title: localize2('pulseAI.openSettings', 'Pulse Settings'),
			f1: true,
			icon: Codicon.settingsGear,
			menu: [{ id: PULSE_AI_MENU_ID, group: '4_settings', order: 1 }],
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.openSettings', 'pulseai');
	}
});
