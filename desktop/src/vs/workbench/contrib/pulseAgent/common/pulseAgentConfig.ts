/*---------------------------------------------------------------------------------------------
 *  Copyright (c) PulseCode AI. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { Registry } from '../../../../platform/registry/common/platform.js';
import { Extensions as ConfigExtensions, IConfigurationNode, IConfigurationRegistry, EditPresentationTypes } from '../../../../platform/configuration/common/configurationRegistry.js';
import { localize } from '../../../../nls.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';

/**
 * Configuration keys for PulseCodeAI settings.
 */
export const PULSE_CONFIG_KEY = 'pulsecodeai';

export interface IPulseAgentProviderConfig {
	readonly apiKey?: string;
	readonly baseUrl?: string;
	readonly model?: string;
}

export interface IPulseAgentConfig {
	readonly defaultProvider: string;
	readonly providers: {
		readonly openai: IPulseAgentProviderConfig;
		readonly anthropic: IPulseAgentProviderConfig;
		readonly google: IPulseAgentProviderConfig;
		readonly groq: IPulseAgentProviderConfig;
		readonly openrouter: IPulseAgentProviderConfig;
		readonly cerebras: IPulseAgentProviderConfig;
		readonly nvidia: IPulseAgentProviderConfig;
	};
}

/**
 * Default configuration values.
 */
