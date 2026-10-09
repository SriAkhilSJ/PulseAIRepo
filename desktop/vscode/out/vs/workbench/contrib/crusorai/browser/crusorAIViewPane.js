/*---------------------------------------------------------------------------------------------
 * Native first-party Crusor Agent view. The portable renderer mounts into `crusorai-render-root`.
 *--------------------------------------------------------------------------------------------*/
var __extends = (this && this.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();
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
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { ICrusorAIPreviewService } from './crusorAIPreviewService.js';
import { installCrusorTheme } from './crusorTheme.js';
/**
 * Where the built CopilotKit SPA lands inside the app. `npm run build` in `crusor-webview`
 * writes it here (see its `postbuild`), and the fork's own copy step carries it into `out/`.
 *
 * Loading it from the workbench's OWN origin is the whole point: the workbench document's CSP is
 * `frame-src 'self' vscode-webview:`, so a `http://localhost:5173` iframe is refused before the dev
 * server is ever asked -- no domain, no port, no proxy needed, and a packaged build or a remote
 * editor window behaves the same because the files travel with the app.
 */
var LOCAL_SPA_RESOURCE = 'vs/workbench/contrib/crusorai/browser/media/crusorai-spa/index.html';
var DEFAULT_COPILOT_WEBVIEW_URL = 'local';
function paragraph(text) {
    var node = DOM.$('p');
    node.textContent = text;
    return node;
}
var CrusorAIViewPane = /** @class */ (function (_super) {
    __extends(CrusorAIViewPane, _super);
    function CrusorAIViewPane(options, keybindingService, contextMenuService, crusorConfigurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, crusorThemeService, hoverService, crusorAIRendererService, crusorAIPreviewService) {
        var _this = _super.call(this, options, keybindingService, contextMenuService, crusorConfigurationService, contextKeyService, viewDescriptorService, instantiationService, openerService, crusorThemeService, hoverService) || this;
        _this.crusorConfigurationService = crusorConfigurationService;
        _this.crusorThemeService = crusorThemeService;
        _this.crusorAIRendererService = crusorAIRendererService;
        _this.crusorAIPreviewService = crusorAIPreviewService;
        /** Latched once the target goes down: only target-ok (or a fresh open) clears the red tab. */
        _this.previewDownLatch = false;
        return _this;
    }
    CrusorAIViewPane.prototype.renderBody = function (container) {
        var _this = this;
        _super.prototype.renderBody.call(this, container);
        this.crusorBody = DOM.append(container, DOM.$('.crusorai-view'));
        // Semantic palette is derived from the LIVE theme (hermes seed→token
        // machine) and re-derived on every theme change — never hardcoded.
        this._register(installCrusorTheme(this.crusorBody, this.crusorThemeService));
        this.crusorBody.style.display = 'flex';
        this.crusorBody.style.flexDirection = 'column';
        this.crusorBody.style.minHeight = '0';
        var root = DOM.append(this.crusorBody, DOM.$('.crusorai-render-root'));
        root.style.flex = '1 1 auto';
        root.style.minHeight = '0';
        // In a 380px-wide auxiliary bar, stacking two full agent surfaces at 50% each
        // gives you half a transcript and half a scrollbox. The pane now shows one at a
        // time; both stay mounted, so switching costs no remount and the native view's
        // scroll position survives the trip.
        var tabs = DOM.append(this.crusorBody, DOM.$('.crusorai-view-tabs'));
        var nativeTab = DOM.append(tabs, DOM.$('button.crusorai-view-tab'));
        nativeTab.type = 'button';
        nativeTab.textContent = 'Agent';
        var webviewTab = DOM.append(tabs, DOM.$('button.crusorai-view-tab'));
        webviewTab.type = 'button';
        webviewTab.textContent = 'Webview';
        webviewTab.disabled = this.webviewFrame === undefined;
        // "Preview is available" lives in the Agent UI and only lights up when the session actually
        // built something previewable — a dev server it started, or an HTML file it wrote.
        var previewButton = DOM.append(tabs, DOM.$('button.crusorai-view-tab.crusorai-preview-open'));
        previewButton.type = 'button';
        previewButton.textContent = 'Preview';
        previewButton.disabled = true;
        previewButton.dataset.available = 'false';
        var applyPreviewAvailability = function () {
            var _a;
            var availability = _this.crusorAIPreviewService.availability;
            var windowOpen = _this.crusorAIPreviewService.isWindowOpen;
            var health = _this.crusorAIPreviewService.health;
            // The chip tells the truth in three states: green "Preview · OPEN" only
            // while the framed app is verified live; red "Preview · DOWN" when the
            // target refuses (clicking it ASKS THE AGENT to relaunch instead of
            // opening a dead window); plain "Preview" when nothing exists yet.
            var down = health === 'down' || (windowOpen && health === 'starting' && _this.previewDownLatch);
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
                        ? "Open the preview window \u2014 ".concat((_a = availability.label) !== null && _a !== void 0 ? _a : 'the UI Crusor built')
                        : 'No preview yet: when Crusor builds UI or starts a dev server, it appears here.';
        };
        this._register(this.crusorAIPreviewService.onDidChangeAvailability(function () { return applyPreviewAvailability(); }));
        this._register(this.crusorAIPreviewService.onDidChangeWindow(function () { return applyPreviewAvailability(); }));
        this._register(this.crusorAIPreviewService.onDidChangeHealth(function () { return applyPreviewAvailability(); }));
        // Down is latched so a transient starting-state flicker can never
        // un-red an outage before target-ok proves recovery; opening clears it.
        this._register(this.crusorAIPreviewService.onDidChangeHealth(function (health) {
            if (health === 'down') {
                _this.previewDownLatch = true;
            }
            if (health === 'live' || health === 'closed') {
                _this.previewDownLatch = false;
            }
            applyPreviewAvailability();
        }));
        this._register(addDisposableListener(previewButton, 'click', function () {
            if (_this.crusorAIPreviewService.health === 'down') {
                // Red tab: the agent restarts the dev server and re-opens the
                // preview — the user never opens a dead window by hand.
                void _this.crusorAIPreviewService.requestRelaunch();
                return;
            }
            void _this.crusorAIPreviewService.openPreview();
        }));
        applyPreviewAvailability();
        var show = function (surface) {
            root.style.display = surface === 'native' ? '' : 'none';
            if (_this.webviewSlot) {
                _this.webviewSlot.style.display = surface === 'webview' ? '' : 'none';
            }
            nativeTab.classList.toggle('is-active', surface === 'native');
            webviewTab.classList.toggle('is-active', surface === 'webview');
            nativeTab.setAttribute('aria-current', String(surface === 'native'));
            webviewTab.setAttribute('aria-current', String(surface === 'webview'));
            // Only the two tab BUTTONS hide when there is a single surface: the row also carries the
            // "a preview is available" chip, which must stay visible with the CopilotKit webview off.
            nativeTab.classList.toggle('is-hidden', _this.webviewFrame === undefined);
            webviewTab.classList.toggle('is-hidden', _this.webviewFrame === undefined);
        };
        this._register(addDisposableListener(nativeTab, 'click', function () { return show('native'); }));
        this._register(addDisposableListener(webviewTab, 'click', function () { return show('webview'); }));
        root.dataset.surface = 'agent';
        root.setAttribute('role', 'region');
        root.setAttribute('aria-label', 'Crusor Agent');
        this._register(this.crusorAIRendererService.mount(root, 'agent'));
        this.renderCopilotWebview(this.crusorBody);
        show('native');
    };
    /**
     * The CopilotKit React SPA (crusor-webview) under the native renderer.
     *
     * This used to be `src = 'http://localhost:5173'`, which only ever worked when a
     * `npm run dev` happened to be listening on that port: everywhere else -- a
     * packaged build, a second machine, a remote/WSL window where `localhost` is the
     * client, or simply forgetting the dev server -- the pane showed an empty frame
     * with no explanation, and the native renderer above it kept claiming 50% of the
     * pane for nothing. URL, size and the surface itself are now settings, and an
     * unreachable URL says so in the pane instead of rendering blank.
     */
    CrusorAIViewPane.prototype.renderCopilotWebview = function (parent) {
        var _this = this;
        var cfg = this.crusorConfigurationService;
        if (cfg.getValue('crusorai.copilotWebview.enabled') === false) {
            return; // no tab, no iframe: the native Agent view owns the whole pane
        }
        var configured = (cfg.getValue('crusorai.copilotWebview.url') || DEFAULT_COPILOT_WEBVIEW_URL).trim();
        var isLocal = configured === '' || configured.toLowerCase() === 'local';
        // `asBrowserUri`, NOT `asFileUri` (field log 2026-09-05: "Not allowed to
        // load local resource"): the native workbench document itself is served
        // from `vscode-file://vscode-app/<appRoot>/out/` (workbench.ts baseUrl),
        // and Chromium refuses a raw `file://` iframe from that origin. The
        // browser URI is the document's OWN origin, so frame-src 'self' admits
        // it, and it degrades to the same file URI in pure-browser contexts.
        // Typed `as never`: the SPA directory is copied into out/ after the
        // build, so it can't be in the build-time union of app resource paths.
        var url = isLocal ? FileAccess.asBrowserUri(LOCAL_SPA_RESOURCE).toString(true) : configured;
        var share = Math.min(85, Math.max(10, Number(cfg.getValue('crusorai.copilotWebview.height')) || 50));
        var slot = DOM.append(parent, DOM.$('.crusorai-webview-slot'));
        this.webviewSlot = slot;
        slot.style.flex = "1 1 ".concat(share, "%");
        slot.style.minHeight = '120px';
        slot.style.display = 'flex';
        slot.style.flexDirection = 'column';
        // Typed as the frame it is: `showUnreachable` reads `contentWindow`/`src` off it, and a
        // plain HTMLElement there is a lie the compiler would otherwise let us ship.
        var frame = DOM.append(slot, DOM.$('iframe.crusorai-webview-webview'));
        frame.setAttribute('title', 'Crusor CopilotKit');
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
        var settled = false;
        this._register(addDisposableListener(frame, 'load', function () { settled = true; }));
        this._register(toDisposable(function () { settled = true; }));
        var attempt = 0;
        var arm = function () {
            attempt++;
            var watchdog = timeout(12000);
            _this._register(toDisposable(function () { return watchdog.cancel(); }));
            void watchdog.then(function () {
                if (settled || !frame.isConnected) {
                    return;
                }
                _this.showUnreachable(slot, frame, url, attempt, isLocal, function () { return arm(); });
            });
        };
        arm();
    };
    CrusorAIViewPane.prototype.showUnreachable = function (slot, frame, url, attempt, isLocal, rearm) {
        if (slot.querySelector('.crusorai-webview-unreachable')) {
            return;
        }
        var notice = DOM.append(slot, DOM.$('.crusorai-webview-unreachable'));
        notice.append(paragraph(attempt > 1
            ? "Crusor CopilotKit is still not answering at ".concat(url, ".")
            : "Crusor CopilotKit is not answering at ".concat(url, ".")));
        notice.append(paragraph(isLocal
            ? 'Nothing is at that path yet: build the SPA once (`cd crusor-webview && npm run build`), which writes it into the app and needs no server. If you would rather not use this surface at all, set `crusorai.copilotWebview.enabled` to false and the native Agent view takes the whole pane.'
            : "Nothing loaded from ".concat(url, ". Note the workbench CSP frames only 'self' and vscode-webview:, so an http(s) URL here is refused before it is asked -- build the SPA and set crusorai.copilotWebview.url to \"local\", or point it at a build you serve yourself only if you have added that origin to the frame policy.")));
        var retry = DOM.append(notice, DOM.$('button.crusorai-button.crusorai-button-secondary'));
        retry.type = 'button';
        retry.textContent = 'Reload';
        this._register(addDisposableListener(retry, 'click', function () {
            notice.remove();
            frame.setAttribute('src', url);
            rearm();
        }));
    };
    CrusorAIViewPane.prototype.layoutBody = function (height, width) {
        _super.prototype.layoutBody.call(this, height, width);
        if (!this.crusorBody) {
            return;
        }
        this.crusorBody.style.width = "".concat(width, "px");
        this.crusorBody.style.height = "".concat(height, "px");
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
    return CrusorAIViewPane;
}(ViewPane));
export { CrusorAIViewPane };
