/*---------------------------------------------------------------------------------------------
 *  Copyright (c) PulseCode AI. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { CancellationToken } from '../../../../base/common/cancellation.js';
import { streamToBuffer } from '../../../../base/common/buffer.js';
import { IRequestService, asText } from '../../../../platform/request/common/request.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import {
	IPulseChatMessage,
	IPulseToolDefinition,
	IPulseToolCall,
	PulseModelError,
	PulseModelProvider,
} from './pulseAgentTypes.js';

/**
 * Result delta from streaming an LLM response.
 */
export interface IPulseStreamResult {
	type: 'text' | 'tool_call_start' | 'tool_call_arg' | 'done' | 'error';
	text?: string;
	toolCall?: { id: string; name: string };
	argText?: string;
	error?: string;
}

/**
 * Complete non-streaming LLM response.
 */
export interface IPulseModelResult {
	content: string;
	toolCalls: IPulseToolCall[];
}

/**
 * PulseAgentModelService — makes HTTP calls to LLM providers.
 *
 * Uses VS Code's IRequestService for HTTP and handles SSE/JSON-line streaming.
 */
export class PulseAgentModelService {

	constructor(
		private readonly _requestService: IRequestService,
		private readonly _logService: ILogService,
	) { }

	/**
	 * Non-streaming request, returns full response.
	 */
	async sendRequest(
		provider: PulseModelProvider,
		model: string,
		apiKey: string,
		baseUrl: string,
		messages: IPulseChatMessage[],
		tools: IPulseToolDefinition[] | undefined,
		token: CancellationToken,
		maxTokens?: number,
		temperature?: number,
	): Promise<IPulseModelResult> {

		const deltas: IPulseStreamResult[] = [];
		for await (const d of this.streamRequest(provider, model, apiKey, baseUrl, messages, tools, token, maxTokens, temperature)) {
			if (d.type === 'done') { break; }
			if (d.type === 'error') { throw new PulseModelError(d.error ?? 'Unknown', provider); }
			deltas.push(d);
		}

		const content = deltas.filter(d => d.type === 'text').map(d => d.text ?? '').join('');

		// Assemble tool calls from deltas
		const toolCalls: IPulseToolCall[] = [];
		let currentToolCall: { id: string; name: string; args: string } | null = null;

		for (const d of deltas) {
			if (d.type === 'tool_call_start') {
				if (currentToolCall) {
					toolCalls.push({ id: currentToolCall.id, name: currentToolCall.name, arguments: this._safeParseJSON(currentToolCall.args) });
				}
				currentToolCall = { id: d.toolCall!.id, name: d.toolCall!.name, args: '' };
			} else if (d.type === 'tool_call_arg' && currentToolCall) {
				currentToolCall.args += d.argText ?? '';
			}
		}
		if (currentToolCall) {
			toolCalls.push({ id: currentToolCall.id, name: currentToolCall.name, arguments: this._safeParseJSON(currentToolCall.args) });
		}

		return { content, toolCalls };
	}

	/**
	 * Streaming request, yields deltas as they arrive.
	 */
	async *streamRequest(
		provider: PulseModelProvider,
		model: string,
		apiKey: string,
		baseUrl: string,
		messages: IPulseChatMessage[],
		tools: IPulseToolDefinition[] | undefined,
		token: CancellationToken,
		maxTokens?: number,
		temperature?: number,
	): AsyncGenerator<IPulseStreamResult> {
		switch (provider) {
			case 'openai':
			case 'openrouter':
			case 'groq':
			case 'cerebras':
			case 'nvidia':
				yield* this._streamOpenAI(model, apiKey, baseUrl, messages, tools, token, maxTokens, temperature, provider === 'openrouter');
				return;
			case 'anthropic':
				yield* this._streamAnthropic(model, apiKey, baseUrl, messages, tools, token, maxTokens, temperature);
				return;
			case 'google':
				yield* this._streamGoogle(model, apiKey, baseUrl, messages, tools, token, temperature);
				return;
			case 'ollama':
				yield* this._streamOllama(model, apiKey, baseUrl, messages, tools, token, temperature);
				return;
			default:
				yield { type: 'error', error: `Unsupported provider: ${provider}` };
				return;
		}
	}

