/*---------------------------------------------------------------------------------------------
 * PulseAI IDE first-party workbench registration. Never an extension.
 *
 * Follows the same shape as Copilot Chat (chatParticipant.contribution.ts):
 *   - View container on the right (Auxiliary Bar), doNotRegisterOpenCommand:true
 *   - View descriptor carries openCommandActionDescriptor with Ctrl/Cmd+L
 *   - Top-level menubar entry between Terminal and Help
 *   - Title-bar (command center) icon, one click to open Agent
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { localize, localize2 } from '../../../../nls.js';
import { MenuId, MenuRegistry, registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService, ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { EditorPaneDescriptor, IEditorPaneRegistry } from '../../../browser/editor.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import {
	Extensions as ViewContainerExtensions,
	IViewContainersRegistry,
	IViewDescriptor,
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
import './media/pulseai-tokens.css';
import './media/pulseAI.css';

const PULSE_AI_MENU_ID = new MenuId('MenubarPulseAI');

// Keep common/web hosts constructable. The desktop entrypoint registers its
// utility-process implementation later, replacing this no-process fallback.
registerSingleton(IPulseAIEngineService, PulseAIUnavailableEngineService, InstantiationType.Delayed);
registerSingleton(IPulseAIWorkbenchService, PulseAIWorkbenchService, InstantiationType.Delayed);
registerSingleton(IPulseAIRendererService, PulseAIRendererService, InstantiationType.Delayed);

// --- Pulse container (right-side auxiliary bar) ---------------------------
// Same shape used by Copilot Chat:
//   • AuxiliaryBar (right-side secondary sidebar)
//   • doNotRegisterOpenCommand: true  — we wire the open command on the VIEW
//     descriptor, which is the pattern viewsService.ts actually reads to
//     install the keybinding + F1 + View-menu entry.
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
}, ViewContainerLocation.AuxiliaryBar, { doNotRegisterOpenCommand: true });

// --- Pulse Agent view ------------------------------------------------------
// Keybinding: Ctrl/Cmd+L — market standard "talk to the AI" chord:
//   • Cursor   → Ctrl/Cmd+L opens AI chat
//   • Windsurf → Ctrl/Cmd+L opens Cascade (agent)
// We register this on the view descriptor (same as Copilot does at
// chatParticipant.contribution.ts:58) so viewsService.ts auto-generates the
// toggle command, F1 Command Palette entry, and View-menu entry with the
// keybinding at KeybindingWeight.WorkbenchContrib (200), which outranks
// the editor's built-in 'expandLineSelection' (EditorCore = 0) — same
// global-steal trick Cursor and Windsurf ship with.
const pulseViewDescriptor: IViewDescriptor = {
	id: PULSE_AI_VIEW_ID,
	name: localize2('pulseAI.view.name', 'Pulse Agent'),
	containerIcon: Codicon.pulse,
	containerTitle: localize('pulseAI.containerTitle', 'Pulse'),
	singleViewPaneContainerTitle: localize('pulseAI.singlePaneTitle', 'Pulse'),
	canToggleVisibility: true,
	canMoveView: false,
	ctorDescriptor: new SyncDescriptor(PulseAIViewPane),
	openCommandActionDescriptor: {
		id: PULSE_AI_VIEW_CONTAINER_ID,
		title: localize2('pulseAI.openAgent', 'Pulse: Open Agent'),
		mnemonicTitle: localize({ key: 'miTogglePulse', comment: ['&& denotes a mnemonic'] }, '&&Pulse Agent'),
		keybindings: {
			primary: KeyMod.CtrlCmd | KeyCode.KeyL,
		},
		order: 1,
	},
};
Registry.as<IViewsRegistry>(ViewContainerExtensions.ViewsRegistry).registerViews(
	[pulseViewDescriptor], container
);

// --- Manager editor (Agent Manager, Copilot's "Agents Window" analogue) ---
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

// --- Top-level Pulse menu --------------------------------------------------
// order: 7.5 sits between Terminal(7) and Help(8) in MenubarMainMenu.
// On Windows/Linux the menubar reads:
//   File · Edit · Selection · View · Go · Run · Terminal · Pulse · Help
// (The 'Window' menu is a macOS-native Electron menu injected only on darwin;
// it is not present on Windows/Linux in Code OSS at this pin.)
MenuRegistry.appendMenuItem(MenuId.MenubarMainMenu, {
	submenu: PULSE_AI_MENU_ID,
	title: {
		value: 'Pulse',
		original: 'Pulse',
		mnemonicTitle: localize({ key: 'mPulse', comment: ['&& denotes a mnemonic'] }, '&&Pulse'),
	},
	order: 7.5,
});

// --- Title-bar (command center) icon ---------------------------------------
// Copilot ships a Copilot icon in the command center (top-center of the
// title bar) that one-clicks open chat. We match that: a Pulse icon in the
// command center that fires the same open command Ctrl+L fires. Appears when
// window.commandCenter is enabled (default in modern Code OSS).
MenuRegistry.appendMenuItem(MenuId.CommandCenterCenter, {
	command: {
		id: PULSE_AI_VIEW_CONTAINER_ID,
		title: localize2('pulseAI.commandCenter.tooltip', 'Open Pulse Agent (Ctrl+L)'),
		icon: Codicon.pulse,
	},
	order: -100, // far-left of command center, next to the back/forward icons
});

// Helper: open Pulse and focus it.
async function focusPulse(accessor: ServicesAccessor): Promise<void> {
	await accessor.get(IViewsService).openView(PULSE_AI_VIEW_ID, true);
}

// --- Pulse dropdown entries -----------------------------------------------
// "Open Pulse Agent" reuses the container's auto-registered toggle command
// (id: PULSE_AI_VIEW_CONTAINER_ID → 'workbench.view.pulseai') which is the
// same command that Ctrl+L and the command-center icon fire. This way the
// shortcut shows up next to the menu item automatically.
MenuRegistry.appendMenuItem(PULSE_AI_MENU_ID, {
	command: {
		id: PULSE_AI_VIEW_CONTAINER_ID,
		title: localize('pulseAI.menu.openAgent', 'Open Pulse Agent'),
	},
	group: '0_open',
	order: 1,
});

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
	run(accessor: ServicesAccessor): Promise<void> { return focusPulse(accessor); }
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
	run(accessor: ServicesAccessor): Promise<void> { return focusPulse(accessor); }
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
	run(accessor: ServicesAccessor): Promise<void> { return focusPulse(accessor); }
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
	run(accessor: ServicesAccessor): Promise<void> { return focusPulse(accessor); }
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
