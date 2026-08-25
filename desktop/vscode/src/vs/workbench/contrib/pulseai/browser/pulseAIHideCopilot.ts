/*---------------------------------------------------------------------------------------------
 * Hide Copilot's first-run UI surfaces when Pulse is the primary AI.
 *
 * Why this exists:
 *
 *   Setting `chat.disableAIFeatures: true` in configurationDefaults hides
 *   most of Copilot once the ChatEntitlementService finishes its async
 *   entitlement resolution and flips ChatContextKeys.Setup.hidden to true.
 *   But that flip happens AFTER the workbench paints, so on first boot /
 *   empty window / before sign-in users still see:
 *     - a CHAT tab in the auxiliary bar next to Pulse,
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
 *   this Pulse workbench contribution forces those context keys to the
 *   "hidden" state from LifecyclePhase.Starting onward, and calls
 *   IChatEntitlementService.setForceHidden(true) so Copilot's own gating
 *   agrees. Reversible by flipping `pulseai.hideBuiltInCopilotUI` to false.
 *--------------------------------------------------------------------------------------------*/

import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { IContextKey, IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IWorkbenchContribution, WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { ServicesAccessor } from '../../../../platform/instantiation/common/instantiation.js';
import { IChatEntitlementService } from '../../../../workbench/services/chat/common/chatEntitlementService.js';

const SETTING_ID = 'pulseai.hideBuiltInCopilotUI';

// Register the setting so it shows up under Pulse Settings and is
// overridable per-user.
Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'pulseai',
	title: localize2('pulseAI.configuration.title', 'PulseAI').value,
	type: 'object',
	properties: {
		[SETTING_ID]: {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.APPLICATION,
			description: localize2('pulseai.hideBuiltInCopilotUI.description',
				'Hide the built-in GitHub Copilot UI (CHAT tab, empty-editor "Open Chat" watermark, title-bar Copilot icon, Copilot sign-in prompts). Pulse is the primary AI in this IDE; Copilot source and extensions remain installed and can be re-enabled by turning this off.').value,
		},
	},
});

class PulseHideCopilotContribution implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.pulseai.hideCopilot';

	// Context keys we force. These are the literal keys Copilot reads:
	//   chatSetupHidden              - editorGroupWatermark.ts:34, chatGettingStarted, onboarding
	//   chatSetupInstalled           - CHAT tab secondary gating
	//   chatSetupDisabled            - general "chat is disabled" gate
	//   chatIsEnabled                - AgentTitleBarStatusRendering (title bar widget)
	private readonly hiddenKey: IContextKey<boolean>;
	private readonly installedKey: IContextKey<boolean>;
	private readonly disabledKey: IContextKey<boolean>;
	private readonly chatEnabledKey: IContextKey<boolean>;

	constructor(
		@IContextKeyService contextKeyService: IContextKeyService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@IChatEntitlementService private readonly chatEntitlementService: IChatEntitlementService,
	) {
		this.hiddenKey      = new RawContextKey<boolean>('chatSetupHidden', false).bindTo(contextKeyService);
		this.installedKey   = new RawContextKey<boolean>('chatSetupInstalled', false).bindTo(contextKeyService);
		this.disabledKey    = new RawContextKey<boolean>('chatSetupDisabled', false).bindTo(contextKeyService);
		this.chatEnabledKey = new RawContextKey<boolean>('chatIsEnabled', true).bindTo(contextKeyService);

		this.apply();
		this.configurationService.onDidChangeConfiguration(e => {
			if (e.affectsConfiguration(SETTING_ID) || e.affectsConfiguration('chat.disableAIFeatures')) {
				this.apply();
			}
		});
	}

	private apply(): void {
		const hide = this.configurationService.getValue<boolean>(SETTING_ID) !== false
			// Also honor the upstream "disable AI features" master switch.
			&& this.configurationService.getValue<boolean>('chat.disableAIFeatures') === true;

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
}

registerWorkbenchContribution2(PulseHideCopilotContribution.ID, PulseHideCopilotContribution, WorkbenchPhase.BlockStartup);

// Manual toggle command (Command Palette only) so a power user can flip
// this without editing settings JSON.
registerAction2(class extends Action2 {
	constructor() {
		super({
			id: 'pulseai.toggleBuiltInCopilotUI',
			title: localize2('pulseai.toggleCopilot', 'Pulse: Toggle Built-in Copilot UI'),
			f1: true,
			category: localize2('pulseAI.category', 'Pulse'),
		});
	}
	async run(accessor: ServicesAccessor): Promise<void> {
		const config = accessor.get(IConfigurationService);
		const current = config.getValue<boolean>(SETTING_ID) !== false;
		await config.updateValue(SETTING_ID, !current);
	}
});
