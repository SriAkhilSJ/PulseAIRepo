/*---------------------------------------------------------------------------------------------
 * Desktop-only PulseAI service registration. Kept out of workbench.common.main for web safety.
 *--------------------------------------------------------------------------------------------*/

import { localize } from '../../../../nls.js';
import { ConfigurationScope } from '../../../../platform/configuration/common/configuration.js';
import { Extensions as ConfigurationExtensions, IConfigurationRegistry } from '../../../../platform/configuration/common/configurationRegistry.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { IPulseAIEngineService } from '../common/pulseAIEngineService.js';
import { PulseAIEngineService } from './pulseAIEngineService.js';

registerSingleton(IPulseAIEngineService, PulseAIEngineService, InstantiationType.Delayed);

Registry.as<IConfigurationRegistry>(ConfigurationExtensions.Configuration).registerConfiguration({
	id: 'pulseai',
	title: localize('pulseAI.configuration.title', 'PulseAI'),
	type: 'object',
	properties: {
		'pulseai.engineRoot': {
			type: 'string',
			default: '',
			scope: ConfigurationScope.MACHINE,
			description: localize('pulseAI.engineRoot', 'Absolute path to the PulseAI engine package. Empty uses the current workspace during development.'),
		},
		'pulseai.pythonPath': {
			type: 'string',
			default: '',
			scope: ConfigurationScope.MACHINE,
			description: localize('pulseAI.pythonPath', 'Python executable used for the local PulseAI engine. Empty uses the platform default.'),
		},
		'pulseai.autoStart': {
			type: 'boolean',
			default: true,
			scope: ConfigurationScope.WINDOW,
			description: localize('pulseAI.autoStart', 'Start the local PulseAI engine when the Pulse view is first opened.'),
		},
	},
});
