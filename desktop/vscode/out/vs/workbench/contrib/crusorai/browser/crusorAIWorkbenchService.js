/*---------------------------------------------------------------------------------------------
 * Phase-A Code OSS sensor adapter. All internal service imports terminate here.
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
import { MultiDiffEditorInput } from '../../multiDiffEditor/browser/multiDiffEditorInput.js';
import { EditorActivation } from '../../../../platform/editor/common/editor.js';
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
const WIRED_CAPABILITIES = new Set([
    'editor.activeSelection', 'editor.dirtyText', 'language.symbols',
    'language.definitions', 'language.references', 'diagnostics.markers',
    'search.workspace', 'scm.state',
    'edit.nativeDiff', 'edit.bulkApply', 'edit.undoRedo', 'terminal.native',
    'tasks.discover', 'tasks.run', 'tests.discover', 'tests.run', 'tests.results', 'workspace.trust',
    'preview.open',
]);
const DEFAULT_TERMINAL_TIMEOUT_MS = 120_000;
const MIN_TERMINAL_TIMEOUT_MS = 1_000;
const MAX_TERMINAL_TIMEOUT_MS = 10 * 60_000;
const DEFAULT_TERMINAL_OUTPUT_CHARS = 64_000;
const MAX_TERMINAL_OUTPUT_CHARS = 256_000;
const CRUSOR_AI_DIFF_SCHEME = 'crusorai-diff';
const MAX_INLINE_DIFF_CHARS = 512_000;
const MAX_INLINE_DIFF_MODELS = 64;
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
    if (typeof marker.code === 'string') {
        return marker.code;
    }
    if (typeof marker.code === 'number') {
        return String(marker.code);
    }
    return marker.code?.value;
}
function diagnostic(marker) {
    return {
        resource: marker.resource.toString(),
        range: range(marker),
        severity: severity(marker.severity),
        message: marker.message,
        source: marker.source,
        code: markerCode(marker),
        related: marker.relatedInformation?.map(info => ({
            resource: info.resource.toString(),
            range: range(info),
            message: info.message,
        })),
    };
}
let CrusorAIWorkbenchService = class CrusorAIWorkbenchService extends Disposable {
    constructor(editorService, textFileService, markerService, languageFeaturesService, languageService, modelService, textModelService, instantiationService, workspaceContextService, searchService, scmService, testService, testResultService, taskService, terminalService, bulkEditService, openerService, trustManagementService, trustRequestService, contextKeyService) {
        super();
        this.editorService = editorService;
        this.textFileService = textFileService;
        this.markerService = markerService;
        this.languageFeaturesService = languageFeaturesService;
        this.languageService = languageService;
        this.modelService = modelService;
        this.textModelService = textModelService;
        this.instantiationService = instantiationService;
        this.workspaceContextService = workspaceContextService;
        this.searchService = searchService;
        this.scmService = scmService;
        this.testService = testService;
        this.testResultService = testResultService;
        this.taskService = taskService;
        this.terminalService = terminalService;
        this.bulkEditService = bulkEditService;
        this.openerService = openerService;
        this.trustManagementService = trustManagementService;
        this.trustRequestService = trustRequestService;
        this.contextKeyService = contextKeyService;
        this._onDidChangeCapabilities = this._register(new Emitter());
        this.onDidChangeCapabilities = this._onDidChangeCapabilities.event;
        this._onDidChangeDiagnostics = this._register(new Emitter());
        this.onDidChangeDiagnostics = this._onDidChangeDiagnostics.event;
        this._onDidChangeTests = this._register(new Emitter());
        this.onDidChangeTests = this._onDidChangeTests.event;
        this._onDidResolveDiff = this._register(new Emitter());
        this.onDidResolveDiff = this._onDidResolveDiff.event;
        this.inlineDiffModels = new Map();
        this.inlineDiffOrder = [];
        this.activeDiffs = new Map();
        this.hasActiveDiffKey = new RawContextKey('crusorai.hasActiveDiff', false).bindTo(this.contextKeyService);
        this.queryBuilder = this.instantiationService.createInstance(QueryBuilder);
        this._register(this.editorService.onDidActiveEditorChange(() => this.updateActiveDiffContext()));
        this._register(this.textModelService.registerTextModelContentProvider(CRUSOR_AI_DIFF_SCHEME, {
            provideTextContent: async (resource) => {
                const existing = this.modelService.getModel(resource);
                if (existing) {
                    return existing;
                }
                const entry = this.inlineDiffModels.get(resource.toString());
                if (!entry) {
                    return null;
                }
                const firstLine = entry.content.split(/\r?\n/, 1)[0];
                const language = this.languageService.createByFilepathOrFirstLine(entry.languageResource ?? resource, firstLine);
                return this.modelService.createModel(entry.content, language, resource);
            },
        }));
        this._register(this.markerService.onMarkerChanged(resources => {
            this._onDidChangeDiagnostics.fire(this.getDiagnostics(resources.map(resource => resource.toString())));
        }));
        this._register(this.trustManagementService.onDidChangeTrust(() => {
            this._onDidChangeCapabilities.fire(this.getCapabilities());
        }));
        this._register(this.testResultService.onResultsChanged(() => {
            const latest = this.testResultService.results[0];
            if (latest) {
                this._onDidChangeTests.fire(this.testReceipt(latest));
            }
        }));
    }
    isWorkspaceTrusted() {
        return this.trustManagementService.isWorkspaceTrusted();
    }
    getCapabilities() {
        const trusted = this.isWorkspaceTrusted();
        return CRUSOR_AI_WORKBENCH_CAPABILITIES.map(descriptor => ({
            id: descriptor.id,
            availability: descriptor.requiresTrust && !trusted
                ? 'blocked'
                : WIRED_CAPABILITIES.has(descriptor.id) ? 'available' : 'degraded',
            detail: WIRED_CAPABILITIES.has(descriptor.id)
                ? undefined
                : 'Adapter scheduled for a later host milestone',
        }));
    }
    async getActiveEditorContext(includeVisibleText = false) {
        const control = this.editorService.activeTextEditorControl;
        const editor = isCodeEditor(control)
            ? control
            : isDiffEditor(control) ? control.getModifiedEditor() : undefined;
        const model = editor?.getModel();
        if (!editor || !model) {
            return undefined;
        }
        const selection = editor.getSelection();
        const selectedText = selection && !selection.isEmpty()
            ? model.getValueInRange(selection).slice(0, 20_000)
            : undefined;
        const visibleText = includeVisibleText
            ? editor.getVisibleRanges().map(item => model.getValueInRange(item)).join('\n...\n').slice(0, 32_000)
            : undefined;
        return {
            resource: model.uri.toString(),
            languageId: model.getLanguageId(),
            versionId: model.getVersionId(),
            dirty: this.textFileService.isDirty(model.uri),
            selection: selection ? range(selection) : undefined,
            selectedText,
            visibleText,
        };
    }
    getDiagnostics(resources) {
        if (!resources || resources.length === 0) {
            return this.markerService.read({ take: 500 }).map(diagnostic);
        }
        return resources.flatMap(value => this.markerService.read({ resource: URI.parse(value), take: 200 }).map(diagnostic));
    }
    async getDocumentSymbols(resource) {
        return this.withModel(resource, async (model) => {
            const result = [];
            for (const provider of this.languageFeaturesService.documentSymbolProvider.ordered(model)) {
                try {
                    const symbols = await Promise.resolve(provider.provideDocumentSymbols(model, CancellationToken.None));
                    for (const symbol of symbols ?? []) {
                        result.push(this.symbol(symbol));
                    }
                }
                catch { /* one extension provider must not break all semantic context */ }
            }
            return result;
        });
    }
    async getDefinitions(resource, line, column) {
        return this.withModel(resource, async (model) => {
            const result = [];
            const position = new Position(line, column);
            for (const provider of this.languageFeaturesService.definitionProvider.ordered(model)) {
                try {
                    const value = await Promise.resolve(provider.provideDefinition(model, position, CancellationToken.None));
                    const items = Array.isArray(value) ? value : value ? [value] : [];
                    for (const item of items) {
                        const linked = isLocationLink(item);
                        result.push({
                            resource: item.uri.toString(),
                            range: range(linked ? item.targetSelectionRange ?? item.range : item.range),
                        });
                    }
                }
                catch { /* provider isolation */ }
            }
            return result;
        });
    }
    async getReferences(resource, line, column) {
        return this.withModel(resource, async (model) => {
            const result = [];
            const position = new Position(line, column);
            for (const provider of this.languageFeaturesService.referenceProvider.ordered(model)) {
                try {
                    const items = await Promise.resolve(provider.provideReferences(model, position, { includeDeclaration: true }, CancellationToken.None));
                    for (const item of items ?? []) {
                        result.push({ resource: item.uri.toString(), range: range(item.range) });
                    }
                }
                catch { /* provider isolation */ }
            }
            return result;
        });
    }
    async openResource(resource, selection) {
        const uri = URI.parse(resource);
        // Web URLs are not text-model resources: the textmodel resolver
        // refuses them ("Unable to resolve resource http://localhost:3000/",
        // owner log 2026-09-08 — the old navigate card revealed the URL and
        // the editor paged in an error). Hermes-equivalent behavior: a URL
        // opens in the user's browser, never a text editor pane.
        if (!selection && (uri.scheme === 'http' || uri.scheme === 'https')) {
            await this.openerService.open(uri, { openExternal: true });
            return;
        }
        await this.editorService.openEditor({
            resource: uri,
            options: selection ? {
                selection: {
                    startLineNumber: selection.startLine,
                    startColumn: selection.startColumn,
                    endLineNumber: selection.endLine,
                    endColumn: selection.endColumn,
                },
            } : undefined,
        });
    }
    async openNativeDiff(original, modified, label) {
        await this.editorService.openEditor({
            original: { resource: URI.parse(original) },
            modified: { resource: URI.parse(modified) },
            label,
        });
    }
    async openInlineDiff(request) {
        if (!request.toolId.trim()) {
            throw new Error('Crusor inline diff is missing its tool id');
        }
        if (request.original.length > MAX_INLINE_DIFF_CHARS || request.modified.length > MAX_INLINE_DIFF_CHARS) {
            throw new Error(`Crusor inline diff exceeds ${MAX_INLINE_DIFF_CHARS.toLocaleString()} characters per side`);
        }
        const languageResource = request.resource
            ? /^[a-z][a-z0-9+.-]*:/i.test(request.resource) ? URI.parse(request.resource) : URI.file(request.resource)
            : undefined;
        // The review must read as THE FILE being edited, the way
        // Copilot's does: its original/modified text models carry
        // the file's own path and differ only by scheme/authority
        // (chatEditingSession / TextModelRefUri). The multi-diff
        // header derives its label from the modified resource
        // (file name + folder), and differing paths would flag
        // the change a "rename" and print both synthetic paths.
        // So both sides share the file's path; the authority
        // carries the side plus a stamp so concurrent reviews of
        // the same file never share a model.
        const filePath = languageResource?.path || '/proposed-change.txt';
        const stamp = Date.now().toString(36);
        const original = URI.from({ scheme: CRUSOR_AI_DIFF_SCHEME, authority: `original-${stamp}`, path: filePath });
        const modified = URI.from({ scheme: CRUSOR_AI_DIFF_SCHEME, authority: `modified-${stamp}`, path: filePath });
        this.rememberInlineDiff(original, request.original, languageResource);
        this.rememberInlineDiff(modified, request.modified, languageResource);
        this.activeDiffs.set(modified.toString(), {
            toolId: request.toolId,
            originalUri: original,
            modifiedUri: modified,
            label: request.label,
        });
        // Review opens the way Copilot's chat editing opens its
        // "Suggested Edits" (chatEditingSession.show): a
        // MultiDiffEditorInput over text models -- ours ride the
        // crusorai-diff content provider above -- opened pinned and
        // active. The multi-diff surface is the review surface: a
        // file header per resource with the real diff editor's
        // green/red inside, instead of a naked two-model diff tab.
        try {
            // The tab names the file under review, not the tool
            // that proposed it; goToFile aims the header's open
            // affordance at the real file, as Copilot's does.
            const fileLabel = filePath.split('/').filter(Boolean).pop() || 'proposed-change.txt';
            const input = MultiDiffEditorInput.fromResourceMultiDiffEditorInput({
                label: fileLabel,
                resources: [{
                        original: { resource: original },
                        modified: { resource: modified },
                        ...(languageResource ? { goToFile: { resource: languageResource } } : {}),
                    }],
            }, this.instantiationService);
            await this.editorService.openEditor(input, { pinned: true, activation: EditorActivation.ACTIVATE });
        }
        catch {
            // A build without the multi-diff editor must not break
            // review: the plain diff editor is the same two models.
            await this.openNativeDiff(original.toString(), modified.toString(), request.label);
        }
        this.updateActiveDiffContext();
    }
    acceptActiveDiff() {
        const diff = this.getActiveDiffForCurrentEditor();
        if (!diff) {
            return;
        }
        this.activeDiffs.delete(diff.modifiedUri.toString());
        this._onDidResolveDiff.fire({ toolId: diff.toolId, approved: true });
        const active = this.editorService.activeEditor;
        if (active) {
            const groupId = this.editorService.activeEditorPane?.group.id;
            if (groupId !== undefined) {
                void this.editorService.closeEditor({ editor: active, groupId });
            }
        }
        this.updateActiveDiffContext();
    }
    rejectActiveDiff() {
        const diff = this.getActiveDiffForCurrentEditor();
        if (!diff) {
            return;
        }
        this.activeDiffs.delete(diff.modifiedUri.toString());
        this._onDidResolveDiff.fire({ toolId: diff.toolId, approved: false });
        const active = this.editorService.activeEditor;
        if (active) {
            const groupId = this.editorService.activeEditorPane?.group.id;
            if (groupId !== undefined) {
                void this.editorService.closeEditor({ editor: active, groupId });
            }
        }
        this.updateActiveDiffContext();
    }
    hasActiveDiff() {
        return this.getActiveDiffForCurrentEditor() !== undefined;
    }
    updateActiveDiffContext() {
        this.hasActiveDiffKey.set(this.hasActiveDiff());
    }
    getActiveDiffForCurrentEditor() {
        const activeEditor = this.editorService.activeEditor;
        if (!activeEditor) {
            return undefined;
        }
        // The review surface is a multi-diff input: its items carry
        // the synthetic modified/original URIs directly.
        if (activeEditor instanceof MultiDiffEditorInput) {
            for (const item of activeEditor.initialResources ?? []) {
                for (const candidate of [item.modifiedUri, item.originalUri]) {
                    const hit = candidate ? this.activeDiffs.get(candidate.toString()) : undefined;
                    if (hit) {
                        return hit;
                    }
                }
            }
            return undefined;
        }
        const modifiedUri = activeEditor?.modified?.resource?.toString()
            ?? activeEditor?.resource?.toString();
        if (modifiedUri && this.activeDiffs.has(modifiedUri)) {
            return this.activeDiffs.get(modifiedUri);
        }
        for (const diff of this.activeDiffs.values()) {
            if (diff.modifiedUri.toString() === modifiedUri || diff.originalUri.toString() === modifiedUri) {
                return diff;
            }
        }
        return undefined;
    }
    async requestWorkspaceTrust() {
        if (this.trustManagementService.isWorkspaceTrusted()) {
            return true;
        }
        return (await this.trustRequestService.requestWorkspaceTrust({
            message: 'Crusor needs workspace trust before it can modify files or run commands.',
        })) === true;
    }
    async searchWorkspace(pattern, maxResults = 100) {
        const folders = this.workspaceContextService.getWorkspace().folders.map(folder => folder.uri);
        const query = this.queryBuilder.text({ pattern, isRegExp: false, isCaseSensitive: false, isWordMatch: false }, folders.length > 0 ? folders : undefined, {
            _reason: 'crusorAI',
            maxResults,
            previewOptions: { matchLines: 1, charsPerLine: 180 },
            surroundingContext: 0,
        });
        const matches = [];
        const seen = new Set();
        const consume = (file) => {
            for (const item of file.results ?? []) {
                if (!resultIsMatch(item)) {
                    continue;
                }
                const location = item.rangeLocations[0]?.source;
                const resource = (item.uri ?? file.resource).toString();
                const key = `${resource}:${location?.startLineNumber}:${location?.startColumn}`;
                if (seen.has(key) || matches.length >= maxResults) {
                    continue;
                }
                seen.add(key);
                matches.push({
                    resource,
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
        const complete = await this.searchService.textSearch(query, CancellationToken.None, item => {
            if (isFileMatch(item)) {
                consume({ resource: URI.revive(item.resource), results: item.results });
            }
        });
        for (const file of complete.results) {
            consume({ resource: URI.revive(file.resource), results: file.results });
        }
        return matches;
    }
    getSCMState() {
        return [...this.scmService.repositories].map(repository => ({
            id: repository.provider.id,
            providerId: repository.provider.providerId,
            label: repository.provider.label,
            root: repository.provider.rootUri?.toString(),
            resources: repository.provider.groups.flatMap(group => group.resources.map(item => ({
                resource: item.sourceUri.toString(),
                contextValue: item.contextValue,
                tooltip: item.decorations.tooltip,
                groupId: group.id,
                groupLabel: group.label,
            }))),
        }));
    }
    async applyWorkspaceEdit(request) {
        if (!this.trustManagementService.isWorkspaceTrusted()) {
            throw new Error('Crusor cannot apply workspace edits before workspace trust is granted');
        }
        if (!request.approvalToolId.trim()) {
            throw new Error('Crusor workspace edit is missing its approval tool id');
        }
        const resources = [...new Set(request.edits.map(edit => edit.resource))];
        const edits = request.edits.map(edit => new ResourceTextEdit(URI.parse(edit.resource), {
            range: {
                startLineNumber: edit.range.startLine,
                startColumn: edit.range.startColumn,
                endLineNumber: edit.range.endLine,
                endColumn: edit.range.endColumn,
            },
            text: edit.text,
        }, edit.expectedVersionId));
        const result = await this.bulkEditService.apply(edits, {
            label: request.label,
            code: 'crusorai',
            showPreview: request.showPreview,
            confirmBeforeUndo: true,
        });
        return { applied: result.isApplied, ariaSummary: result.ariaSummary, resources };
    }
    async discoverTests(resources) {
        await this.testService.syncTests();
        const resourceSet = resources ? new Set(resources) : undefined;
        const result = [];
        for (const test of this.testService.collection.all) {
            const item = test.item;
            const resource = item.uri?.toString();
            if (resourceSet && (!resource || !resourceSet.has(resource))) {
                continue;
            }
            result.push({
                id: item.extId,
                controllerId: test.controllerId,
                label: item.label,
                resource,
                range: item.range ? range(item.range) : undefined,
            });
            if (result.length >= 1_000) {
                break;
            }
        }
        return result;
    }
    async runTests(request) {
        if (!this.trustManagementService.isWorkspaceTrusted()) {
            throw new Error('Crusor cannot run tests before workspace trust is granted');
        }
        if (!request.approvalToolId.trim()) {
            throw new Error('Crusor test request is missing its approval tool id');
        }
        await this.testService.syncTests();
        const selected = new Map();
        for (const id of request.testIds ?? []) {
            const item = this.testService.collection.getNodeById(id);
            if (item) {
                selected.set(item.item.extId, item);
            }
        }
        for (const value of request.resources ?? []) {
            for (const item of this.testService.collection.getNodeByUrl(URI.parse(value))) {
                selected.set(item.item.extId, item);
            }
        }
        if (selected.size === 0) {
            throw new Error('Crusor test request did not resolve to any registered tests');
        }
        const exclude = [];
        for (const id of request.excludeIds ?? []) {
            const item = this.testService.collection.getNodeById(id);
            if (item) {
                exclude.push(item);
            }
        }
        const result = await this.testService.runTests({
            group: TestRunProfileBitset.Run,
            tests: [...selected.values()],
            exclude,
            preserveFocus: true,
        }, CancellationToken.None);
        return this.testReceipt(result);
    }
    async discoverTasks() {
        const tasks = await this.taskService.getKnownTasks();
        return tasks.map(task => {
            const group = task.configurationProperties.group;
            return {
                id: task.getMapKey(),
                label: task.getQualifiedLabel(),
                description: this.taskService.getTaskDescription(task),
                group: typeof group === 'string' ? group : group?._id,
                background: task.configurationProperties.isBackground === true,
            };
        });
    }
    async runTask(request) {
        if (!this.trustManagementService.isWorkspaceTrusted()) {
            throw new Error('Crusor cannot run tasks before workspace trust is granted');
        }
        if (!request.approvalToolId.trim()) {
            throw new Error('Crusor task request is missing its approval tool id');
        }
        const tasks = await this.taskService.getKnownTasks();
        const task = tasks.find(candidate => candidate.getMapKey() === request.taskId ||
            candidate._id === request.taskId ||
            candidate.configurationProperties.identifier === request.taskId);
        if (!task) {
            throw new Error(`Crusor could not resolve task: ${request.taskId}`);
        }
        const summary = await this.taskService.run(task, undefined, TaskRunSource.ChatAgent);
        return {
            taskId: request.taskId,
            state: summary?.exitCode === 0 ? 'passed' : typeof summary?.exitCode === 'number' ? 'failed' : 'unknown',
            exitCode: summary?.exitCode,
        };
    }
    async runInTerminal(request) {
        if (!this.trustManagementService.isWorkspaceTrusted()) {
            throw new Error('Crusor cannot run terminal commands before workspace trust is granted');
        }
        if (!request.approvalToolId.trim()) {
            throw new Error('Crusor terminal request is missing its approval tool id');
        }
        const commandText = request.command.trim();
        if (!commandText) {
            throw new Error('Crusor terminal request has an empty command');
        }
        const timeoutMs = Math.min(MAX_TERMINAL_TIMEOUT_MS, Math.max(MIN_TERMINAL_TIMEOUT_MS, request.timeoutMs ?? DEFAULT_TERMINAL_TIMEOUT_MS));
        const maxOutputChars = Math.min(MAX_TERMINAL_OUTPUT_CHARS, Math.max(1_000, request.maxOutputChars ?? DEFAULT_TERMINAL_OUTPUT_CHARS));
        const instance = await this.terminalService.createAndFocusTerminal({
            config: { name: request.name ?? 'Crusor Agent' },
            cwd: request.cwd,
        });
        const startedAt = Date.now();
        const listeners = new DisposableStore();
        const attached = new Set();
        let fallbackOutput = '';
        let fallbackTruncated = false;
        let hasShellIntegration = false;
        let finish;
        let fail;
        const boundOutput = (value) => {
            if (value.length <= maxOutputChars) {
                return { output: value, truncated: false };
            }
            return { output: value.slice(-maxOutputChars), truncated: true };
        };
        const completion = new Promise((resolve, reject) => {
            let done = false;
            const complete = (receipt) => {
                if (done) {
                    return;
                }
                done = true;
                clearTimeout(timer);
                listeners.dispose();
                resolve(receipt);
            };
            finish = complete;
            fail = error => {
                if (done) {
                    return;
                }
                done = true;
                clearTimeout(timer);
                listeners.dispose();
                reject(error);
            };
            const timer = setTimeout(() => {
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
        const finishCommand = (command) => {
            if (command.command.trim() !== commandText) {
                return;
            }
            const captured = boundOutput(command.getOutput() ?? fallbackOutput);
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
        const attachCommandDetection = (capability) => {
            if (attached.has(capability)) {
                return;
            }
            attached.add(capability);
            hasShellIntegration = true;
            listeners.add(capability.onCommandFinished(finishCommand));
        };
        const existing = instance.capabilities.get(TerminalCapability.CommandDetection);
        if (existing) {
            attachCommandDetection(existing);
        }
        listeners.add(instance.capabilities.onDidAddCommandDetectionCapability(attachCommandDetection));
        listeners.add(instance.onLineData(line => {
            const captured = boundOutput(`${fallbackOutput}${fallbackOutput ? '\n' : ''}${line}`);
            fallbackOutput = captured.output;
            fallbackTruncated ||= captured.truncated;
        }));
        listeners.add(instance.onExit(code => {
            const exitCode = typeof code === 'number' ? code : undefined;
            finish({
                terminalId: instance.instanceId,
                state: exitCode === 0 ? 'passed' : typeof exitCode === 'number' ? 'failed' : 'unknown',
                exitCode,
                durationMs: Date.now() - startedAt,
                output: fallbackOutput,
                outputTruncated: fallbackTruncated,
                shellIntegration: hasShellIntegration,
            });
        }));
        try {
            await instance.sendText(request.command, true, true);
        }
        catch (error) {
            fail(error);
        }
        return completion;
    }
    rememberInlineDiff(resource, content, languageResource) {
        const key = resource.toString();
        this.inlineDiffModels.set(key, { content, languageResource });
        this.inlineDiffOrder.push(key);
        while (this.inlineDiffOrder.length > MAX_INLINE_DIFF_MODELS) {
            const removed = this.inlineDiffOrder.shift();
            if (removed) {
                this.inlineDiffModels.delete(removed);
            }
        }
    }
    testReceipt(result) {
        const failed = result.counts[TestResultState.Failed] + result.counts[TestResultState.Errored];
        return {
            runId: result.id,
            state: result.completedAt === undefined ? 'running' : failed > 0 ? 'failed' : 'passed',
            passed: result.counts[TestResultState.Passed],
            failed,
            skipped: result.counts[TestResultState.Skipped],
        };
    }
    async withModel(resource, callback) {
        const reference = await this.textModelService.createModelReference(URI.parse(resource));
        try {
            return await callback(reference.object.textEditorModel);
        }
        finally {
            reference.dispose();
        }
    }
    symbol(value) {
        return {
            name: value.name,
            kind: String(value.kind),
            range: range(value.range),
            children: value.children?.map(child => this.symbol(child)),
        };
    }
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
export { CrusorAIWorkbenchService };
