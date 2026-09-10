/*---------------------------------------------------------------------------------------------
 * Native first-party Pulse Agent view. The portable renderer mounts into `pulseai-render-root`.
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
import { FileAccess } from '../../../../base/common/network.js';
import { ViewPane } from '../../../browser/parts/views/viewPane.js';
import { IViewDescriptorService } from '../../../common/views.js';
import { IPulseAIRendererService } from '../common/pulseAIRendererService.js';
import { installPulseTheme } from './pulseTheme.js';
/**
 * Where the built CopilotKit SPA lands inside the app. `npm run build` in `pulse-webview`
 * writes it here (see its `postbuild`), and the fork's own copy step carries it into `out/`.
 *
 * Loading it from the workbench's OWN origin is the whole point: the workbench document's CSP is
 * `frame-src 'self' vscode-webview:`, so a `http://localhost:5173` iframe is refused before the dev
 * server is ever asked -- no domain, no port, no proxy needed, and a packaged build or a remote
 * editor window behaves the same because the files travel with the app.
 */
const LOCAL_SPA_RESOURCE = 'vs/workbench/contrib/pulseai/browser/media/pulseai-spa/index.html';
const DEFAULT_COPILOT_WEBVIEW_URL = 'local';
function paragraph(text) {
    const node = DOM.$('p');
    node.textContent = text;
    return node;
}
let PulseAIViewPane = class PulseAIViewPane extends ViewPane {
    constructor(options, keybindingService, contextMenuService, pulseConfigurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, pulseThemeService, hoverService, pulseAIRendererService) {
        super(options, keybindingService, contextMenuService, pulseConfigurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, pulseThemeService, hoverService);
        this.pulseConfigurationService = pulseConfigurationService;
        this.pulseThemeService = pulseThemeService;
        this.pulseAIRendererService = pulseAIRendererService;
    }
    renderBody(container) {
        super.renderBody(container);
        this.pulseBody = DOM.append(container, DOM.$('.pulseai-view'));
        // Semantic palette is derived from the LIVE theme (hermes seed→token
        // machine) and re-derived on every theme change — never hardcoded.
        this._register(installPulseTheme(this.pulseBody, this.pulseThemeService));
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
        const nativeTab = DOM.append(tabs, DOM.$('button.pulseai-view-tab'));
        nativeTab.type = 'button';
        nativeTab.textContent = 'Agent';
        const webviewTab = DOM.append(tabs, DOM.$('button.pulseai-view-tab'));
        webviewTab.type = 'button';
        webviewTab.textContent = 'Webview';
        webviewTab.disabled = this.webviewFrame === undefined;
        const show = (surface) => {
            root.style.display = surface === 'native' ? '' : 'none';
            if (this.webviewSlot) {
                this.webviewSlot.style.display = surface === 'webview' ? '' : 'none';
            }
            nativeTab.classList.toggle('is-active', surface === 'native');
            webviewTab.classList.toggle('is-active', surface === 'webview');
            nativeTab.setAttribute('aria-current', String(surface === 'native'));
            webviewTab.setAttribute('aria-current', String(surface === 'webview'));
            tabs.classList.toggle('is-hidden', this.webviewFrame === undefined);
        };
        this._register(addDisposableListener(nativeTab, 'click', () => show('native')));
        this._register(addDisposableListener(webviewTab, 'click', () => show('webview')));
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
    renderCopilotWebview(parent) {
        const cfg = this.pulseConfigurationService;
        if (cfg.getValue('pulseai.copilotWebview.enabled') === false) {
            return; // no tab, no iframe: the native Agent view owns the whole pane
        }
        const configured = (cfg.getValue('pulseai.copilotWebview.url') || DEFAULT_COPILOT_WEBVIEW_URL).trim();
        const isLocal = configured === '' || configured.toLowerCase() === 'local';
        // `asBrowserUri`, NOT `asFileUri` (field log 2026-09-05: "Not allowed to
        // load local resource"): the native workbench document itself is served
        // from `vscode-file://vscode-app/<appRoot>/out/` (workbench.ts baseUrl),
        // and Chromium refuses a raw `file://` iframe from that origin. The
        // browser URI is the document's OWN origin, so frame-src 'self' admits
        // it, and it degrades to the same file URI in pure-browser contexts.
        // Typed `as never`: the SPA directory is copied into out/ after the
        // build, so it can't be in the build-time union of app resource paths.
        const url = isLocal ? FileAccess.asBrowserUri(LOCAL_SPA_RESOURCE).toString(true) : configured;
        const share = Math.min(85, Math.max(10, Number(cfg.getValue('pulseai.copilotWebview.height')) || 50));
        const slot = DOM.append(parent, DOM.$('.pulseai-webview-slot'));
        this.webviewSlot = slot;
        slot.style.flex = `1 1 ${share}%`;
        slot.style.minHeight = '120px';
        slot.style.display = 'flex';
        slot.style.flexDirection = 'column';
        // Typed as the frame it is: `showUnreachable` reads `contentWindow`/`src` off it, and a
        // plain HTMLElement there is a lie the compiler would otherwise let us ship.
        const frame = DOM.append(slot, DOM.$('iframe.pulseai-webview-webview'));
        frame.setAttribute('title', 'Pulse CopilotKit');
        frame.style.width = '100%';
        frame.style.height = '100%';
        frame.style.flex = '1 1 auto';
        frame.style.border = 'none';
        frame.style.display = 'block';
        frame.setAttribute('src', url);
        this.webviewFrame = frame;
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
                if (settled || !frame.isConnected) {
                    return;
                }
                this.showUnreachable(slot, frame, url, attempt, isLocal, () => arm());
            });
        };
        arm();
    }
    showUnreachable(slot, frame, url, attempt, isLocal, rearm) {
        if (slot.querySelector('.pulseai-webview-unreachable')) {
            return;
        }
        const notice = DOM.append(slot, DOM.$('.pulseai-webview-unreachable'));
        notice.append(paragraph(attempt > 1
            ? `Pulse CopilotKit is still not answering at ${url}.`
            : `Pulse CopilotKit is not answering at ${url}.`));
        notice.append(paragraph(isLocal
            ? 'Nothing is at that path yet: build the SPA once (`cd pulse-webview && npm run build`), which writes it into the app and needs no server. If you would rather not use this surface at all, set `pulseai.copilotWebview.enabled` to false and the native Agent view takes the whole pane.'
            : `Nothing loaded from ${url}. Note the workbench CSP frames only 'self' and vscode-webview:, so an http(s) URL here is refused before it is asked -- build the SPA and set pulseai.copilotWebview.url to "local", or point it at a build you serve yourself only if you have added that origin to the frame policy.`));
        const retry = DOM.append(notice, DOM.$('button.pulseai-button.pulseai-button-secondary'));
        retry.type = 'button';
        retry.textContent = 'Reload';
        this._register(addDisposableListener(retry, 'click', () => {
            notice.remove();
            frame.setAttribute('src', url);
            rearm();
        }));
    }
    layoutBody(height, width) {
        super.layoutBody(height, width);
        if (!this.pulseBody) {
            return;
        }
        this.pulseBody.style.width = `${width}px`;
        this.pulseBody.style.height = `${height}px`;
    }
};
PulseAIViewPane = __decorate([
    __param(1, IKeybindingService),
    __param(2, IContextMenuService),
    __param(3, IConfigurationService),
    __param(4, IContextKeyService),
    __param(5, IViewDescriptorService),
    __param(6, IInstantiationService),
    __param(7, IOpenerService),
    __param(8, IThemeService),
    __param(9, IHoverService),
    __param(10, IPulseAIRendererService)
], PulseAIViewPane);
export { PulseAIViewPane };
