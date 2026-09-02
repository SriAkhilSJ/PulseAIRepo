/*---------------------------------------------------------------------------------------------
 * Native first-party Pulse Agent view. The portable renderer mounts into `pulseai-render-root`.
 *--------------------------------------------------------------------------------------------*/

import * as DOM from '../../../../base/browser/dom.js';
import { addDisposableListener } from '../../../../base/browser/dom.js';
import { toDisposable } from '../../../../base/common/lifecycle.js';
import { timeout } from '../../../../base/common/async.js';
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

const DEFAULT_COPILOT_WEBVIEW_URL = 'http://localhost:5173';

function paragraph(text: string): HTMLParagraphElement {
	const node = DOM.$<HTMLParagraphElement>('p');
	node.textContent = text;
	return node;
}

export class PulseAIViewPane extends ViewPane {
	private copilotSlot: HTMLElement | undefined;
	private copilotWebview: HTMLIFrameElement | undefined;
	private pulseBody: HTMLElement | undefined;

	constructor(
		options: IViewPaneOptions,
		@IKeybindingService keybindingService: IKeybindingService,
		@IContextMenuService contextMenuService: IContextMenuService,
		@IConfigurationService private readonly pulseConfigurationService: IConfigurationService,
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
			pulseConfigurationService,
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
		this.pulseBody.style.display = 'flex';
		this.pulseBody.style.flexDirection = 'column';
		this.pulseBody.style.minHeight = '0';
		const root = DOM.append(this.pulseBody, DOM.$('.pulseai-render-root'));
		root.style.flex = '1 1 auto';
		root.style.minHeight = '0';
		// In a 380px-wide auxiliary bar, stacking two full agent surfaces at 50% each
		// gives you half a transcript and half a scrollbox. The pane now shows one at a
		// time; both stay mounted, so switching costs no remount and the native view's
		// scroll position survives the trip.
		const tabs = DOM.append(this.pulseBody, DOM.$('.pulseai-view-tabs'));
		const nativeTab = DOM.append(tabs, DOM.$('button.pulseai-view-tab')) as HTMLButtonElement;
		nativeTab.type = 'button';
		nativeTab.textContent = 'Agent';
		const copilotTab = DOM.append(tabs, DOM.$('button.pulseai-view-tab')) as HTMLButtonElement;
		copilotTab.type = 'button';
		copilotTab.textContent = 'CopilotKit';
		copilotTab.disabled = this.copilotWebview === undefined;
		const show = (surface: 'native' | 'copilot') => {
			root.style.display = surface === 'native' ? '' : 'none';
			if (this.copilotSlot) { this.copilotSlot.style.display = surface === 'copilot' ? '' : 'none'; }
			nativeTab.classList.toggle('is-active', surface === 'native');
			copilotTab.classList.toggle('is-active', surface === 'copilot');
			nativeTab.setAttribute('aria-current', String(surface === 'native'));
			copilotTab.setAttribute('aria-current', String(surface === 'copilot'));
			tabs.classList.toggle('is-hidden', this.copilotWebview === undefined);
		};
		this._register(addDisposableListener(nativeTab, 'click', () => show('native')));
		this._register(addDisposableListener(copilotTab, 'click', () => show('copilot')));
		root.dataset.surface = 'agent';
		root.setAttribute('role', 'region');
		root.setAttribute('aria-label', 'Pulse Agent');
		this._register(this.pulseAIRendererService.mount(root, 'agent'));
		this.renderCopilotWebview(this.pulseBody);
		show('native');
	}

	/**
	 * The CopilotKit React SPA (pulse-webview) under the native renderer.
	 *
	 * This used to be `src = 'http://localhost:5173'`, which only ever worked when a
	 * `npm run dev` happened to be listening on that port: everywhere else -- a
	 * packaged build, a second machine, a remote/WSL window where `localhost` is the
	 * client, or simply forgetting the dev server -- the pane showed an empty frame
	 * with no explanation, and the native renderer above it kept claiming 50% of the
	 * pane for nothing. URL, size and the surface itself are now settings, and an
	 * unreachable URL says so in the pane instead of rendering blank.
	 */
	private renderCopilotWebview(parent: HTMLElement): void {
		const cfg = this.pulseConfigurationService;
		if (cfg.getValue<boolean>('pulseai.copilotWebview.enabled') === false) {
			return; // no tab, no iframe: the native Agent view owns the whole pane
		}
		const url = (cfg.getValue<string>('pulseai.copilotWebview.url') || DEFAULT_COPILOT_WEBVIEW_URL).trim();
		const share = Math.min(85, Math.max(10, Number(cfg.getValue<number>('pulseai.copilotWebview.height')) || 50));

		const slot = DOM.append(parent, DOM.$('.pulseai-copilot-slot'));
		this.copilotSlot = slot;
		slot.style.flex = `1 1 ${share}%`;
		slot.style.minHeight = '120px';
		slot.style.display = 'flex';
		slot.style.flexDirection = 'column';

		// Typed as the frame it is: `showUnreachable` reads `contentWindow`/`src` off it, and a
		// plain HTMLElement there is a lie the compiler would otherwise let us ship.
		const frame = DOM.append(slot, DOM.$<HTMLIFrameElement>('iframe.pulseai-copilot-webview'));
		frame.setAttribute('title', 'Pulse CopilotKit');
		frame.style.width = '100%';
		frame.style.height = '100%';
		frame.style.flex = '1 1 auto';
		frame.style.border = 'none';
		frame.style.display = 'block';
		frame.setAttribute('src', url);
		this.copilotWebview = frame;

		// A refused or hanging connection fires no event an extension may read (by
		// design), so "nothing loaded within N ms" is the only honest signal here. The
		// frame is kept rather than removed: a cold `vite` dev server that eventually
		// answers still resolves into this DOM, and the notice sits under it.
		let settled = false;
		this._register(addDisposableListener(frame, 'load', () => { settled = true; }));
		this._register(toDisposable(() => { settled = true; }));
		let attempt = 0;
		const arm = () => {
			attempt++;
			const watchdog = timeout(12_000);
			this._register(toDisposable(() => watchdog.cancel()));
			void watchdog.then(() => {
				if (settled || !frame.isConnected) { return; }
				this.showUnreachable(slot, frame, url, attempt, () => arm());
			});
		};
		arm();
	}

	private showUnreachable(slot: HTMLElement, frame: HTMLIFrameElement, url: string, attempt: number, rearm: () => void): void {
		if (slot.querySelector('.pulseai-copilot-unreachable')) { return; }
		const notice = DOM.append(slot, DOM.$('.pulseai-copilot-unreachable'));
		notice.append(paragraph(attempt > 1
			? `Pulse CopilotKit is still not answering at ${url}.`
			: `Pulse CopilotKit is not answering at ${url}.`));
		notice.append(paragraph('Start it (`cd pulse-webview && npm run dev`), point `pulseai.copilotWebview.url` at a build you serve yourself, or set `pulseai.copilotWebview.enabled` to false to give the whole pane to the native Agent view.'));
		const retry = DOM.append(notice, DOM.$('button.pulseai-button.pulseai-button-secondary')) as HTMLButtonElement;
		retry.type = 'button';
		retry.textContent = 'Reload';
		this._register(addDisposableListener(retry, 'click', () => {
			notice.remove();
			frame.setAttribute('src', url);
			rearm();
		}));
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
