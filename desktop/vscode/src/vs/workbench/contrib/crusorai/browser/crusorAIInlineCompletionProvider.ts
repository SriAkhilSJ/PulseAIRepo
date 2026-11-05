/*---------------------------------------------------------------------------------------------
 * CrusorAI inline completion provider — ghost text suggestions via bridge protocol.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { Position } from '../../../../editor/common/core/position.js';
import { Range } from '../../../../editor/common/core/range.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import {
	InlineCompletion,
	InlineCompletionContext,
	InlineCompletions,
	InlineCompletionsProvider,
} from '../../../../editor/common/languages.js';
import { IWorkspaceTrustManagementService } from '../../../../platform/workspace/common/workspaceTrust.js';
import { CrusorAIEngineState, ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import type { CrusorServerEvent } from '../common/crusorAIProtocol.js';

const MAX_CONCURRENT_PENDING = 8;
const REQUEST_TIMEOUT_MS = 4000;
const MAX_PREFIX_LINES = 50;
const MAX_SUFFIX_LINES = 25;
const MAX_PREFIX_CHARS = 4000;
const MAX_SUFFIX_CHARS = 2000;

interface PendingCompletionRequest {
	readonly resolve: (result: InlineCompletions | undefined) => void;
	readonly modelUri: string;
	readonly modelVersion: number;
	readonly timer: any;
}

export class CrusorAIInlineCompletionProvider extends Disposable implements InlineCompletionsProvider {
	private requestCounter = 0;
	private readonly pending = new Map<string, PendingCompletionRequest>();

	constructor(
		@ICrusorAIEngineService private readonly engineService: ICrusorAIEngineService,
		@IWorkspaceTrustManagementService private readonly trustService: IWorkspaceTrustManagementService,
	) {
		super();
		this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
	}

	async provideInlineCompletions(
		model: ITextModel,
		position: Position,
		context: InlineCompletionContext,
		token: CancellationToken,
	): Promise<InlineCompletions | undefined> {
		if (token.isCancellationRequested) { return undefined; }
		if (!this.trustService.isWorkspaceTrusted()) { return undefined; }
		if (this.engineService.state !== CrusorAIEngineState.Ready) { return undefined; }

		const uriStr = model.uri.toString();
		if (this.isSensitiveFile(model.uri.path)) { return undefined; }

		const requestId = `req-${++this.requestCounter}-${Date.now()}`;
		const prefix = this.getPrefix(model, position);
		const suffix = this.getSuffix(model, position);
		const modelVersion = model.getVersionId();

		// Guard: throttle unbounded accumulation
		if (this.pending.size >= MAX_CONCURRENT_PENDING) {
			const oldestKey = this.pending.keys().next().value;
			if (oldestKey) {
				const oldest = this.pending.get(oldestKey);
				if (oldest) {
					clearTimeout(oldest.timer);
					oldest.resolve(undefined);
					this.pending.delete(oldestKey);
				}
			}
		}

		return new Promise<InlineCompletions | undefined>(resolve => {
			const timer = setTimeout(() => {
				this.pending.delete(requestId);
				resolve(undefined);
			}, REQUEST_TIMEOUT_MS);

			const cancellationListener = token.onCancellationRequested(() => {
				clearTimeout(timer);
				this.pending.delete(requestId);
				cancellationListener.dispose();
				resolve(undefined);
			});

			this.pending.set(requestId, {
				resolve: result => {
					clearTimeout(timer);
					cancellationListener.dispose();
					resolve(result);
				},
				modelUri: uriStr,
				modelVersion,
				timer,
			});

			try {
				this.engineService.send({
					type: 'inline_completion',
					request_id: requestId,
					resource: uriStr,
					language_id: model.getLanguageId(),
					line: position.lineNumber - 1,
					column: position.column - 1,
					prefix,
					suffix,
				} as any);
			} catch {
				clearTimeout(timer);
				cancellationListener.dispose();
				this.pending.delete(requestId);
				resolve(undefined);
			}
		});
	}

	private handleFrame(frame: CrusorServerEvent): void {
		if (frame.type !== 'inline_completion_result') { return; }
		const result = frame as any;
		const requestId = result.request_id;
		if (!requestId || !this.pending.has(requestId)) { return; }

		const pending = this.pending.get(requestId)!;
		this.pending.delete(requestId);

		const completions = result.completions ?? [];
		const items: InlineCompletion[] = completions.map((c: any) => ({
			insertText: c.text ?? '',
			range: new Range(
				(c.range_start_line ?? 0) + 1, (c.range_start_column ?? 0) + 1,
				(c.range_end_line ?? 0) + 1, (c.range_end_column ?? 0) + 1,
			),
		}));

		pending.resolve({ items });
	}

	private isSensitiveFile(path: string): boolean {
		const lower = path.toLowerCase();
		return lower.includes('.env') ||
			lower.includes('/.git/') ||
			lower.includes('id_rsa') ||
			lower.includes('credentials') ||
			lower.endsWith('.key') ||
			lower.endsWith('.pem');
	}

	private getPrefix(model: ITextModel, position: Position): string {
		const lines: string[] = [];
		const startLine = Math.max(1, position.lineNumber - MAX_PREFIX_LINES);
		for (let i = startLine; i <= position.lineNumber; i++) {
			lines.push(i === position.lineNumber
				? model.getLineContent(i).substring(0, position.column - 1)
				: model.getLineContent(i));
		}
		const text = lines.join('\n');
		return text.length > MAX_PREFIX_CHARS ? text.slice(-MAX_PREFIX_CHARS) : text;
	}

	private getSuffix(model: ITextModel, position: Position): string {
		const lines: string[] = [];
		const endLine = Math.min(model.getLineCount(), position.lineNumber + MAX_SUFFIX_LINES);
		for (let i = position.lineNumber; i <= endLine; i++) {
			lines.push(i === position.lineNumber
				? model.getLineContent(i).substring(position.column - 1)
				: model.getLineContent(i));
		}
		const text = lines.join('\n');
		return text.length > MAX_SUFFIX_CHARS ? text.slice(0, MAX_SUFFIX_CHARS) : text;
	}

	disposeInlineCompletions(completions: InlineCompletions, reason: unknown): void {
		// Completed or dismissed inline completions cleanup
	}

	override dispose(): void {
		for (const [, item] of this.pending) {
			clearTimeout(item.timer);
			item.resolve(undefined);
		}
		this.pending.clear();
		super.dispose();
	}
}
