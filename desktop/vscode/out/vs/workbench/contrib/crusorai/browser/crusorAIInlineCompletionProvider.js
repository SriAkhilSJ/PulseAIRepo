/*---------------------------------------------------------------------------------------------
 * CrusorAI inline completion provider — ghost text suggestions via bridge protocol.
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
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Range } from '../../../../editor/common/core/range.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
let CrusorAIInlineCompletionProvider = class CrusorAIInlineCompletionProvider extends Disposable {
    constructor(engineService) {
        super();
        this.engineService = engineService;
        this.requestCounter = 0;
        this.pending = new Map();
        this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
    }
    handleFrame(frame) {
        if (frame.type !== 'inline_completion_result') {
            return;
        }
        const result = frame;
        const completions = result.completions ?? [];
        const items = completions.map((c) => ({
            insertText: c.text ?? '',
            range: new Range((c.range_start_line ?? 0) + 1, (c.range_start_column ?? 0) + 1, (c.range_end_line ?? 0) + 1, (c.range_end_column ?? 0) + 1),
        }));
        for (const [, pending] of this.pending) {
            pending.resolve(items);
            break;
        }
        this.pending.clear();
    }
    requestCompletions(model, position) {
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
        });
    }
    getPrefix(model, position) {
        const lines = [];
        const startLine = Math.max(1, position.lineNumber - 30);
        for (let i = startLine; i <= position.lineNumber; i++) {
            lines.push(i === position.lineNumber
                ? model.getLineContent(i).substring(0, position.column - 1)
                : model.getLineContent(i));
        }
        return lines.join('\n');
    }
    getSuffix(model, position) {
        const lines = [];
        const endLine = Math.min(model.getLineCount(), position.lineNumber + 15);
        for (let i = position.lineNumber; i <= endLine; i++) {
            lines.push(i === position.lineNumber
                ? model.getLineContent(i).substring(position.column - 1)
                : model.getLineContent(i));
        }
        return lines.join('\n');
    }
};
CrusorAIInlineCompletionProvider = __decorate([
    __param(0, ICrusorAIEngineService)
], CrusorAIInlineCompletionProvider);
export { CrusorAIInlineCompletionProvider };