	// ── OpenAI / OpenRouter ─────────────────────────────

	private async *_streamOpenAI(
		model: string, apiKey: string, baseUrl: string,
		messages: IPulseChatMessage[], tools: IPulseToolDefinition[] | undefined,
		token: CancellationToken, maxTokens?: number, temperature?: number, isOpenRouter?: boolean,
	): AsyncGenerator<IPulseStreamResult> {
		const url = `${baseUrl.replace(/\/+$/, '')}/chat/completions`;
		const body = this._openAIBody(model, messages, tools, maxTokens, temperature);

		const headers: Record<string, string> = {
			'Content-Type': 'application/json',
			'Authorization': `Bearer ${apiKey}`,
		};
		if (isOpenRouter) {
			headers['HTTP-Referer'] = 'https://pulsecodeai.dev';
		}

		const raw = new SSEReader(this._requestService, url, headers, body, isOpenRouter ? 'openrouter' as PulseModelProvider : 'openai' as PulseModelProvider, token, this._logService);

		for await (const parsed of raw) {
			const choice = parsed.choices?.[0];
			if (!choice) { continue; }

			if (choice.delta?.content) {
				yield { type: 'text', text: choice.delta.content };
			}

			if (choice.delta?.tool_calls) {
				for (const tc of choice.delta.tool_calls) {
					if (tc.function?.name) {
						yield { type: 'tool_call_start', toolCall: { id: tc.id ?? '', name: tc.function.name } };
					} else if (tc.function?.arguments) {
						yield { type: 'tool_call_arg', argText: tc.function.arguments };
					}
				}
				continue;
			}

			if (choice.finish_reason) {
				yield { type: 'done' };
				return;
			}
		}
		yield { type: 'done' };
	}

	private _openAIBody(
		model: string, messages: IPulseChatMessage[], tools: IPulseToolDefinition[] | undefined,
		maxTokens?: number, temperature?: number,
	): Record<string, unknown> {
		const body: Record<string, unknown> = {
			model,
			messages: messages.map(m => ({ role: m.role, content: m.content })),
			stream: true,
		};
		if (temperature !== undefined) { body.temperature = temperature; }
		if (maxTokens !== undefined) { body.max_tokens = maxTokens; }
		if (tools && tools.length > 0) {
			body.tools = tools.map(t => ({
				type: 'function',
				function: { name: t.name, description: t.description, parameters: t.inputSchema },
			}));
		}
		return body;
	}

	// ── Anthropic ──────────────────────────────────────