export const PULSE_AGENT_DEFAULTS: IPulseAgentConfig = {
	defaultProvider: 'google',
	providers: {
		openai: { baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o' },
		anthropic: { baseUrl: 'https://api.anthropic.com/v1', model: 'claude-sonnet-4-20250514' },
		google: { baseUrl: 'https://generativelanguage.googleapis.com/v1beta', model: 'gemini-2.0-flash' },
		groq: { baseUrl: 'https://api.groq.com/openai/v1', model: 'llama-3.3-70b-versatile' },
		openrouter: { baseUrl: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-sonnet' },
		cerebras: { baseUrl: 'https://api.cerebras.ai/v1', model: 'llama3.1-8b' },
		nvidia: { baseUrl: 'https://integrate.api.nvidia.com/v1', model: 'meta/llama-3.1-8b-instruct' },
	}
};

/**
 * Read the PulseCodeAI config object from VS Code settings,
 * falling back to environment variables for API keys.
 */
export function readPulseConfig(configService: IConfigurationService): IPulseAgentConfig {
	const config = configService.getValue<IPulseAgentConfig>(PULSE_CONFIG_KEY);

	const providers = { ...PULSE_AGENT_DEFAULTS.providers };
	if (config?.providers) {
		for (const key of Object.keys(providers) as Array<keyof typeof providers>) {
			if (config.providers[key]) {
				providers[key] = {
					...providers[key],
					...config.providers[key],
					apiKey: config.providers[key].apiKey || getEnvApiKeyForProvider(key),
				};
			} else {
				providers[key] = {
					...providers[key],
					apiKey: providers[key].apiKey || getEnvApiKeyForProvider(key),
				};
			}
		}
	}

	return { defaultProvider: config?.defaultProvider ?? PULSE_AGENT_DEFAULTS.defaultProvider, providers };
}

/**
 * Map provider name to environment variable for API key.
 */
function getEnvApiKeyForProvider(provider: string): string | undefined {
	const envMap: Record<string, string> = {
		groq: 'GROQ_API_KEY',
		google: 'GOOGLE_API_KEY',
		cerebras: 'CEREBRAS_API_KEY',
		openrouter: 'OPENROUTER_API_KEY',
		nvidia: 'NVIDIA_NIM_API_KEY',
		openai: 'OPENAI_API_KEY',
		anthropic: 'ANTHROPIC_API_KEY',
	};
	const envKey = envMap[provider];
	if (envKey) {
		const glob = globalThis as Record<string, unknown>;
		const val = glob[envKey];
		if (typeof val === 'string' && val.length > 0) {
			return val;
		}
		const proc = glob.process as { env?: Record<string, string | undefined> } | undefined;
		if (proc?.env?.[envKey]) {
			return proc.env[envKey]!;
		}
	}
	return undefined;
}

/**
 * Register PulseCodeAI configuration schema with VS Code.
 */
export function registerPulseAgentConfiguration(): void {
	const configRegistry = Registry.as<IConfigurationRegistry>(ConfigExtensions.Configuration);

	const configuration: IConfigurationNode = {
		id: 'pulsecodeai',
		order: 30,
		title: localize('pulsecodeai.config.title', 'PulseCodeAI'),
		type: 'object',
		properties: {
			'pulsecodeai.defaultProvider': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.defaultProvider', 'Default LLM provider (openai, anthropic, google, groq, openrouter, cerebras, nvidia)'),
				default: 'google',
				enum: ['openai', 'anthropic', 'google', 'groq', 'openrouter', 'cerebras', 'nvidia'],
			},
			'pulsecodeai.providers.openai.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.openai.apiKey', 'OpenAI API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.openai.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.openai.baseUrl', 'OpenAI API base URL'),
				default: 'https://api.openai.com/v1',
			},
			'pulsecodeai.providers.openai.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.openai.model', 'Default OpenAI model'),
				default: 'gpt-4o',
			},
			'pulsecodeai.providers.anthropic.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.anthropic.apiKey', 'Anthropic API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.anthropic.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.anthropic.baseUrl', 'Anthropic API base URL'),
				default: 'https://api.anthropic.com/v1',
			},
			'pulsecodeai.providers.anthropic.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.anthropic.model', 'Default Anthropic model'),
				default: 'claude-sonnet-4-20250514',
			},
			'pulsecodeai.providers.google.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.google.apiKey', 'Google Gemini API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.google.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.google.baseUrl', 'Google Gemini API base URL'),
				default: 'https://generativelanguage.googleapis.com/v1beta',
			},
			'pulsecodeai.providers.google.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.google.model', 'Default Google Gemini model'),
				default: 'gemini-2.0-flash',
			},
			'pulsecodeai.providers.groq.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.groq.apiKey', 'Groq API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.groq.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.groq.baseUrl', 'Groq API base URL'),
				default: 'https://api.groq.com/openai/v1',
			},
			'pulsecodeai.providers.groq.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.groq.model', 'Default Groq model'),
				default: 'llama-3.3-70b-versatile',
			},
			'pulsecodeai.providers.openrouter.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.openrouter.apiKey', 'OpenRouter API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.openrouter.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.openrouter.baseUrl', 'OpenRouter API base URL'),
				default: 'https://openrouter.ai/api/v1',
			},
			'pulsecodeai.providers.openrouter.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.openrouter.model', 'Default OpenRouter model'),
				default: 'anthropic/claude-sonnet',
			},
			'pulsecodeai.providers.cerebras.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.cerebras.apiKey', 'Cerebras API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.cerebras.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.cerebras.baseUrl', 'Cerebras API base URL'),
				default: 'https://api.cerebras.ai/v1',
			},
			'pulsecodeai.providers.cerebras.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.cerebras.model', 'Default Cerebras model'),
				default: 'llama3.1-8b',
			},
			'pulsecodeai.providers.nvidia.apiKey': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.nvidia.apiKey', 'NVIDIA NIM API key'),
				default: '',
				editPresentation: EditPresentationTypes.Multiline,
			},
			'pulsecodeai.providers.nvidia.baseUrl': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.nvidia.baseUrl', 'NVIDIA NIM API base URL'),
				default: 'https://integrate.api.nvidia.com/v1',
			},
			'pulsecodeai.providers.nvidia.model': {
				type: 'string',
				markdownDescription: localize('pulsecodeai.providers.nvidia.model', 'Default NVIDIA NIM model'),
				default: 'meta/llama-3.1-8b-instruct',
			},
		}
	};

	configRegistry.registerConfiguration(configuration);
}
