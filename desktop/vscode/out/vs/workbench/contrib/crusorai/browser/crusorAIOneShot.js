// Crusor One-Shot — quick jobs outside the conversation (Phase 3).
// Command Palette: "Crusor: One-Shot Task" — pick a template (or ad-hoc),
// give it the input, one cheap-tier provider call, result to clipboard +
// notification. Stateless by contract: never appends to the thread, never
// touches the prompt cache.
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
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
var ONESHOT_TIMEOUT_MS = 60000;
function oneshotRequest(renderer, progress, template, extra) {
    return progress.withProgress({ location: ProgressLocation.Window, title: 'Crusor one-shot…' }, function () {
        return new Promise(function (resolve, reject) {
            var listener;
            var timer = setTimeout(function () {
                listener === null || listener === void 0 ? void 0 : listener.dispose();
                reject(new Error("One-shot: the engine did not answer the '".concat(template, "' request. Fully restart CrusorAI so the bridge runs this build.")));
            }, ONESHOT_TIMEOUT_MS);
            listener = renderer.onOneshotResult(function (frame) {
                clearTimeout(timer);
                listener === null || listener === void 0 ? void 0 : listener.dispose();
                resolve(frame);
            });
            renderer.sendOneshot(template, extra);
        });
    });
}
registerAction2(/** @class */ (function (_super) {
    __extends(class_1, _super);
    function class_1() {
        return _super.call(this, {
            id: 'crusorai.oneshot',
            title: localize2('crusorAI.oneshot', 'One-Shot Task'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_1.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var quickInput, notif, clipboard, progress, renderer, picks, pick, variables, template, ask, input, input, frame, preview, error_1;
            var _a, _b;
            return __generator(this, function (_c) {
                switch (_c.label) {
                    case 0:
                        quickInput = accessor.get(IQuickInputService);
                        notif = accessor.get(INotificationService);
                        clipboard = accessor.get(IClipboardService);
                        progress = accessor.get(IProgressService);
                        renderer = accessor.get(ICrusorAIRendererService);
                        picks = [
                            { label: '$(git-commit) Draft commit message', description: 'from a diff or a description of what changed', id: 'commit_message', variablePrompt: 'Paste the diff (or describe the change)' },
                            { label: '$(book) Summarize', description: 'the essentials of a page or a document', id: 'summarize', variablePrompt: 'Paste the text to summarize' },
                            { label: '$(lightbulb) Name ideas', description: '8 candidates with a one-clause rationale each', id: 'rename_ideas', variablePrompt: 'What needs a name? (feature, module, product…)' },
                            { label: '$(symbol-string) Ad-hoc one-shot…', description: 'your own instruction + input — no thread, no cache cost', id: '__adhoc' },
                        ];
                        return [4 /*yield*/, quickInput.pick(picks, { placeHolder: 'Crusor One-Shot — one question, one answer, nothing saved to the chat' })];
                    case 1:
                        pick = _c.sent();
                        if (!pick) {
                            return [2 /*return*/];
                        }
                        variables = {};
                        template = pick.id;
                        if (!(pick.id === '__adhoc')) return [3 /*break*/, 4];
                        return [4 /*yield*/, quickInput.input({ prompt: 'What should the model do? (one instruction)' })];
                    case 2:
                        ask = _c.sent();
                        if (!ask || !ask.trim()) {
                            return [2 /*return*/];
                        }
                        return [4 /*yield*/, quickInput.input({ prompt: 'Paste the input text (Enter to skip)' })];
                    case 3:
                        input = _c.sent();
                        template = 'adhoc';
                        variables = { instructions: ask.trim(), input: (input !== null && input !== void 0 ? input : '').trim() };
                        return [3 /*break*/, 6];
                    case 4: return [4 /*yield*/, quickInput.input({ prompt: (_a = pick.variablePrompt) !== null && _a !== void 0 ? _a : 'Input' })];
                    case 5:
                        input = _c.sent();
                        if (!input || !input.trim()) {
                            return [2 /*return*/];
                        }
                        variables = { input: input.trim() };
                        _c.label = 6;
                    case 6:
                        _c.trys.push([6, 9, , 10]);
                        return [4 /*yield*/, oneshotRequest(renderer, progress, template, {
                                instructions: variables.instructions,
                                variables: variables,
                            })];
                    case 7:
                        frame = _c.sent();
                        if (frame.error) {
                            notif.notify({ severity: Severity.Error, message: "One-shot: ".concat(frame.error), source: 'Crusor One-Shot' });
                            return [2 /*return*/];
                        }
                        return [4 /*yield*/, clipboard.writeText(frame.text)];
                    case 8:
                        _c.sent();
                        preview = frame.text.length > 400 ? frame.text.slice(0, 400) + '…' : frame.text;
                        notif.notify({
                            severity: Severity.Info,
                            message: "One-shot done \u2014 copied to clipboard:\n\n".concat(preview),
                            source: 'Crusor One-Shot',
                        });
                        return [3 /*break*/, 10];
                    case 9:
                        error_1 = _c.sent();
                        notif.notify({ severity: Severity.Error, message: String((_b = error_1.message) !== null && _b !== void 0 ? _b : error_1), source: 'Crusor One-Shot' });
                        return [3 /*break*/, 10];
                    case 10: return [2 /*return*/];
                }
            });
        });
    };
    return class_1;
}(Action2)));