	private async *_streamAnthropic(
		model: string, apiKey: string, baseUrl: string,
		messages: IPulseChatMessage[], tools: IPulseToolDefinition[] | undefined,
		token: CancellationToken, maxTokens?: number, temperature?: number,
	): AsyncGenerator<IPulseStreamResult> {
		const url = `${baseUrl.replace(/\/+$/, '')}/messages`;

		const systemMessages = messages.filter(m => m.role === 'system');
		const chatMessages = messages.filter(m => m.role !== 'system');

		const body: Record<string, unknown> = {
			model,
			max_tokens: maxTokens ?? 4096,
			messages: chatMessages.map(m => ({ role: m.role, content: m.content })),
			stream: true,
		};
		if (systemMessages.length > 0) {
			body.system = systemMessages.map(m => ({ type: 'text', text: m.content }));
		}
		if (temperature !== undefined) { body.temperature = temperature; }
		if (tools && tools.length > 0) {
			body.tools = tools.map(t => ({ name: t.name, description: t.description, input_schema: t.inputSchema }));
		}

		const headers: Record<string, string> = {
			'Content-Type': 'application/json',
			'x-api-key': apiKey,
			'anthropic-version': '2023-06-01',
		};

		const raw = new SSEReader(this._requestService, url, headers, body, 'anthropic' as PulseModelProvider, token, this._logService);

		for await (const parsed of raw) {
			switch (parsed.type) {
				case 'content_block_start': {
					if (parsed.content_block?.type === 'tool_use') {
						yield {
							type: 'tool_call_start',
							toolCall: { id: parsed.content_block.id ?? '', name: parsed.content_block.name ?? '' },
						};
					}
					break;
				}
				case 'content_block_delta': {
					if (parsed.delta?.type === 'text_delta') {
						yield { type: 'text', text: parsed.delta.text ?? '' };
					} else if (parsed.delta?.type === 'input_json_delta') {
						yield { type: 'tool_call_arg', argText: parsed.delta.partial_json ?? '' };
					}
					break;
				}
				case 'message_delta':
				case 'message_stop':
					if (parsed.delta?.stop_reason || parsed.type === 'message_stop') {
						yield { type: 'done' };
						return;
					}
					break;
				case 'error':
					yield { type: 'error', error: parsed.error?.message ?? 'Anthropic error' };
					return;
			}
		}
		yield { type: 'done' };
	}

	// ── Google Gemini ──────────────────────────────────

	private async *_streamGoogle(
		model: string, apiKey: string, baseUrl: string,
		messages: IPulseChatMessage[], _tools: IPulseToolDefinition[] | undefined,
		token: CancellationToken, temperature?: number,
	): AsyncGenerator<IPulseStreamResult> {
		const url = `${baseUrl.replace(/\/+$/, '')}/models/${model}:streamGenerateContent?alt=sse&key=${apiKey}`;

		const contents: Record<string, unknown>[] = [];
		for (const msg of messages) {
			if (msg.role === 'system') {
				contents.push({ role: 'user', parts: [{ text: msg.content }] });
			} else if (msg.role === 'assistant') {
				contents.push({ role: 'model', parts: [{ text: msg.content }] });
			} else {
				contents.push({ role: 'user', parts: [{ text: msg.content }] });
			}
		}

		const body: Record<string, unknown> = {
			contents,
			generationConfig: {},
		};
		if (temperature !== undefined) {
			(body.generationConfig as Record<string, unknown>).temperature = temperature;
		}

		const headers: Record<string, string> = { 'Content-Type': 'application/json' };

		const raw = new SSEReader(this._requestService, url, headers, body, 'google' as PulseModelProvider, token, this._logService);

		for await (const parsed of raw) {
			const candidate = parsed.candidates?.[0];
			if (!candidate) { continue; }

			const part = candidate.content?.parts?.[0];
			if (part?.text) {
				yield { type: 'text', text: part.text };
			}

			if (candidate.finishReason && candidate.finishReason !== 'FINISH_REASON_UNSPECIFIED') {
				yield { type: 'done' };
				return;
			}
		}
		yield { type: 'done' };
	}

	// ── Ollama ─────────────────────────────────────────

	private async *_streamOllama(
		model: string, _apiKey: string, baseUrl: string,
		messages: IPulseChatMessage[],
		tools: IPulseToolDefinition[] | undefined,
		token: CancellationToken, temperature?: number,
	): AsyncGenerator<IPulseStreamResult> {
		const url = `${baseUrl.replace(/\/+$/, '')}/api/chat`;

		const body: Record<string, unknown> = {
			model,
			messages: messages.map(m => ({ role: m.role, content: m.content })),
			stream: true,
		};
		if (tools && tools.length > 0) {
			body.tools = tools;
		}
		if (temperature !== undefined) { body.temperature = temperature; }

		const headers: Record<string, string> = { 'Content-Type': 'application/json' };

		const raw = new JSONLinesReader(this._requestService, url, headers, body, 'ollama' as PulseModelProvider, token, this._logService);

		for await (const parsed of raw) {
			if (parsed.done) {
				yield { type: 'done' };
				return;
			}
			if (parsed.message?.content) {
				yield { type: 'text', text: parsed.message.content };
			}
			if (parsed.message?.tool_calls) {
				for (const tc of parsed.message.tool_calls) {
					yield { type: 'tool_call_start', toolCall: { id: tc.function?.name ?? 'ollama_tc', name: tc.function?.name ?? '' } };
					yield { type: 'tool_call_arg', argText: JSON.stringify(tc.function?.arguments ?? {}) };
				}
			}
		}
		yield { type: 'done' };
	}

