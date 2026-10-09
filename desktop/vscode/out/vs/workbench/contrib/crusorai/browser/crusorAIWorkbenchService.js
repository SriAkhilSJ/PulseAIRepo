/*---------------------------------------------------------------------------------------------
 * Phase-A Code OSS sensor adapter. All internal service imports terminate here.
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
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { isCodeEditor, isDiffEditor } from '../../../../editor/browser/editorBrowser.js';
import { IBulkEditService, ResourceTextEdit } from '../../../../editor/browser/services/bulkEditService.js';
import { Position } from '../../../../editor/common/core/position.js';
import { ILanguageService } from '../../../../editor/common/languages/language.js';
import { isLocationLink } from '../../../../editor/common/languages.js';
import { ILanguageFeaturesService } from '../../../../editor/common/services/languageFeatures.js';
import { IModelService } from '../../../../editor/common/services/model.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { IContextKeyService, RawContextKey } from '../../../../platform/contextkey/common/contextkey.js';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { TerminalCapability } from '../../../../platform/terminal/common/capabilities/capabilities.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IMarkerService, MarkerSeverity } from '../../../../platform/markers/common/markers.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IWorkspaceTrustManagementService, IWorkspaceTrustRequestService } from '../../../../platform/workspace/common/workspaceTrust.js';
import { ISCMService } from '../../scm/common/scm.js';
import { ITestResultService } from '../../testing/common/testResultService.js';
import { ITestService } from '../../testing/common/testService.js';
import { TestResultState, TestRunProfileBitset } from '../../testing/common/testTypes.js';
import { ITaskService } from '../../tasks/common/taskService.js';
import { TaskRunSource } from '../../tasks/common/tasks.js';
import { ITerminalService } from '../../terminal/browser/terminal.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { QueryBuilder } from '../../../services/search/common/queryBuilder.js';
import { ISearchService, isFileMatch, resultIsMatch } from '../../../services/search/common/search.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import { CRUSOR_AI_WORKBENCH_CAPABILITIES, } from '../common/crusorAIWorkbenchCapabilities.js';
var WIRED_CAPABILITIES = new Set([
    'editor.activeSelection', 'editor.dirtyText', 'language.symbols',
    'language.definitions', 'language.references', 'diagnostics.markers',
    'search.workspace', 'scm.state',
    'edit.nativeDiff', 'edit.bulkApply', 'edit.undoRedo', 'terminal.native',
    'tasks.discover', 'tasks.run', 'tests.discover', 'tests.run', 'tests.results', 'workspace.trust',
    'preview.open',
]);
var DEFAULT_TERMINAL_TIMEOUT_MS = 120000;
var MIN_TERMINAL_TIMEOUT_MS = 1000;
var MAX_TERMINAL_TIMEOUT_MS = 10 * 60000;
var DEFAULT_TERMINAL_OUTPUT_CHARS = 64000;
var MAX_TERMINAL_OUTPUT_CHARS = 256000;
var CRUSOR_AI_DIFF_SCHEME = 'crusorai-diff';
var MAX_INLINE_DIFF_CHARS = 512000;
var MAX_INLINE_DIFF_MODELS = 64;
function range(value) {
    return {
        startLine: value.startLineNumber,
        startColumn: value.startColumn,
        endLine: value.endLineNumber,
        endColumn: value.endColumn,
    };
}
function severity(value) {
    if (value === MarkerSeverity.Error) {
        return 'error';
    }
    if (value === MarkerSeverity.Warning) {
        return 'warning';
    }
    if (value === MarkerSeverity.Info) {
        return 'info';
    }
    return 'hint';
}
function markerCode(marker) {
    var _a;
    if (typeof marker.code === 'string') {
        return marker.code;
    }
    if (typeof marker.code === 'number') {
        return String(marker.code);
    }
    return (_a = marker.code) === null || _a === void 0 ? void 0 : _a.value;
}
function diagnostic(marker) {
    var _a;
    return {
        resource: marker.resource.toString(),
        range: range(marker),
        severity: severity(marker.severity),
        message: marker.message,
        source: marker.source,
        code: markerCode(marker),
        related: (_a = marker.relatedInformation) === null || _a === void 0 ? void 0 : _a.map(function (info) { return ({
            resource: info.resource.toString(),
            range: range(info),
            message: info.message,
        }); }),
    };
}
var CrusorAIWorkbenchService = /** @class */ (function (_super) {
    __extends(CrusorAIWorkbenchService, _super);
    function CrusorAIWorkbenchService(editorService, textFileService, markerService, languageFeaturesService, languageService, modelService, textModelService, instantiationService, workspaceContextService, searchService, scmService, testService, testResultService, taskService, terminalService, bulkEditService, openerService, trustManagementService, trustRequestService, contextKeyService) {
        var _this = _super.call(this) || this;
        _this.editorService = editorService;
        _this.textFileService = textFileService;
        _this.markerService = markerService;
        _this.languageFeaturesService = languageFeaturesService;
        _this.languageService = languageService;
        _this.modelService = modelService;
        _this.textModelService = textModelService;
        _this.workspaceContextService = workspaceContextService;
        _this.searchService = searchService;
        _this.scmService = scmService;
        _this.testService = testService;
        _this.testResultService = testResultService;
        _this.taskService = taskService;
        _this.terminalService = terminalService;
        _this.bulkEditService = bulkEditService;
        _this.openerService = openerService;
        _this.trustManagementService = trustManagementService;
        _this.trustRequestService = trustRequestService;
        _this.contextKeyService = contextKeyService;
        _this._onDidChangeCapabilities = _this._register(new Emitter());
        _this.onDidChangeCapabilities = _this._onDidChangeCapabilities.event;
        _this._onDidChangeDiagnostics = _this._register(new Emitter());
        _this.onDidChangeDiagnostics = _this._onDidChangeDiagnostics.event;
        _this._onDidChangeTests = _this._register(new Emitter());
        _this.onDidChangeTests = _this._onDidChangeTests.event;
        _this._onDidResolveDiff = _this._register(new Emitter());
        _this.onDidResolveDiff = _this._onDidResolveDiff.event;
        _this.inlineDiffModels = new Map();
        _this.inlineDiffOrder = [];
        _this.activeDiffs = new Map();
        _this.hasActiveDiffKey = new RawContextKey('crusorai.hasActiveDiff', false).bindTo(_this.contextKeyService);
        _this.queryBuilder = instantiationService.createInstance(QueryBuilder);
        _this._register(_this.editorService.onDidActiveEditorChange(function () { return _this.updateActiveDiffContext(); }));
        _this._register(_this.textModelService.registerTextModelContentProvider(CRUSOR_AI_DIFF_SCHEME, {
            provideTextContent: function (resource) { return __awaiter(_this, void 0, void 0, function () {
                var existing, entry, firstLine, language;
                var _a;
                return __generator(this, function (_b) {
                    existing = this.modelService.getModel(resource);
                    if (existing) {
                        return [2 /*return*/, existing];
                    }
                    entry = this.inlineDiffModels.get(resource.toString());
                    if (!entry) {
                        return [2 /*return*/, null];
                    }
                    firstLine = entry.content.split(/\r?\n/, 1)[0];
                    language = this.languageService.createByFilepathOrFirstLine((_a = entry.languageResource) !== null && _a !== void 0 ? _a : resource, firstLine);
                    return [2 /*return*/, this.modelService.createModel(entry.content, language, resource)];
                });
            }); },
        }));
        _this._register(_this.markerService.onMarkerChanged(function (resources) {
            _this._onDidChangeDiagnostics.fire(_this.getDiagnostics(resources.map(function (resource) { return resource.toString(); })));
        }));
        _this._register(_this.trustManagementService.onDidChangeTrust(function () {
            _this._onDidChangeCapabilities.fire(_this.getCapabilities());
        }));
        _this._register(_this.testResultService.onResultsChanged(function () {
            var latest = _this.testResultService.results[0];
            if (latest) {
                _this._onDidChangeTests.fire(_this.testReceipt(latest));
            }
        }));
        return _this;
    }
    CrusorAIWorkbenchService.prototype.isWorkspaceTrusted = function () {
        return this.trustManagementService.isWorkspaceTrusted();
    };
    CrusorAIWorkbenchService.prototype.getCapabilities = function () {
        var trusted = this.isWorkspaceTrusted();
        return CRUSOR_AI_WORKBENCH_CAPABILITIES.map(function (descriptor) { return ({
            id: descriptor.id,
            availability: descriptor.requiresTrust && !trusted
                ? 'blocked'
                : WIRED_CAPABILITIES.has(descriptor.id) ? 'available' : 'degraded',
            detail: WIRED_CAPABILITIES.has(descriptor.id)
                ? undefined
                : 'Adapter scheduled for a later host milestone',
        }); });
    };
    CrusorAIWorkbenchService.prototype.getActiveEditorContext = function () {
        return __awaiter(this, arguments, Promise, function (includeVisibleText) {
            var control, editor, model, selection, selectedText, visibleText;
            if (includeVisibleText === void 0) { includeVisibleText = false; }
            return __generator(this, function (_a) {
                control = this.editorService.activeTextEditorControl;
                editor = isCodeEditor(control)
                    ? control
                    : isDiffEditor(control) ? control.getModifiedEditor() : undefined;
                model = editor === null || editor === void 0 ? void 0 : editor.getModel();
                if (!editor || !model) {
                    return [2 /*return*/, undefined];
                }
                selection = editor.getSelection();
                selectedText = selection && !selection.isEmpty()
                    ? model.getValueInRange(selection).slice(0, 20000)
                    : undefined;
                visibleText = includeVisibleText
                    ? editor.getVisibleRanges().map(function (item) { return model.getValueInRange(item); }).join('\n...\n').slice(0, 32000)
                    : undefined;
                return [2 /*return*/, {
                        resource: model.uri.toString(),
                        languageId: model.getLanguageId(),
                        versionId: model.getVersionId(),
                        dirty: this.textFileService.isDirty(model.uri),
                        selection: selection ? range(selection) : undefined,
                        selectedText: selectedText,
                        visibleText: visibleText,
                    }];
            });
        });
    };
    CrusorAIWorkbenchService.prototype.getDiagnostics = function (resources) {
        var _this = this;
        if (!resources || resources.length === 0) {
            return this.markerService.read({ take: 500 }).map(diagnostic);
        }
        return resources.flatMap(function (value) {
            return _this.markerService.read({ resource: URI.parse(value), take: 200 }).map(diagnostic);
        });
    };
    CrusorAIWorkbenchService.prototype.getDocumentSymbols = function (resource) {
        return __awaiter(this, void 0, Promise, function () {
            var _this = this;
            return __generator(this, function (_a) {
                return [2 /*return*/, this.withModel(resource, function (model) { return __awaiter(_this, void 0, void 0, function () {
                        var result, _i, _a, provider, symbols, _b, _c, symbol, _d;
                        return __generator(this, function (_e) {
                            switch (_e.label) {
                                case 0:
                                    result = [];
                                    _i = 0, _a = this.languageFeaturesService.documentSymbolProvider.ordered(model);
                                    _e.label = 1;
                                case 1:
                                    if (!(_i < _a.length)) return [3 /*break*/, 6];
                                    provider = _a[_i];
                                    _e.label = 2;
                                case 2:
                                    _e.trys.push([2, 4, , 5]);
                                    return [4 /*yield*/, Promise.resolve(provider.provideDocumentSymbols(model, CancellationToken.None))];
                                case 3:
                                    symbols = _e.sent();
                                    for (_b = 0, _c = symbols !== null && symbols !== void 0 ? symbols : []; _b < _c.length; _b++) {
                                        symbol = _c[_b];
                                        result.push(this.symbol(symbol));
                                    }
                                    return [3 /*break*/, 5];
                                case 4:
                                    _d = _e.sent();
                                    return [3 /*break*/, 5];
                                case 5:
                                    _i++;
                                    return [3 /*break*/, 1];
                                case 6: return [2 /*return*/, result];
                            }
                        });
                    }); })];
            });
        });
    };
    CrusorAIWorkbenchService.prototype.getDefinitions = function (resource, line, column) {
        return __awaiter(this, void 0, Promise, function () {
            var _this = this;
            return __generator(this, function (_a) {
                return [2 /*return*/, this.withModel(resource, function (model) { return __awaiter(_this, void 0, void 0, function () {
                        var result, position, _i, _a, provider, value, items, _b, items_1, item, linked, _c;
                        var _d;
                        return __generator(this, function (_e) {
                            switch (_e.label) {
                                case 0:
                                    result = [];
                                    position = new Position(line, column);
                                    _i = 0, _a = this.languageFeaturesService.definitionProvider.ordered(model);
                                    _e.label = 1;
                                case 1:
                                    if (!(_i < _a.length)) return [3 /*break*/, 6];
                                    provider = _a[_i];
                                    _e.label = 2;
                                case 2:
                                    _e.trys.push([2, 4, , 5]);
                                    return [4 /*yield*/, Promise.resolve(provider.provideDefinition(model, position, CancellationToken.None))];
                                case 3:
                                    value = _e.sent();
                                    items = Array.isArray(value) ? value : value ? [value] : [];
                                    for (_b = 0, items_1 = items; _b < items_1.length; _b++) {
                                        item = items_1[_b];
                                        linked = isLocationLink(item);
                                        result.push({
                                            resource: item.uri.toString(),
                                            range: range(linked ? (_d = item.targetSelectionRange) !== null && _d !== void 0 ? _d : item.range : item.range),
                                        });
                                    }
                                    return [3 /*break*/, 5];
                                case 4:
                                    _c = _e.sent();
                                    return [3 /*break*/, 5];
                                case 5:
                                    _i++;
                                    return [3 /*break*/, 1];
                                case 6: return [2 /*return*/, result];
                            }
                        });
                    }); })];
            });
        });
    };
    CrusorAIWorkbenchService.prototype.getReferences = function (resource, line, column) {
        return __awaiter(this, void 0, Promise, function () {
            var _this = this;
            return __generator(this, function (_a) {
                return [2 /*return*/, this.withModel(resource, function (model) { return __awaiter(_this, void 0, void 0, function () {
                        var result, position, _i, _a, provider, items, _b, _c, item, _d;
                        return __generator(this, function (_e) {
                            switch (_e.label) {
                                case 0:
                                    result = [];
                                    position = new Position(line, column);
                                    _i = 0, _a = this.languageFeaturesService.referenceProvider.ordered(model);
                                    _e.label = 1;
                                case 1:
                                    if (!(_i < _a.length)) return [3 /*break*/, 6];
                                    provider = _a[_i];
                                    _e.label = 2;
                                case 2:
                                    _e.trys.push([2, 4, , 5]);
                                    return [4 /*yield*/, Promise.resolve(provider.provideReferences(model, position, { includeDeclaration: true }, CancellationToken.None))];
                                case 3:
                                    items = _e.sent();
                                    for (_b = 0, _c = items !== null && items !== void 0 ? items : []; _b < _c.length; _b++) {
                                        item = _c[_b];
                                        result.push({ resource: item.uri.toString(), range: range(item.range) });
                                    }
                                    return [3 /*break*/, 5];
                                case 4:
                                    _d = _e.sent();
                                    return [3 /*break*/, 5];
                                case 5:
                                    _i++;
                                    return [3 /*break*/, 1];
                                case 6: return [2 /*return*/, result];
                            }
                        });
                    }); })];
            });
        });
    };
    CrusorAIWorkbenchService.prototype.openResource = function (resource, selection) {
        return __awaiter(this, void 0, Promise, function () {
            var uri;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        uri = URI.parse(resource);
                        if (!(!selection && (uri.scheme === 'http' || uri.scheme === 'https'))) return [3 /*break*/, 2];
                        return [4 /*yield*/, this.openerService.open(uri, { openExternal: true })];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                    case 2: return [4 /*yield*/, this.editorService.openEditor({
                            resource: uri,
                            options: selection ? {
                                selection: {
                                    startLineNumber: selection.startLine,
                                    startColumn: selection.startColumn,
                                    endLineNumber: selection.endLine,
                                    endColumn: selection.endColumn,
                                },
                            } : undefined,
                        })];
                    case 3:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.openNativeDiff = function (original, modified, label) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, this.editorService.openEditor({
                            original: { resource: URI.parse(original) },
                            modified: { resource: URI.parse(modified) },
                            label: label,
                        })];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.openInlineDiff = function (request) {
        return __awaiter(this, void 0, Promise, function () {
            var languageResource, fileName, key, original, modified;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        if (!request.toolId.trim()) {
                            throw new Error('Crusor inline diff is missing its tool id');
                        }
                        if (request.original.length > MAX_INLINE_DIFF_CHARS || request.modified.length > MAX_INLINE_DIFF_CHARS) {
                            throw new Error("Crusor inline diff exceeds ".concat(MAX_INLINE_DIFF_CHARS.toLocaleString(), " characters per side"));
                        }
                        languageResource = request.resource
                            ? /^[a-z][a-z0-9+.-]*:/i.test(request.resource) ? URI.parse(request.resource) : URI.file(request.resource)
                            : undefined;
                        fileName = (languageResource === null || languageResource === void 0 ? void 0 : languageResource.path.split('/').pop()) || 'proposed-change.txt';
                        key = "".concat(request.toolId.replace(/[^a-z0-9._-]/gi, '_').slice(0, 96), "-").concat(Date.now().toString(36));
                        original = URI.from({ scheme: CRUSOR_AI_DIFF_SCHEME, authority: 'crusorai', path: "/".concat(key, "/before/").concat(fileName) });
                        modified = URI.from({ scheme: CRUSOR_AI_DIFF_SCHEME, authority: 'crusorai', path: "/".concat(key, "/after/").concat(fileName) });
                        this.rememberInlineDiff(original, request.original, languageResource);
                        this.rememberInlineDiff(modified, request.modified, languageResource);
                        this.activeDiffs.set(modified.toString(), {
                            toolId: request.toolId,
                            originalUri: original,
                            modifiedUri: modified,
                            label: request.label,
                        });
                        return [4 /*yield*/, this.openNativeDiff(original.toString(), modified.toString(), request.label)];
                    case 1:
                        _a.sent();
                        this.updateActiveDiffContext();
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.acceptActiveDiff = function () {
        var _a;
        var diff = this.getActiveDiffForCurrentEditor();
        if (!diff) {
            return;
        }
        this.activeDiffs.delete(diff.modifiedUri.toString());
        this._onDidResolveDiff.fire({ toolId: diff.toolId, approved: true });
        var active = this.editorService.activeEditor;
        if (active) {
            var groupId = (_a = this.editorService.activeEditorPane) === null || _a === void 0 ? void 0 : _a.group.id;
            if (groupId !== undefined) {
                void this.editorService.closeEditor({ editor: active, groupId: groupId });
            }
        }
        this.updateActiveDiffContext();
    };
    CrusorAIWorkbenchService.prototype.rejectActiveDiff = function () {
        var _a;
        var diff = this.getActiveDiffForCurrentEditor();
        if (!diff) {
            return;
        }
        this.activeDiffs.delete(diff.modifiedUri.toString());
        this._onDidResolveDiff.fire({ toolId: diff.toolId, approved: false });
        var active = this.editorService.activeEditor;
        if (active) {
            var groupId = (_a = this.editorService.activeEditorPane) === null || _a === void 0 ? void 0 : _a.group.id;
            if (groupId !== undefined) {
                void this.editorService.closeEditor({ editor: active, groupId: groupId });
            }
        }
        this.updateActiveDiffContext();
    };
    CrusorAIWorkbenchService.prototype.hasActiveDiff = function () {
        return this.getActiveDiffForCurrentEditor() !== undefined;
    };
    CrusorAIWorkbenchService.prototype.updateActiveDiffContext = function () {
        this.hasActiveDiffKey.set(this.hasActiveDiff());
    };
    CrusorAIWorkbenchService.prototype.getActiveDiffForCurrentEditor = function () {
        var _a, _b, _c, _d;
        var activeEditor = this.editorService.activeEditor;
        if (!activeEditor) {
            return undefined;
        }
        var modifiedUri = (_c = (_b = (_a = activeEditor === null || activeEditor === void 0 ? void 0 : activeEditor.modified) === null || _a === void 0 ? void 0 : _a.resource) === null || _b === void 0 ? void 0 : _b.toString()) !== null && _c !== void 0 ? _c : (_d = activeEditor === null || activeEditor === void 0 ? void 0 : activeEditor.resource) === null || _d === void 0 ? void 0 : _d.toString();
        if (modifiedUri && this.activeDiffs.has(modifiedUri)) {
            return this.activeDiffs.get(modifiedUri);
        }
        for (var _i = 0, _e = this.activeDiffs.values(); _i < _e.length; _i++) {
            var diff = _e[_i];
            if (diff.modifiedUri.toString() === modifiedUri || diff.originalUri.toString() === modifiedUri) {
                return diff;
            }
        }
        return undefined;
    };
    CrusorAIWorkbenchService.prototype.requestWorkspaceTrust = function () {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        if (this.trustManagementService.isWorkspaceTrusted()) {
                            return [2 /*return*/, true];
                        }
                        return [4 /*yield*/, this.trustRequestService.requestWorkspaceTrust({
                                message: 'Crusor needs workspace trust before it can modify files or run commands.',
                            })];
                    case 1: return [2 /*return*/, (_a.sent()) === true];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.searchWorkspace = function (pattern_1) {
        return __awaiter(this, arguments, Promise, function (pattern, maxResults) {
            var folders, query, matches, seen, consume, complete, _i, _a, file;
            if (maxResults === void 0) { maxResults = 100; }
            return __generator(this, function (_b) {
                switch (_b.label) {
                    case 0:
                        folders = this.workspaceContextService.getWorkspace().folders.map(function (folder) { return folder.uri; });
                        query = this.queryBuilder.text({ pattern: pattern, isRegExp: false, isCaseSensitive: false, isWordMatch: false }, folders.length > 0 ? folders : undefined, {
                            _reason: 'crusorAI',
                            maxResults: maxResults,
                            previewOptions: { matchLines: 1, charsPerLine: 180 },
                            surroundingContext: 0,
                        });
                        matches = [];
                        seen = new Set();
                        consume = function (file) {
                            var _a, _b, _c;
                            for (var _i = 0, _d = (_a = file.results) !== null && _a !== void 0 ? _a : []; _i < _d.length; _i++) {
                                var item = _d[_i];
                                if (!resultIsMatch(item)) {
                                    continue;
                                }
                                var location = (_b = item.rangeLocations[0]) === null || _b === void 0 ? void 0 : _b.source;
                                var resource = ((_c = item.uri) !== null && _c !== void 0 ? _c : file.resource).toString();
                                var key = "".concat(resource, ":").concat(location === null || location === void 0 ? void 0 : location.startLineNumber, ":").concat(location === null || location === void 0 ? void 0 : location.startColumn);
                                if (seen.has(key) || matches.length >= maxResults) {
                                    continue;
                                }
                                seen.add(key);
                                matches.push({
                                    resource: resource,
                                    range: location ? {
                                        startLine: location.startLineNumber + 1,
                                        startColumn: location.startColumn + 1,
                                        endLine: location.endLineNumber + 1,
                                        endColumn: location.endColumn + 1,
                                    } : undefined,
                                    preview: item.previewText,
                                });
                            }
                        };
                        return [4 /*yield*/, this.searchService.textSearch(query, CancellationToken.None, function (item) {
                                if (isFileMatch(item)) {
                                    consume({ resource: URI.revive(item.resource), results: item.results });
                                }
                            })];
                    case 1:
                        complete = _b.sent();
                        for (_i = 0, _a = complete.results; _i < _a.length; _i++) {
                            file = _a[_i];
                            consume({ resource: URI.revive(file.resource), results: file.results });
                        }
                        return [2 /*return*/, matches];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.getSCMState = function () {
        return __spreadArray([], this.scmService.repositories, true).map(function (repository) {
            var _a;
            return ({
                id: repository.provider.id,
                providerId: repository.provider.providerId,
                label: repository.provider.label,
                root: (_a = repository.provider.rootUri) === null || _a === void 0 ? void 0 : _a.toString(),
                resources: repository.provider.groups.flatMap(function (group) { return group.resources.map(function (item) { return ({
                    resource: item.sourceUri.toString(),
                    contextValue: item.contextValue,
                    tooltip: item.decorations.tooltip,
                    groupId: group.id,
                    groupLabel: group.label,
                }); }); }),
            });
        });
    };
    CrusorAIWorkbenchService.prototype.applyWorkspaceEdit = function (request) {
        return __awaiter(this, void 0, Promise, function () {
            var resources, edits, result;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        if (!this.trustManagementService.isWorkspaceTrusted()) {
                            throw new Error('Crusor cannot apply workspace edits before workspace trust is granted');
                        }
                        if (!request.approvalToolId.trim()) {
                            throw new Error('Crusor workspace edit is missing its approval tool id');
                        }
                        resources = __spreadArray([], new Set(request.edits.map(function (edit) { return edit.resource; })), true);
                        edits = request.edits.map(function (edit) { return new ResourceTextEdit(URI.parse(edit.resource), {
                            range: {
                                startLineNumber: edit.range.startLine,
                                startColumn: edit.range.startColumn,
                                endLineNumber: edit.range.endLine,
                                endColumn: edit.range.endColumn,
                            },
                            text: edit.text,
                        }, edit.expectedVersionId); });
                        return [4 /*yield*/, this.bulkEditService.apply(edits, {
                                label: request.label,
                                code: 'crusorai',
                                showPreview: request.showPreview,
                                confirmBeforeUndo: true,
                            })];
                    case 1:
                        result = _a.sent();
                        return [2 /*return*/, { applied: result.isApplied, ariaSummary: result.ariaSummary, resources: resources }];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.discoverTests = function (resources) {
        return __awaiter(this, void 0, Promise, function () {
            var resourceSet, result, _i, _a, test, item, resource;
            var _b;
            return __generator(this, function (_c) {
                switch (_c.label) {
                    case 0: return [4 /*yield*/, this.testService.syncTests()];
                    case 1:
                        _c.sent();
                        resourceSet = resources ? new Set(resources) : undefined;
                        result = [];
                        for (_i = 0, _a = this.testService.collection.all; _i < _a.length; _i++) {
                            test = _a[_i];
                            item = test.item;
                            resource = (_b = item.uri) === null || _b === void 0 ? void 0 : _b.toString();
                            if (resourceSet && (!resource || !resourceSet.has(resource))) {
                                continue;
                            }
                            result.push({
                                id: item.extId,
                                controllerId: test.controllerId,
                                label: item.label,
                                resource: resource,
                                range: item.range ? range(item.range) : undefined,
                            });
                            if (result.length >= 1000) {
                                break;
                            }
                        }
                        return [2 /*return*/, result];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.runTests = function (request) {
        return __awaiter(this, void 0, Promise, function () {
            var selected, _i, _a, id, item, _b, _c, value, _d, _e, item, exclude, _f, _g, id, item, result;
            var _h, _j, _k;
            return __generator(this, function (_l) {
                switch (_l.label) {
                    case 0:
                        if (!this.trustManagementService.isWorkspaceTrusted()) {
                            throw new Error('Crusor cannot run tests before workspace trust is granted');
                        }
                        if (!request.approvalToolId.trim()) {
                            throw new Error('Crusor test request is missing its approval tool id');
                        }
                        return [4 /*yield*/, this.testService.syncTests()];
                    case 1:
                        _l.sent();
                        selected = new Map();
                        for (_i = 0, _a = (_h = request.testIds) !== null && _h !== void 0 ? _h : []; _i < _a.length; _i++) {
                            id = _a[_i];
                            item = this.testService.collection.getNodeById(id);
                            if (item) {
                                selected.set(item.item.extId, item);
                            }
                        }
                        for (_b = 0, _c = (_j = request.resources) !== null && _j !== void 0 ? _j : []; _b < _c.length; _b++) {
                            value = _c[_b];
                            for (_d = 0, _e = this.testService.collection.getNodeByUrl(URI.parse(value)); _d < _e.length; _d++) {
                                item = _e[_d];
                                selected.set(item.item.extId, item);
                            }
                        }
                        if (selected.size === 0) {
                            throw new Error('Crusor test request did not resolve to any registered tests');
                        }
                        exclude = [];
                        for (_f = 0, _g = (_k = request.excludeIds) !== null && _k !== void 0 ? _k : []; _f < _g.length; _f++) {
                            id = _g[_f];
                            item = this.testService.collection.getNodeById(id);
                            if (item) {
                                exclude.push(item);
                            }
                        }
                        return [4 /*yield*/, this.testService.runTests({
                                group: TestRunProfileBitset.Run,
                                tests: __spreadArray([], selected.values(), true),
                                exclude: exclude,
                                preserveFocus: true,
                            }, CancellationToken.None)];
                    case 2:
                        result = _l.sent();
                        return [2 /*return*/, this.testReceipt(result)];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.discoverTasks = function () {
        return __awaiter(this, void 0, Promise, function () {
            var tasks;
            var _this = this;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, this.taskService.getKnownTasks()];
                    case 1:
                        tasks = _a.sent();
                        return [2 /*return*/, tasks.map(function (task) {
                                var group = task.configurationProperties.group;
                                return {
                                    id: task.getMapKey(),
                                    label: task.getQualifiedLabel(),
                                    description: _this.taskService.getTaskDescription(task),
                                    group: typeof group === 'string' ? group : group === null || group === void 0 ? void 0 : group._id,
                                    background: task.configurationProperties.isBackground === true,
                                };
                            })];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.runTask = function (request) {
        return __awaiter(this, void 0, Promise, function () {
            var tasks, task, summary;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        if (!this.trustManagementService.isWorkspaceTrusted()) {
                            throw new Error('Crusor cannot run tasks before workspace trust is granted');
                        }
                        if (!request.approvalToolId.trim()) {
                            throw new Error('Crusor task request is missing its approval tool id');
                        }
                        return [4 /*yield*/, this.taskService.getKnownTasks()];
                    case 1:
                        tasks = _a.sent();
                        task = tasks.find(function (candidate) {
                            return candidate.getMapKey() === request.taskId ||
                                candidate._id === request.taskId ||
                                candidate.configurationProperties.identifier === request.taskId;
                        });
                        if (!task) {
                            throw new Error("Crusor could not resolve task: ".concat(request.taskId));
                        }
                        return [4 /*yield*/, this.taskService.run(task, undefined, TaskRunSource.ChatAgent)];
                    case 2:
                        summary = _a.sent();
                        return [2 /*return*/, {
                                taskId: request.taskId,
                                state: (summary === null || summary === void 0 ? void 0 : summary.exitCode) === 0 ? 'passed' : typeof (summary === null || summary === void 0 ? void 0 : summary.exitCode) === 'number' ? 'failed' : 'unknown',
                                exitCode: summary === null || summary === void 0 ? void 0 : summary.exitCode,
                            }];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.runInTerminal = function (request) {
        return __awaiter(this, void 0, Promise, function () {
            var commandText, timeoutMs, maxOutputChars, instance, startedAt, listeners, attached, fallbackOutput, fallbackTruncated, hasShellIntegration, finish, fail, boundOutput, completion, finishCommand, attachCommandDetection, existing, error_1;
            var _a, _b, _c;
            return __generator(this, function (_d) {
                switch (_d.label) {
                    case 0:
                        if (!this.trustManagementService.isWorkspaceTrusted()) {
                            throw new Error('Crusor cannot run terminal commands before workspace trust is granted');
                        }
                        if (!request.approvalToolId.trim()) {
                            throw new Error('Crusor terminal request is missing its approval tool id');
                        }
                        commandText = request.command.trim();
                        if (!commandText) {
                            throw new Error('Crusor terminal request has an empty command');
                        }
                        timeoutMs = Math.min(MAX_TERMINAL_TIMEOUT_MS, Math.max(MIN_TERMINAL_TIMEOUT_MS, (_a = request.timeoutMs) !== null && _a !== void 0 ? _a : DEFAULT_TERMINAL_TIMEOUT_MS));
                        maxOutputChars = Math.min(MAX_TERMINAL_OUTPUT_CHARS, Math.max(1000, (_b = request.maxOutputChars) !== null && _b !== void 0 ? _b : DEFAULT_TERMINAL_OUTPUT_CHARS));
                        return [4 /*yield*/, this.terminalService.createAndFocusTerminal({
                                config: { name: (_c = request.name) !== null && _c !== void 0 ? _c : 'Crusor Agent' },
                                cwd: request.cwd,
                            })];
                    case 1:
                        instance = _d.sent();
                        startedAt = Date.now();
                        listeners = new DisposableStore();
                        attached = new Set();
                        fallbackOutput = '';
                        fallbackTruncated = false;
                        hasShellIntegration = false;
                        boundOutput = function (value) {
                            if (value.length <= maxOutputChars) {
                                return { output: value, truncated: false };
                            }
                            return { output: value.slice(-maxOutputChars), truncated: true };
                        };
                        completion = new Promise(function (resolve, reject) {
                            var done = false;
                            var complete = function (receipt) {
                                if (done) {
                                    return;
                                }
                                done = true;
                                clearTimeout(timer);
                                listeners.dispose();
                                resolve(receipt);
                            };
                            finish = complete;
                            fail = function (error) {
                                if (done) {
                                    return;
                                }
                                done = true;
                                clearTimeout(timer);
                                listeners.dispose();
                                reject(error);
                            };
                            var timer = setTimeout(function () {
                                if (request.interruptOnTimeout) {
                                    void instance.sendSignal('SIGINT');
                                }
                                complete({
                                    terminalId: instance.instanceId,
                                    state: 'timed_out',
                                    durationMs: Date.now() - startedAt,
                                    output: fallbackOutput,
                                    outputTruncated: fallbackTruncated,
                                    shellIntegration: hasShellIntegration,
                                });
                            }, timeoutMs);
                        });
                        finishCommand = function (command) {
                            var _a;
                            if (command.command.trim() !== commandText) {
                                return;
                            }
                            var captured = boundOutput((_a = command.getOutput()) !== null && _a !== void 0 ? _a : fallbackOutput);
                            finish({
                                terminalId: instance.instanceId,
                                state: command.exitCode === 0 ? 'passed' : typeof command.exitCode === 'number' ? 'failed' : 'unknown',
                                exitCode: command.exitCode,
                                durationMs: command.duration || Date.now() - startedAt,
                                output: captured.output,
                                outputTruncated: captured.truncated || fallbackTruncated,
                                shellIntegration: true,
                            });
                        };
                        attachCommandDetection = function (capability) {
                            if (attached.has(capability)) {
                                return;
                            }
                            attached.add(capability);
                            hasShellIntegration = true;
                            listeners.add(capability.onCommandFinished(finishCommand));
                        };
                        existing = instance.capabilities.get(TerminalCapability.CommandDetection);
                        if (existing) {
                            attachCommandDetection(existing);
                        }
                        listeners.add(instance.capabilities.onDidAddCommandDetectionCapability(attachCommandDetection));
                        listeners.add(instance.onLineData(function (line) {
                            var captured = boundOutput("".concat(fallbackOutput).concat(fallbackOutput ? '\n' : '').concat(line));
                            fallbackOutput = captured.output;
                            fallbackTruncated || (fallbackTruncated = captured.truncated);
                        }));
                        listeners.add(instance.onExit(function (code) {
                            var exitCode = typeof code === 'number' ? code : undefined;
                            finish({
                                terminalId: instance.instanceId,
                                state: exitCode === 0 ? 'passed' : typeof exitCode === 'number' ? 'failed' : 'unknown',
                                exitCode: exitCode,
                                durationMs: Date.now() - startedAt,
                                output: fallbackOutput,
                                outputTruncated: fallbackTruncated,
                                shellIntegration: hasShellIntegration,
                            });
                        }));
                        _d.label = 2;
                    case 2:
                        _d.trys.push([2, 4, , 5]);
                        return [4 /*yield*/, instance.sendText(request.command, true, true)];
                    case 3:
                        _d.sent();
                        return [3 /*break*/, 5];
                    case 4:
                        error_1 = _d.sent();
                        fail(error_1);
                        return [3 /*break*/, 5];
                    case 5: return [2 /*return*/, completion];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.rememberInlineDiff = function (resource, content, languageResource) {
        var key = resource.toString();
        this.inlineDiffModels.set(key, { content: content, languageResource: languageResource });
        this.inlineDiffOrder.push(key);
        while (this.inlineDiffOrder.length > MAX_INLINE_DIFF_MODELS) {
            var removed = this.inlineDiffOrder.shift();
            if (removed) {
                this.inlineDiffModels.delete(removed);
            }
        }
    };
    CrusorAIWorkbenchService.prototype.testReceipt = function (result) {
        var failed = result.counts[TestResultState.Failed] + result.counts[TestResultState.Errored];
        return {
            runId: result.id,
            state: result.completedAt === undefined ? 'running' : failed > 0 ? 'failed' : 'passed',
            passed: result.counts[TestResultState.Passed],
            failed: failed,
            skipped: result.counts[TestResultState.Skipped],
        };
    };
    CrusorAIWorkbenchService.prototype.withModel = function (resource, callback) {
        return __awaiter(this, void 0, Promise, function () {
            var reference;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, this.textModelService.createModelReference(URI.parse(resource))];
                    case 1:
                        reference = _a.sent();
                        _a.label = 2;
                    case 2:
                        _a.trys.push([2, , 4, 5]);
                        return [4 /*yield*/, callback(reference.object.textEditorModel)];
                    case 3: return [2 /*return*/, _a.sent()];
                    case 4:
                        reference.dispose();
                        return [7 /*endfinally*/];
                    case 5: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkbenchService.prototype.symbol = function (value) {
        var _this = this;
        var _a;
        return {
            name: value.name,
            kind: String(value.kind),
            range: range(value.range),
            children: (_a = value.children) === null || _a === void 0 ? void 0 : _a.map(function (child) { return _this.symbol(child); }),
        };
    };
    CrusorAIWorkbenchService = __decorate([
        __param(0, IEditorService),
        __param(1, ITextFileService),
        __param(2, IMarkerService),
        __param(3, ILanguageFeaturesService),
        __param(4, ILanguageService),
        __param(5, IModelService),
        __param(6, ITextModelService),
        __param(7, IInstantiationService),
        __param(8, IWorkspaceContextService),
        __param(9, ISearchService),
        __param(10, ISCMService),
        __param(11, ITestService),
        __param(12, ITestResultService),
        __param(13, ITaskService),
        __param(14, ITerminalService),
        __param(15, IBulkEditService),
        __param(16, IOpenerService),
        __param(17, IWorkspaceTrustManagementService),
        __param(18, IWorkspaceTrustRequestService),
        __param(19, IContextKeyService)
    ], CrusorAIWorkbenchService);
    return CrusorAIWorkbenchService;
}(Disposable));
export { CrusorAIWorkbenchService };
