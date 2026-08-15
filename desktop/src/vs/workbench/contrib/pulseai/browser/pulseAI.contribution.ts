/*---------------------------------------------------------------------------------------------
 * PulseAI IDE first-party workbench registration. Never an extension.
 *--------------------------------------------------------------------------------------------*/

import { Codicon } from '../../../../base/common/codicons.js';
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
}, ViewContainerLocation.Sidebar);

Registry.as<IViewsRegistry>(ViewContainerExtensions.ViewsRegistry).registerViews([{
	id: PULSE_AI_VIEW_ID,
	name: localize2('pulseAI.view.name', 'Pulse Agent'),
	containerIcon: Codicon.pulse,
	canToggleVisibility: true,
	canMoveView: false,
	ctorDescriptor: new SyncDescriptor(PulseAIViewPane),
}], container);

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

MenuRegistry.appendMenuItem(MenuId.MenubarMainMenu, {
	title: localize2('pulseAI.menu.title', 'Pulse'),
	submenu: PULSE_AI_MENU_ID,
	group: '9_pulseAI',
	order: 1,
});

async function focusPulse(accessor: ServicesAccessor): Promise<void> {
	await accessor.get(IViewsService).openView(PULSE_AI_VIEW_ID, true);
}

registerAction2(class extends Action2 {
	constructor() {
		super({
			id: PulseAICommandId.Focus,
			title: localize2('pulseAI.focus', 'PulseAI: Focus Agent'),
			f1: true,
		});
	}
	run(accessor: ServicesAccessor): Promise<void> { return focusPulse(accessor); }
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
			title: localize({ key: 'pulseAI.openSettings', comment: ['PulseAI product settings'] }, 'Pulse Settings'),
			f1: true,
			icon: Codicon.settingsGear,
			menu: [{ id: PULSE_AI_MENU_ID, group: '4_settings', order: 1 }],
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		await accessor.get(ICommandService).executeCommand('workbench.action.openSettings', 'pulseai');
	}
});