	// ── Utils ─────────────────────────────────────────

	private _safeParseJSON(text: string): Record<string, unknown> {
		try { return JSON.parse(text); } catch { return {}; }
	}
}

/**
 * Reads an SSE (Server-Sent Events) stream, yields parsed JSON events.
 */
class SSEReader {
	constructor(
		private readonly _requestService: IRequestService,
		private readonly _url: string,
		private readonly _headers: Record<string, string>,
		private readonly _body: Record<string, unknown>,
		private readonly _provider: PulseModelProvider,
		private readonly _token: CancellationToken,
		private readonly _logService: ILogService,
	) { }

	async *[Symbol.asyncIterator](): AsyncGenerator<Record<string, any>> {
		const context = await this._requestService.request({
			type: 'POST',
			url: this._url,
			headers: this._headers,
			data: JSON.stringify(this._body),
			callSite: 'pulsecodeai.modelService',
		}, this._token);

		if (context.res.statusCode && context.res.statusCode >= 400) {
			const text = await asText(context);
			throw new PulseModelError(
				`HTTP ${context.res.statusCode}: ${(text ?? 'Unknown').slice(0, 500)}`,
				this._provider,
				context.res.statusCode,
				text ?? undefined,
			);
		}

		const buffer = await streamToBuffer(context.stream);
		const fullText = buffer.toString();

		for (const line of fullText.split('\n')) {
			const trimmed = line.trim();
			if (!trimmed || !trimmed.startsWith('data: ')) { continue; }

			const jsonStr = trimmed.slice(6).trim();
			if (jsonStr === '[DONE]') { return; }

			try {
				yield JSON.parse(jsonStr);
			} catch {
				this._logService.trace('[PulseAgent] Failed to parse SSE:', jsonStr);
			}
		}
	}
}

/**
 * Reads a JSON-lines stream (Ollama format), yields parsed JSON events.
 */
class JSONLinesReader {
	constructor(
		private readonly _requestService: IRequestService,
		private readonly _url: string,
		private readonly _headers: Record<string, string>,
		private readonly _body: Record<string, unknown>,
		private readonly _provider: PulseModelProvider,
		private readonly _token: CancellationToken,
		private readonly _logService: ILogService,
	) { }

	async *[Symbol.asyncIterator](): AsyncGenerator<Record<string, any>> {
		const context = await this._requestService.request({
			type: 'POST',
			url: this._url,
			headers: this._headers,
			data: JSON.stringify(this._body),
			callSite: 'pulsecodeai.modelService',
		}, this._token);

		if (context.res.statusCode && context.res.statusCode >= 400) {
			const text = await asText(context);
			throw new PulseModelError(
				`HTTP ${context.res.statusCode}: ${(text ?? 'Unknown').slice(0, 500)}`,
				this._provider,
				context.res.statusCode,
				text ?? undefined,
			);
		}

		const buffer = await streamToBuffer(context.stream);
		const fullText = buffer.toString();

		for (const line of fullText.split('\n')) {
			const trimmed = line.trim();
			if (!trimmed) { continue; }

			try {
				yield JSON.parse(trimmed);
			} catch {
				this._logService.trace('[PulseAgent] Failed to parse JSON line:', trimmed);
			}
		}
	}
}
