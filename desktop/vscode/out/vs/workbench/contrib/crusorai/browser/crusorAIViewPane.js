/*---------------------------------------------------------------------------------------------
 * Native first-party Crusor Agent view. The portable renderer mounts into `crusorai-render-root`.
 *--------------------------------------------------------------------------------------------*/
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import * as DOM from '../../../../base/browser/dom.js';
import { addDisposableListener } from '../../../../base/browser/dom.js';
import { IHoverService } from '../../../../platform/hover/browser/hover.js';
import { IKeybindingService } from '../../../../platform/keybinding/common/keybinding.js';
import { IContextMenuService } from '../../../../platform/contextview/browser/contextView.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IContextKeyService } from '../../../../platform/contextkey/common/contextkey.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { ICrusorAIPreviewService } from './crusorAIPreviewService.js';
import { installCrusorTheme } from './crusorTheme.js';
let CrusorAIViewPane = class CrusorAIViewPane extends ViewPane {
    constructor(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, crusorThemeService, hoverService, crusorAIRendererService, crusorAIPreviewService) {
        super(options, keybindingService, contextMenuService, configurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, crusorThemeService, hoverService);
        this.crusorThemeService = crusorThemeService;
        this.crusorAIRendererService = crusorAIRendererService;
        this.crusorAIPreviewService = crusorAIPreviewService;
        /** Latched once the target goes down: only target-ok (or a fresh open) clears the red tab. */
        this.previewDownLatch = false;
    }
    renderBody(container) {
        super.renderBody(container);
        this.crusorBody = DOM.append(container, DOM.$('.crusorai-view'));
        // Semantic palette is derived from the LIVE theme (hermes seed→token
        // machine) and re-derived on every theme change — never hardcoded.
        this._register(installCrusorTheme(this.crusorBody, this.crusorThemeService));
        this.crusorBody.style.display = 'flex';
        this.crusorBody.style.flexDirection = 'column';
        this.crusorBody.style.minHeight = '0';
        const root = DOM.append(this.crusorBody, DOM.$('.crusorai-render-root'));
        root.style.flex = '1 1 auto';
        root.style.minHeight = '0';
        // The native renderer is the pane's only surface (the CopilotKit
        // webview lab and its iframe host were stripped 2026-10-21). The tab
        // row remains because it also carries the Preview chip.
        const tabs = DOM.append(this.crusorBody, DOM.$('.crusorai-view-tabs'));
        const nativeTab = DOM.append(tabs, DOM.$('button.crusorai-view-tab'));
        nativeTab.type = 'button';
        nativeTab.textContent = 'Agent';
        nativeTab.classList.toggle('is-active', true);
        nativeTab.setAttribute('aria-current', 'true');
        // "Preview is available" lives in the Agent UI and only lights up when the session actually
        // built something previewable — a dev server it started, or an HTML file it wrote.
        const previewButton = DOM.append(tabs, DOM.$('button.crusorai-view-tab.crusorai-preview-open'));
        previewButton.type = 'button';
        previewButton.textContent = 'Preview';
        previewButton.disabled = true;
        previewButton.dataset.available = 'false';
        const applyPreviewAvailability = () => {
            const availability = this.crusorAIPreviewService.availability;
            const windowOpen = this.crusorAIPreviewService.isWindowOpen;
            const health = this.crusorAIPreviewService.health;
            // The chip tells the truth in three states: green "Preview · OPEN" only
            // while the framed app is verified live; red "Preview · DOWN" when the
            // target refuses (clicking it ASKS THE AGENT to relaunch instead of
            // opening a dead window); plain "Preview" when nothing exists yet.
            const down = health === 'down' || (windowOpen && health === 'starting' && this.previewDownLatch);
            previewButton.textContent = down ? 'Preview · DOWN' : windowOpen ? 'Preview · OPEN' : 'Preview';
            previewButton.dataset.open = String(windowOpen);
            previewButton.dataset.down = String(down);
            previewButton.disabled = !availability.available && !windowOpen && !down;
            previewButton.dataset.available = String(availability.available || windowOpen || down);
            previewButton.title = down
                ? 'The preview target is DOWN — click and Crusor restarts the dev server and re-opens the preview.'
                : windowOpen
                    ? health === 'starting'
                        ? 'The preview window is open and loading the framed app…'
                        : 'The preview window is open on your desktop — click to bring it forward'
                    : availability.available
                        ? `Open the preview window — ${availability.label ?? 'the UI Crusor built'}`
                        : 'No preview yet: when Crusor builds UI or starts a dev server, it appears here.';
        };
        this._register(this.crusorAIPreviewService.onDidChangeAvailability(() => applyPreviewAvailability()));
        this._register(this.crusorAIPreviewService.onDidChangeWindow(() => applyPreviewAvailability()));
        this._register(this.crusorAIPreviewService.onDidChangeHealth(() => applyPreviewAvailability()));
        // Down is latched so a transient starting-state flicker can never
        // un-red an outage before target-ok proves recovery; opening clears it.
        this._register(this.crusorAIPreviewService.onDidChangeHealth(health => {
            if (health === 'down') {
                this.previewDownLatch = true;
            }
            if (health === 'live' || health === 'closed') {
                this.previewDownLatch = false;
            }
            applyPreviewAvailability();
        }));
        this._register(addDisposableListener(previewButton, 'click', () => {
            if (this.crusorAIPreviewService.health === 'down') {
                // Red tab: the agent restarts the dev server and re-opens the
                // preview — the user never opens a dead window by hand.
                void this.crusorAIPreviewService.requestRelaunch();
                return;
            }
            void this.crusorAIPreviewService.openPreview();
        }));
        applyPreviewAvailability();
        root.dataset.surface = 'agent';
        root.setAttribute('role', 'region');
        root.setAttribute('aria-label', 'Crusor Agent');
        this._register(this.crusorAIRendererService.mount(root, 'agent'));
    }
    layoutBody(height, width) {
        super.layoutBody(height, width);
        if (!this.crusorBody) {
            return;
        }
        this.crusorBody.style.width = `${width}px`;
        this.crusorBody.style.height = `${height}px`;
    }
};
CrusorAIViewPane = __decorate([
    __param(1, IKeybindingService),
    __param(2, IContextMenuService),
    __param(3, IConfigurationService),
    __param(4, IContextKeyService),
    __param(5, IViewDescriptorService),
    __param(6, IInstantiationService),
    __param(7, IOpenerService),
    __param(8, IThemeService),
    __param(9, IHoverService),
    __param(10, ICrusorAIRendererService),
    __param(11, ICrusorAIPreviewService)
], CrusorAIViewPane);
export { CrusorAIViewPane };
