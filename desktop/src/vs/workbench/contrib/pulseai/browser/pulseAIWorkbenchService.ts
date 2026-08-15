/*---------------------------------------------------------------------------------------------
 * Phase-A Code OSS sensor adapter. All internal service imports terminate here.
 *--------------------------------------------------------------------------------------------*/

import { isCodeEditor, isDiffEditor } from '../../../../editor/browser/editorBrowser.js';
import { IBulkEditService, ResourceTextEdit } from '../../../../editor/browser/services/bulkEditService.js';
import { Position } from '../../../../editor/common/core/position.js';
import { IRange } from '../../../../editor/common/core/range.js';
import { ILanguageFeaturesService } from '../../../../editor/common/services/languageFeatures.js';
import { ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { Disposable, DisposableStore } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandDetectionCapability, ITerminalCommand, TerminalCapability } from '../../../../platform/terminal/common/capabilities/capabilities.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IMarker, IMarkerService, MarkerSeverity } from '../../../../platform/markers/common/markers.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IWorkspaceTrustManagementService, IWorkspaceTrustRequestService } from '../../../../platform/workspace/common/workspaceTrust.js';
import { ISCMService } from '../../scm/common/scm.js';
import { ITestResult } from '../../testing/common/testResult.js';
import { ITestResultService } from '../../testing/common/testResultService.js';
import { ITestService } from '../../testing/common/testService.js';
import { InternalTestItem, TestResultState, TestRunProfileBitset } from '../../testing/common/testTypes.js';
import { ITaskService } from '../../tasks/common/taskService.js';
import { TaskRunSource } from '../../tasks/common/tasks.js';
import { ITerminalService } from '../../terminal/browser/terminal.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { QueryBuilder } from '../../../services/search/common/queryBuilder.js';
import { ISearchService, isFileMatch, resultIsMatch } from '../../../services/search/common/search.js';
import { ITextFileService } from '../../../services/textfile/common/textfiles.js';
import {
	PULSE_AI_WORKBENCH_CAPABILITIES,
	PulseAICapabilityStatus,
} from '../common/pulseAIWorkbenchCapabilities.js';
import {
	IPulseAIWorkbenchService,
	PulseAIApplyResult,
	PulseAIDiagnostic,
	PulseAIEditorContext,
	PulseAILanguageLocation,
	PulseAIRange,
	PulseAISCMRepository,
	PulseAISearchMatch,
	PulseAISymbol,
	PulseAITaskItem,
	PulseAITaskReceipt,
	PulseAITaskRequest,
	PulseAITerminalReceipt,
	PulseAITerminalRequest,
	PulseAITestItem,
	PulseAITestReceipt,
	PulseAITestRequest,
	PulseAIWorkspaceEditRequest,
} from '../common/pulseAIWorkbenchService.js';

const WIRED_CAPABILITIES = new Set([
	'editor.activeSelection', 'editor.dirtyText', 'language.symbols',
	'language.definitions', 'language.references', 'diagnostics.markers',
	'search.workspace', 'scm.state',
	'edit.nativeDiff', 'edit.bulkApply', 'edit.undoRedo', 'terminal.native',
	'tasks.discover', 'tasks.run', 'tests.discover', 'tests.run', 'tests.results', 'workspace.trust',
]);

const DEFAULT_TERMINAL_TIMEOUT_MS = 120_000;
const MIN_TERMINAL_TIMEOUT_MS = 1_000;
const MAX_TERMINAL_TIMEOUT_MS = 10 * 60_000;
const DEFAULT_TERMINAL_OUTPUT_CHARS = 64_000;
const MAX_TERMINAL_OUTPUT_CHARS = 256_000;

function range(value: IRange): PulseAIRange {
	return {
		startLine: value.startLineNumber,
		startColumn: value.startColumn,
		endLine: value.endLineNumber,
		endColumn: value.endColumn,
	};
}

function severity(value: MarkerSeverity): PulseAIDiagnostic['severity'] {
	if (value === MarkerSeverity.Error) { return 'error'; }
	if (value === MarkerSeverity.Warning) { return 'warning'; }
	if (value === MarkerSeverity.Info) { return 'info'; }
	return 'hint';
}

