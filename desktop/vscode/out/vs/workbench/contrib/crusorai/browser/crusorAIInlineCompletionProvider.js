/*---------------------------------------------------------------------------------------------
 * CrusorAI inline completion provider — ghost text suggestions via bridge protocol.
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
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Range } from '../../../../editor/common/core/range.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
var CrusorAIInlineCompletionProvider = /** @class */ (function (_super) {
    __extends(CrusorAIInlineCompletionProvider, _super);
    function CrusorAIInlineCompletionProvider(engineService) {
        var _this = _super.call(this) || this;
        _this.engineService = engineService;
        _this.requestCounter = 0;
        _this.pending = new Map();
        _this._register(_this.engineService.onDidReceiveFrame(function (frame) { return _this.handleFrame(frame); }));
        return _this;
    }
    CrusorAIInlineCompletionProvider.prototype.handleFrame = function (frame) {
        var _a;
        if (frame.type !== 'inline_completion_result') {
            return;
        }
        var result = frame;
        var completions = (_a = result.completions) !== null && _a !== void 0 ? _a : [];
        var items = completions.map(function (c) {
            var _a, _b, _c, _d, _e;
            return ({
                insertText: (_a = c.text) !== null && _a !== void 0 ? _a : '',
                range: new Range(((_b = c.range_start_line) !== null && _b !== void 0 ? _b : 0) + 1, ((_c = c.range_start_column) !== null && _c !== void 0 ? _c : 0) + 1, ((_d = c.range_end_line) !== null && _d !== void 0 ? _d : 0) + 1, ((_e = c.range_end_column) !== null && _e !== void 0 ? _e : 0) + 1),
            });
        });
        for (var _i = 0, _b = this.pending; _i < _b.length; _i++) {
            var _c = _b[_i], pending = _c[1];
            pending.resolve(items);
            break;
        }
        this.pending.clear();
    };
    CrusorAIInlineCompletionProvider.prototype.requestCompletions = function (model, position) {
        var uri = model.uri.toString();
        var prefix = this.getPrefix(model, position);
        var suffix = this.getSuffix(model, position);
        this.engineService.send({
            type: 'inline_completion',
            request_id: "req-".concat(++this.requestCounter),
            resource: uri,
            language_id: model.getLanguageId(),
            line: position.lineNumber - 1,
            column: position.column - 1,
            prefix: prefix,
            suffix: suffix,
        });
    };
    CrusorAIInlineCompletionProvider.prototype.getPrefix = function (model, position) {
        var lines = [];
        var startLine = Math.max(1, position.lineNumber - 30);
        for (var i = startLine; i <= position.lineNumber; i++) {
            lines.push(i === position.lineNumber
                ? model.getLineContent(i).substring(0, position.column - 1)
                : model.getLineContent(i));
        }
        return lines.join('\n');
    };
    CrusorAIInlineCompletionProvider.prototype.getSuffix = function (model, position) {
        var lines = [];
        var endLine = Math.min(model.getLineCount(), position.lineNumber + 15);
        for (var i = position.lineNumber; i <= endLine; i++) {
            lines.push(i === position.lineNumber
                ? model.getLineContent(i).substring(position.column - 1)
                : model.getLineContent(i));
        }
        return lines.join('\n');
    };
    CrusorAIInlineCompletionProvider = __decorate([
        __param(0, ICrusorAIEngineService)
    ], CrusorAIInlineCompletionProvider);
    return CrusorAIInlineCompletionProvider;
}(Disposable));
export { CrusorAIInlineCompletionProvider };
