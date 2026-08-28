/*---------------------------------------------------------------------------------------------
 * PulseAI inline completion provider — ghost text suggestions via bridge protocol.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { Position } from '../../../../editor/common/core/position.js';
import { Range } from '../../../../editor/common/core/range.js';
import { TextModel } from '../../../../editor/common/model/textModel.js';
import { IPulseAIEngineService } from '../common/pulseAIEngineService.js';
import type { PulseServerEvent } from '../common/pulseAIProtocol.js';

export interface PulseAIInlineCompletionItem {
	readonly insertText: string;
	readonly range: Range;
}

export class PulseAIInlineCompletionProvider extends Disposable {
	private requestCounter = 0;
	private readonly pending = new Map<string, { resolve: (items: PulseAIInlineCompletionItem[]) => void; timer: ReturnType<typeof setTimeout> }>();

	constructor(
		@IPulseAIEngineService private readonly engineService: IPulseAIEngineService,
	) {
		super();
		this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
	}

	private handleFrame(frame: PulseServerEvent): void {
		if (frame.type !== 'inline_completion_result') { return; }
		const result = frame as any;
		const completions = result.completions ?? [];
		const items: PulseAIInlineCompletionItem[] = completions.map((c: any) => ({
			insertText: c.text ?? '',
			range: new Range(
				(c.range_start_line ?? 0) + 1, (c.range_start_column ?? 0) + 1,
				(c.range_end_line ?? 0) + 1, (c.range_end_column ?? 0) + 1,
			),
		}));
		for (const [, pending] of this.pending) {
			pending.resolve(items);
			break;
		}
		this.pending.clear();
	}

	requestCompletions(model: TextModel, position: Position): void {
		const uri = model.uri.toString();
		const prefix = this.getPrefix(model, position);
		const suffix = this.getSuffix(model, position);
		this.engineService.send({
			type: 'inline_completion',
			request_id: `req-${++this.requestCounter}`,
			resource: uri,
			language_id: model.getLanguageId(),
			line: position.lineNumber - 1,
			column: position.column - 1,
			prefix, suffix,
		} as any);
	}

	private getPrefix(model: TextModel, position: Position): string {
		const lines: string[] = [];
		const startLine = Math.max(1, position.lineNumber - 30);
		for (let i = startLine; i <= position.lineNumber; i++) {
			lines.push(i === position.lineNumber
				? model.getLineContent(i).substring(0, position.column - 1)
				: model.getLineContent(i));
		}
		return lines.join('\n');
	}

	private getSuffix(model: TextModel, position: Position): string {
		const lines: string[] = [];
		const endLine = Math.min(model.getLineCount(), position.lineNumber + 15);
		for (let i = position.lineNumber; i <= endLine; i++) {
			lines.push(i === position.lineNumber
				? model.getLineContent(i).substring(position.column - 1)
				: model.getLineContent(i));
		}
		return lines.join('\n');
	}
}