function markerCode(marker: IMarker): string | undefined {
	if (typeof marker.code === 'string') { return marker.code; }
	if (typeof marker.code === 'number') { return String(marker.code); }
	return marker.code?.value;
}

function diagnostic(marker: IMarker): PulseAIDiagnostic {
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

export class PulseAIWorkbenchService extends Disposable implements IPulseAIWorkbenchService {
	declare readonly _serviceBrand: undefined;

	private readonly _onDidChangeCapabilities = this._register(new Emitter<readonly PulseAICapabilityStatus[]>());
	readonly onDidChangeCapabilities = this._onDidChangeCapabilities.event;
	private readonly _onDidChangeDiagnostics = this._register(new Emitter<readonly PulseAIDiagnostic[]>());
	readonly onDidChangeDiagnostics = this._onDidChangeDiagnostics.event;
	private readonly _onDidChangeTests = this._register(new Emitter<PulseAITestReceipt>());
	readonly onDidChangeTests: Event<PulseAITestReceipt> = this._onDidChangeTests.event;
	private readonly queryBuilder: QueryBuilder;

	constructor(
		@IEditorService private readonly editorService: IEditorService,
		@ITextFileService private readonly textFileService: ITextFileService,
		@IMarkerService private readonly markerService: IMarkerService,
		@ILanguageFeaturesService private readonly languageFeaturesService: ILanguageFeaturesService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IInstantiationService instantiationService: IInstantiationService,
		@IWorkspaceContextService private readonly workspaceContextService: IWorkspaceContextService,
		@ISearchService private readonly searchService: ISearchService,
		@ISCMService private readonly scmService: ISCMService,
		@ITestService private readonly testService: ITestService,
		@ITestResultService private readonly testResultService: ITestResultService,
		@ITaskService private readonly taskService: ITaskService,
		@ITerminalService private readonly terminalService: ITerminalService,
		@IBulkEditService private readonly bulkEditService: IBulkEditService,
		@IWorkspaceTrustManagementService private readonly trustManagementService: IWorkspaceTrustManagementService,
		@IWorkspaceTrustRequestService private readonly trustRequestService: IWorkspaceTrustRequestService,
	) {
		super();
		this.queryBuilder = instantiationService.createInstance(QueryBuilder);
		this._register(this.markerService.onMarkerChanged(resources => {
			this._onDidChangeDiagnostics.fire(this.getDiagnostics(resources.map(resource => resource.toString())));
		}));
		this._register(this.trustManagementService.onDidChangeTrust(() => {
			this._onDidChangeCapabilities.fire(this.getCapabilities());
		}));
		this._register(this.testResultService.onResultsChanged(() => {
			const latest = this.testResultService.results[0];
			if (latest) { this._onDidChangeTests.fire(this.testReceipt(latest)); }
		}));
	}

	getCapabilities(): readonly PulseAICapabilityStatus[] {
		const trusted = this.trustManagementService.isWorkspaceTrusted();
		return PULSE_AI_WORKBENCH_CAPABILITIES.map(descriptor => ({
			id: descriptor.id,
			availability: descriptor.requiresTrust && !trusted
				? 'blocked'
				: WIRED_CAPABILITIES.has(descriptor.id) ? 'available' : 'degraded',
			detail: WIRED_CAPABILITIES.has(descriptor.id)
				? undefined
				: 'Adapter scheduled for a later host milestone',
		}));
	}

	async getActiveEditorContext(includeVisibleText = false): Promise<PulseAIEditorContext | undefined> {
		const control = this.editorService.activeTextEditorControl;
		const editor = isCodeEditor(control)
			? control
			: isDiffEditor(control) ? control.getModifiedEditor() : undefined;
		const model = editor?.getModel();
		if (!editor || !model) { return undefined; }

		const selection = editor.getSelection();
		const selectedText = selection && !selection.isEmpty()
			? model.getValueInRange(selection).slice(0, 20_000)
			: undefined;
		const visibleText = includeVisibleText
			? editor.getVisibleRanges().map(item => model.getValueInRange(item)).join('\n…\n').slice(0, 32_000)
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

	getDiagnostics(resources?: readonly string[]): readonly PulseAIDiagnostic[] {
		if (!resources || resources.length === 0) {
			return this.markerService.read({ take: 500 }).map(diagnostic);
		}
		return resources.flatMap(value =>
			this.markerService.read({ resource: URI.parse(value), take: 200 }).map(diagnostic)
		);
	}

	async getDocumentSymbols(resource: string): Promise<readonly PulseAISymbol[]> {
		return this.withModel(resource, async model => {
			const result: PulseAISymbol[] = [];
			for (const provider of this.languageFeaturesService.documentSymbolProvider.ordered(model)) {
				try {
					const symbols = await Promise.resolve(provider.provideDocumentSymbols(model, CancellationToken.None));
					for (const symbol of symbols ?? []) {
						result.push(this.symbol(symbol));
					}
				} catch { /* one extension provider must not break all semantic context */ }
			}
			return result;
		});
	}

	async getDefinitions(resource: string, line: number, column: number): Promise<readonly PulseAILanguageLocation[]> {
		return this.withModel(resource, async model => {
			const result: PulseAILanguageLocation[] = [];
			const position = new Position(line, column);
			for (const provider of this.languageFeaturesService.definitionProvider.ordered(model)) {
				try {
					const value = await Promise.resolve(provider.provideDefinition(model, position, CancellationToken.None));
					const items = Array.isArray(value) ? value : value ? [value] : [];
					for (const item of items) {
						const linked = 'targetUri' in item;
						result.push({
							resource: (linked ? item.targetUri : item.uri).toString(),
							range: range(linked ? item.targetSelectionRange : item.range),
						});
					}
				} catch { /* provider isolation */ }
			}
			return result;
		});
	}

	async getReferences(resource: string, line: number, column: number): Promise<readonly PulseAILanguageLocation[]> {
		return this.withModel(resource, async model => {
			const result: PulseAILanguageLocation[] = [];
			const position = new Position(line, column);
			for (const provider of this.languageFeaturesService.referenceProvider.ordered(model)) {
				try {
					const items = await Promise.resolve(provider.provideReferences(model, position, { includeDeclaration: true }, CancellationToken.None));
					for (const item of items ?? []) {
						result.push({ resource: item.uri.toString(), range: range(item.range) });
					}
				} catch { /* provider isolation */ }
			}
			return result;
		});
	}

	async openResource(resource: string, selection?: PulseAIRange): Promise<void> {
		await this.editorService.openEditor({
			resource: URI.parse(resource),
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

	async openNativeDiff(original: string, modified: string, label: string): Promise<void> {
		await this.editorService.openEditor({
			original: { resource: URI.parse(original) },
			modified: { resource: URI.parse(modified) },
			label,
		});
	}

	async requestWorkspaceTrust(): Promise<boolean> {
		if (this.trustManagementService.isWorkspaceTrusted()) { return true; }
		return (await this.trustRequestService.requestWorkspaceTrust({
			message: 'Pulse needs workspace trust before it can modify files or run commands.',
		})) === true;
	}

	async searchWorkspace(pattern: string, maxResults = 100): Promise<readonly PulseAISearchMatch[]> {
		const folders = this.workspaceContextService.getWorkspace().folders.map(folder => folder.uri);
		const query = this.queryBuilder.text(
			{ pattern, isRegExp: false, isCaseSensitive: false, isWordMatch: false },
			folders.length > 0 ? folders : undefined,
			{
				_reason: 'pulseAI',
				maxResults,
				previewOptions: { matchLines: 1, charsPerLine: 180 },
				surroundingContext: 0,
			},
		);
		const matches: PulseAISearchMatch[] = [];
		const seen = new Set<string>();
		const consume = (file: { resource: URI; results?: readonly import('../../../services/search/common/search.js').ITextSearchResult[] }) => {
			for (const item of file.results ?? []) {
				if (!resultIsMatch(item)) { continue; }
				const location = item.rangeLocations[0]?.source;
				const resource = (item.uri ?? file.resource).toString();
				const key = `${resource}:${location?.startLineNumber}:${location?.startColumn}`;
				if (seen.has(key) || matches.length >= maxResults) { continue; }
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
			if (isFileMatch(item)) { consume({ resource: URI.revive(item.resource), results: item.results }); }
		});
		for (const file of complete.results) {
			consume({ resource: URI.revive(file.resource), results: file.results });
		}
		return matches;
	}

	getSCMState(): readonly PulseAISCMRepository[] {
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

	async applyWorkspaceEdit(request: PulseAIWorkspaceEditRequest): Promise<PulseAIApplyResult> {
		if (!this.trustManagementService.isWorkspaceTrusted()) {
			throw new Error('Pulse cannot apply workspace edits before workspace trust is granted');
		}
		if (!request.approvalToolId.trim()) {
			throw new Error('Pulse workspace edit is missing its approval tool id');
		}
		const resources = [...new Set(request.edits.map(edit => edit.resource))];
		const edits = request.edits.map(edit => new ResourceTextEdit(
			URI.parse(edit.resource),
			{
				range: {
					startLineNumber: edit.range.startLine,
					startColumn: edit.range.startColumn,
					endLineNumber: edit.range.endLine,
					endColumn: edit.range.endColumn,
				},
				text: edit.text,
			},
			edit.expectedVersionId,
		));
		const result = await this.bulkEditService.apply(edits, {
			label: request.label,
			code: 'pulseai',
			showPreview: request.showPreview,
			confirmBeforeUndo: true,
		});
		return { applied: result.isApplied, ariaSummary: result.ariaSummary, resources };
	}
	async discoverTests(resources?: readonly string[]): Promise<readonly PulseAITestItem[]> {
		await this.testService.syncTests();
		const resourceSet = resources ? new Set(resources) : undefined;
		const result: PulseAITestItem[] = [];
		for (const test of this.testService.collection.all) {
			const item = test.item;
			const resource = item.uri?.toString();
			if (resourceSet && (!resource || !resourceSet.has(resource))) { continue; }
			result.push({
				id: item.extId,
				controllerId: test.controllerId,
				label: item.label,
				resource,
				range: item.range ? range(item.range) : undefined,
			});
			if (result.length >= 1_000) { break; }
		}
		return result;
	}

	async runTests(request: PulseAITestRequest): Promise<PulseAITestReceipt> {
		if (!this.trustManagementService.isWorkspaceTrusted()) {
			throw new Error('Pulse cannot run tests before workspace trust is granted');
		}
		if (!request.approvalToolId.trim()) {
			throw new Error('Pulse test request is missing its approval tool id');
		}
		await this.testService.syncTests();
		const selected = new Map<string, InternalTestItem>();
		for (const id of request.testIds ?? []) {
			const item = this.testService.collection.getNodeById(id);
			if (item) { selected.set(item.item.extId, item); }
		}
		for (const value of request.resources ?? []) {
			for (const item of this.testService.collection.getNodeByUrl(URI.parse(value))) {
				selected.set(item.item.extId, item);
			}
		}
		if (selected.size === 0) {
			throw new Error('Pulse test request did not resolve to any registered tests');
		}
		const exclude: InternalTestItem[] = [];
		for (const id of request.excludeIds ?? []) {
			const item = this.testService.collection.getNodeById(id);
			if (item) { exclude.push(item); }
		}
		const result = await this.testService.runTests({
			group: TestRunProfileBitset.Run,
			tests: [...selected.values()],
			exclude,
			preserveFocus: true,
		}, CancellationToken.None);
		return this.testReceipt(result);
	}

	async discoverTasks(): Promise<readonly PulseAITaskItem[]> {
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

	async runTask(request: PulseAITaskRequest): Promise<PulseAITaskReceipt> {
		if (!this.trustManagementService.isWorkspaceTrusted()) {
			throw new Error('Pulse cannot run tasks before workspace trust is granted');
		}
		if (!request.approvalToolId.trim()) {
			throw new Error('Pulse task request is missing its approval tool id');
		}
		const tasks = await this.taskService.getKnownTasks();
		const task = tasks.find(candidate =>
			candidate.getMapKey() === request.taskId ||
			candidate._id === request.taskId ||
			candidate.configurationProperties.identifier === request.taskId
		);
		if (!task) { throw new Error(`Pulse could not resolve task: ${request.taskId}`); }
		const summary = await this.taskService.run(task, undefined, TaskRunSource.ChatAgent);
		return {
			taskId: request.taskId,
			state: summary?.exitCode === 0 ? 'passed' : typeof summary?.exitCode === 'number' ? 'failed' : 'unknown',
			exitCode: summary?.exitCode,
		};
	}

	async runInTerminal(request: PulseAITerminalRequest): Promise<PulseAITerminalReceipt> {
		if (!this.trustManagementService.isWorkspaceTrusted()) {
			throw new Error('Pulse cannot run terminal commands before workspace trust is granted');
		}
		if (!request.approvalToolId.trim()) {
			throw new Error('Pulse terminal request is missing its approval tool id');
		}
		const commandText = request.command.trim();
		if (!commandText) {
			throw new Error('Pulse terminal request has an empty command');
		}
		const timeoutMs = Math.min(MAX_TERMINAL_TIMEOUT_MS, Math.max(MIN_TERMINAL_TIMEOUT_MS, request.timeoutMs ?? DEFAULT_TERMINAL_TIMEOUT_MS));
		const maxOutputChars = Math.min(MAX_TERMINAL_OUTPUT_CHARS, Math.max(1_000, request.maxOutputChars ?? DEFAULT_TERMINAL_OUTPUT_CHARS));
		const instance = await this.terminalService.createAndFocusTerminal({
			config: { name: request.name ?? 'Pulse Agent' },
			cwd: request.cwd,
		});
		const startedAt = Date.now();
		const listeners = new DisposableStore();
		const attached = new Set<ICommandDetectionCapability>();
		let fallbackOutput = '';
		let fallbackTruncated = false;
		let hasShellIntegration = false;
		let finish!: (receipt: PulseAITerminalReceipt) => void;
		let fail!: (error: unknown) => void;

		const boundOutput = (value: string): { output: string; truncated: boolean } => {
			if (value.length <= maxOutputChars) { return { output: value, truncated: false }; }
			return { output: value.slice(-maxOutputChars), truncated: true };
		};
		const completion = new Promise<PulseAITerminalReceipt>((resolve, reject) => {
			let done = false;
			const complete = (receipt: PulseAITerminalReceipt) => {
				if (done) { return; }
				done = true;
				clearTimeout(timer);
				listeners.dispose();
				resolve(receipt);
			};
			finish = complete;
			fail = error => {
				if (done) { return; }
				done = true;
				clearTimeout(timer);
				listeners.dispose();
				reject(error);
			};
			const timer = setTimeout(() => {
				if (request.interruptOnTimeout) { void instance.sendSignal('SIGINT'); }
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

		const finishCommand = (command: ITerminalCommand) => {
			if (command.command.trim() !== commandText) { return; }
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
		const attachCommandDetection = (capability: ICommandDetectionCapability) => {
			if (attached.has(capability)) { return; }
			attached.add(capability);
			hasShellIntegration = true;
			listeners.add(capability.onCommandFinished(finishCommand));
		};
		const existing = instance.capabilities.get(TerminalCapability.CommandDetection);
		if (existing) { attachCommandDetection(existing); }
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
		} catch (error) {
			fail(error);
		}
		return completion;
	}

	private testReceipt(result: ITestResult): PulseAITestReceipt {
		const failed = result.counts[TestResultState.Failed] + result.counts[TestResultState.Errored];
		return {
			runId: result.id,
			state: result.completedAt === undefined ? 'running' : failed > 0 ? 'failed' : 'passed',
			passed: result.counts[TestResultState.Passed],
			failed,
			skipped: result.counts[TestResultState.Skipped],
		};
	}

	private async withModel<T>(resource: string, callback: (model: import('../../../../editor/common/model.js').ITextModel) => Promise<T>): Promise<T> {
		const reference = await this.textModelService.createModelReference(URI.parse(resource));
		try {
			return await callback(reference.object.textEditorModel);
		} finally {
			reference.dispose();
		}
	}


	private symbol(value: import('../../../../editor/common/languages.js').DocumentSymbol): PulseAISymbol {
		return {
			name: value.name,
			kind: String(value.kind),
			range: range(value.range),
			children: value.children?.map(child => this.symbol(child)),
		};
	}
}
