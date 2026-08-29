/*---------------------------------------------------------------------------------------------
 * Native first-party Pulse Agent view. The portable renderer mounts into `pulseai-render-root`.
 *--------------------------------------------------------------------------------------------*/

import * as DOM from '../../../../base/browser/dom.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IViewPaneOptions, ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IPulseAIRendererService } from '../common/pulseAIRendererService.js';

export class PulseAIViewPane extends ViewPane {
	private pulseBody: HTMLElement | undefined;

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService configurationService: IConfigurationService,
		@IContextKeyService contextKeyService: IContextKeyService,
		@IViewDescriptorService viewDescriptorService: IViewDescriptorService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IOpenerService openerService: IOpenerService,
		@IThemeService themeService: IThemeService,
		@IHoverService hoverService: IHoverService,
		@IPulseAIRendererService private readonly pulseAIRendererService: IPulseAIRendererService,
	) {
		super(
			options,
			keybindingService,
			contextMenuService,
			configurationService,
			contextKeyService,
			viewDescriptorService,
			instantiationService,
			openerService,
			themeService,
			hoverService,
		);
	}

	protected override renderBody(container: HTMLElement): void {
		super.renderBody(container);
		this.pulseBody = DOM.append(container, DOM.$('.pulseai-view'));
		const root = DOM.append(this.pulseBody, DOM.$('.pulseai-render-root'));
		root.dataset.surface = 'agent';
		root.setAttribute('role', 'region');
		root.setAttribute('aria-label', 'Pulse Agent');
		this._register(this.pulseAIRendererService.mount(root, 'agent'));
		// React SPA embedded as FIXED right-side webview (CopilotKit + LangGraph)
		// Single Pulse Agent via AuxiliaryBar canMoveView:false (contribution.ts)
		const webview = DOM.append(this.pulseBody, DOM.$('iframe.pulseai-copilot-webview'));
		webview.setAttribute('title', 'Pulse CopilotKit');
		webview.setAttribute('src', 'http://localhost:5173');
		webview.style.width = '100%';
		webview.style.height = '50%';
		webview.style.border = 'none';
		webview.style.display = 'block';
	}

	protected override layoutBody(height: number, width: number): void {
		super.layoutBody(height, width);
		if (!this.pulseBody) {
			return;
		}
		this.pulseBody.style.width = `${width}px`;
		this.pulseBody.style.height = `${height}px`;
	}
}
