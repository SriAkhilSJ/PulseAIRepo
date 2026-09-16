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
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { IChatEntitlementService } from '../../../../workbench/services/chat/common/chatEntitlementService.js';
import { Extensions as ViewExtensions } from '../../../common/views.js';
const SETTING_ID = 'crusorai.hideBuiltInCopilotUI';
// Register the setting so it shows up under Crusor Settings and is
// overridable per-user.
Registry.as(ConfigurationExtensions.Configuration).registerConfiguration({
    id: 'crusorai',
    title: localize2('crusorAI.configuration.title', 'CrusorAI').value,
    type: 'object',
    properties: {
        [SETTING_ID]: {
            type: 'boolean',
            default: true,
            scope: 1 /* ConfigurationScope.APPLICATION */,
            description: localize2('crusorai.hideBuiltInCopilotUI.description', 'Hide the built-in GitHub Copilot UI (CHAT tab, empty-editor "Open Chat" watermark, title-bar Copilot icon, Copilot sign-in prompts). Crusor is the primary AI in this IDE; Copilot source and extensions remain installed and can be re-enabled by turning this off.').value,
        },
    },
});
let CrusorHideCopilotContribution = class CrusorHideCopilotContribution {
    static { this.ID = 'workbench.contrib.crusorai.hideCopilot'; }
    constructor(contextKeyService, configurationService, chatEntitlementService) {
        this.configurationService = configurationService;
        this.chatEntitlementService = chatEntitlementService;
        this.hiddenKey = new RawContextKey('chatSetupHidden', false).bindTo(contextKeyService);
        this.installedKey = new RawContextKey('chatSetupInstalled', false).bindTo(contextKeyService);
        this.disabledKey = new RawContextKey('chatSetupDisabled', false).bindTo(contextKeyService);
        this.chatEnabledKey = new RawContextKey('chatIsEnabled', true).bindTo(contextKeyService);
        this.apply();
        this.deregisterChatView();
        this.configurationService.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration(SETTING_ID) || e.affectsConfiguration('chat.disableAIFeatures')) {
                this.apply();
            }
        });
    }
    apply() {
        const hide = this.configurationService.getValue(SETTING_ID) !== false
            // Also honor the upstream "disable AI features" master switch.
            && this.configurationService.getValue('chat.disableAIFeatures') === true;
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
    }
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
    deregisterChatView() {
        try {
            const viewContainersRegistry = Registry.as(ViewExtensions.ViewContainersRegistry);
            const viewsRegistry = Registry.as(ViewExtensions.ViewsRegistry);
            const chatContainer = viewContainersRegistry.get('workbench.panel.chat');
            if (!chatContainer) {
                return; // Chat container not registered — nothing to do
            }
            const chatViews = viewsRegistry.getViews(chatContainer);
            if (chatViews.length > 0) {
                viewsRegistry.deregisterViews(chatViews, chatContainer);
            }
        }
        catch {
            // If the registry is not ready or the container doesn't exist yet,
            // silently skip. The context key forcing above still handles the
            // watermark and title bar surfaces.
        }
    }
};
CrusorHideCopilotContribution = __decorate([
    __param(0, IContextKeyService),
    __param(1, IConfigurationService),
    __param(2, IChatEntitlementService)
], CrusorHideCopilotContribution);
registerWorkbenchContribution2(CrusorHideCopilotContribution.ID, CrusorHideCopilotContribution, 3 /* WorkbenchPhase.AfterRestored */);
// Manual toggle command (Command Palette only) so a power user can flip
// this without editing settings JSON.
registerAction2(class extends Action2 {
    constructor() {
        super({
            id: 'crusorai.toggleBuiltInCopilotUI',
            title: localize2('crusorai.toggleCopilot', 'Crusor: Toggle Built-in Copilot UI'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        });
    }
    async run(accessor) {
        const config = accessor.get(IConfigurationService);
        const current = config.getValue(SETTING_ID) !== false;
        await config.updateValue(SETTING_ID, !current);
    }
});
