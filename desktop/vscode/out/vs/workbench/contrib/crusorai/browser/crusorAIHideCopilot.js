/*---------------------------------------------------------------------------------------------
 * Hide Copilot's first-run UI surfaces when Crusor is the primary AI.
 *
 * Why this exists:
 *
 *   Setting `chat.disableAIFeatures: true` in configurationDefaults hides
 *   most of Copilot once the ChatEntitlementService finishes its async
 *   entitlement resolution and flips ChatContextKeys.Setup.hidden to true.
 *   But that flip happens AFTER the workbench paints, so on first boot /
 *   empty window / before sign-in users still see:
 *     - a CHAT tab in the auxiliary bar next to Crusor,
 *     - an "Open Chat Ctrl+Alt+I" entry in the empty-editor watermark,
 *     - a Copilot sparkle / sign-in affordance in the title bar.
 *
 *   The watermark gates on context key `chatSetupHidden`
 *   (editorGroupWatermark.ts:34), the CHAT view gates on
 *   `ChatContextKeys.Setup.hidden.negate()` (chatParticipant.contribution.ts:71),
 *   and the title-bar agent widget gates on `chatIsEnabled`.
 *
 *   We do NOT edit Copilot source (standing project rule: preserve
 *   contrib/chat and extensions/copilot as the integration guide). Instead
 *   this Crusor workbench contribution forces those context keys to the
 *   "hidden" state from LifecyclePhase.Starting onward, and calls
 *   IChatEntitlementService.setForceHidden(true) so Copilot's own gating
 *   agrees. Reversible by flipping `crusorai.hideBuiltInCopilotUI` to false.
 *
 *   The chat view's `when` clause has 3 OR paths:
 *     (a) chatSetupHidden=false AND chatSetupDisabledInWorkspace=false
 *     (b) chatPanelParticipantRegistered=true
 *     (c) chatExtensionInvalid=true
 *   Context key forcing kills (a), but Copilot's agent registration sets
 *   (b) to true asynchronously, so we also deregister the view from the
 *   container to definitively remove the CHAT tab.
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
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
var _a;
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { IChatEntitlementService } from '../../../../workbench/services/chat/common/chatEntitlementService.js';
import { Extensions as ViewExtensions } from '../../../common/views.js';
var SETTING_ID = 'crusorai.hideBuiltInCopilotUI';
// Register the setting so it shows up under Crusor Settings and is
// overridable per-user.
Registry.as(ConfigurationExtensions.Configuration).registerConfiguration({
    id: 'crusorai',
    title: localize2('crusorAI.configuration.title', 'CrusorAI').value,
    type: 'object',
    properties: (_a = {},
        _a[SETTING_ID] = {
            type: 'boolean',
            default: true,
            scope: ConfigurationScope.APPLICATION,
            description: localize2('crusorai.hideBuiltInCopilotUI.description', 'Hide the built-in GitHub Copilot UI (CHAT tab, empty-editor "Open Chat" watermark, title-bar Copilot icon, Copilot sign-in prompts). Crusor is the primary AI in this IDE; Copilot source and extensions remain installed and can be re-enabled by turning this off.').value,
        },
        _a),
});
var CrusorHideCopilotContribution = /** @class */ (function () {
    function CrusorHideCopilotContribution(contextKeyService, configurationService, chatEntitlementService) {
        var _this = this;
        this.configurationService = configurationService;
        this.chatEntitlementService = chatEntitlementService;
        this.hiddenKey = new RawContextKey('chatSetupHidden', false).bindTo(contextKeyService);
        this.installedKey = new RawContextKey('chatSetupInstalled', false).bindTo(contextKeyService);
        this.disabledKey = new RawContextKey('chatSetupDisabled', false).bindTo(contextKeyService);
        this.chatEnabledKey = new RawContextKey('chatIsEnabled', true).bindTo(contextKeyService);
        this.apply();
        this.deregisterChatView();
        this.configurationService.onDidChangeConfiguration(function (e) {
            if (e.affectsConfiguration(SETTING_ID) || e.affectsConfiguration('chat.disableAIFeatures')) {
                _this.apply();
            }
        });
    }
    CrusorHideCopilotContribution.prototype.apply = function () {
        // CrusorAI fork: hide Copilot if EITHER our setting says hide (default true)
        // OR the upstream disableAIFeatures master switch is on. Previous AND logic
        // meant a user who had not yet loaded configurationDefaults would briefly
        // see CHAT tab / sign-in button. OR logic + earlier phase fixes the flash.
        var crusorHide = this.configurationService.getValue(SETTING_ID) !== false;
        var upstreamDisabled = this.configurationService.getValue('chat.disableAIFeatures') === true;
        var hide = crusorHide || upstreamDisabled;
        // 1) Tell the entitlement service itself that Copilot is hidden —
        //    this covers Copilot's own UI gating (onboarding, sign-in prompts).
        this.chatEntitlementService.setForceHidden(hide);
        // 2) Force raw context keys every Copilot surface reads. Reset on
        //    every apply() because the entitlement service can flip them
        //    back during its async update() flow.
        this.hiddenKey.set(hide);
        this.installedKey.set(!hide);
        this.disabledKey.set(hide);
        this.chatEnabledKey.set(!hide);
    };
    /**
     * Deregister the Copilot Chat view from its container.
     *
     * The chat view container (chatParticipant.contribution.ts:71) has a
     * `when` clause with 3 OR paths. Context key forcing only kills path (a).
     * Path (b) (`chatPanelParticipantRegistered=true`) is set asynchronously
     * by ChatAgentService when the Copilot extension registers its agent,
     * overriding our context key. Rather than race with Copilot's agent
     * registration, we deregister the view from the container entirely.
     *
     * The container is registered with `hideIfEmpty: true`, so once the view
     * is removed, the container automatically disappears from the auxiliary bar.
     *
     * This does NOT edit Copilot source — we only call the public views API.
     */
    CrusorHideCopilotContribution.prototype.deregisterChatView = function () {
        try {
            var viewContainersRegistry = Registry.as(ViewExtensions.ViewContainersRegistry);
            var viewsRegistry = Registry.as(ViewExtensions.ViewsRegistry);
            var chatContainer = viewContainersRegistry.get('workbench.panel.chat');
            if (!chatContainer) {
                return; // Chat container not registered — nothing to do
            }
            var chatViews = viewsRegistry.getViews(chatContainer);
            if (chatViews.length > 0) {
                viewsRegistry.deregisterViews(chatViews, chatContainer);
            }
        }
        catch (_a) {
            // If the registry is not ready or the container doesn't exist yet,
            // silently skip. The context key forcing above still handles the
            // watermark and title bar surfaces.
        }
    };
    CrusorHideCopilotContribution.ID = 'workbench.contrib.crusorai.hideCopilot';
    CrusorHideCopilotContribution = __decorate([
        __param(0, IContextKeyService),
        __param(1, IConfigurationService),
        __param(2, IChatEntitlementService)
    ], CrusorHideCopilotContribution);
    return CrusorHideCopilotContribution;
}());
// BlockRestore (Ready) hides CHAT tab before first paint, preventing flash of VS Code surfaces.
// Previously AfterRestored caused visible flicker of sign-in / CHAT tab.
registerWorkbenchContribution2(CrusorHideCopilotContribution.ID, CrusorHideCopilotContribution, WorkbenchPhase.BlockRestore);
// Manual toggle command (Command Palette only) so a power user can flip
// this without editing settings JSON.
registerAction2(/** @class */ (function (_super) {
    __extends(class_1, _super);
    function class_1() {
        return _super.call(this, {
            id: 'crusorai.toggleBuiltInCopilotUI',
            title: localize2('crusorai.toggleCopilot', 'Crusor: Toggle Built-in Copilot UI'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_1.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var config, current;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        config = accessor.get(IConfigurationService);
                        current = config.getValue(SETTING_ID) !== false;
                        return [4 /*yield*/, config.updateValue(SETTING_ID, !current)];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_1;
}(Action2)));
