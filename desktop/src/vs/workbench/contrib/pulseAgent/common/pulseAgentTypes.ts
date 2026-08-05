/*---------------------------------------------------------------------------------------------
 *  Copyright (c) PulseCode AI. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

/**
 * Types and interfaces for PulseCodeAI LLM model service.
 */

/**
 * A single message in a chat conversation.
 */
export interface IPulseChatMessage {
	role: 'system' | 'user' | 'assistant';
	content: string;
}

/**
 * A tool definition that can be passed to the LLM.
 */
export interface IPulseToolDefinition {
	name: string;
	description: string;
	inputSchema: Record<string, unknown>;
}

/**
 * A tool call returned by the LLM.
 */
export interface IPulseToolCall {
	id: string;
	name: string;
	arguments: Record<string, unknown>;
}

/**
 * Supported LLM providers.
 */
export type PulseModelProvider = 'openai' | 'anthropic' | 'google' | 'ollama' | 'openrouter' | 'groq' | 'cerebras' | 'nvidia';

/**
 * Error thrown by the model service.
 */
export class PulseModelError extends Error {
	constructor(
		message: string,
		public readonly provider: PulseModelProvider,
		public readonly statusCode?: number,
		public readonly body?: string,
	) {
		super(message);
		this.name = 'PulseModelError';
	}
}
