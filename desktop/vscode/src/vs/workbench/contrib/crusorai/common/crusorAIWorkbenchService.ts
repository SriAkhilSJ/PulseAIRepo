/*---------------------------------------------------------------------------------------------
 * Stable adapter between Crusor and Code OSS internal services.
 * The renderer/engine never imports editor internals directly.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { CrusorAICapabilityStatus } from './crusorAIWorkbenchCapabilities.js';

export const ICrusorAIWorkbenchService = createDecorator<ICrusorAIWorkbenchService>('crusorAIWorkbenchService');

export interface CrusorAIRange {
	readonly startLine: number;
	readonly startColumn: number;
	readonly endLine: number;
	readonly endColumn: number;
}

export interface CrusorAIEditorContext {
	readonly resource: string;
	readonly languageId: string;
	readonly versionId: number;
	readonly dirty: boolean;
	readonly selection?: CrusorAIRange;
	readonly selectedText?: string;
	readonly visibleText?: string;
}

export interface CrusorAIDiagnostic {
	readonly resource: string;
	readonly range: CrusorAIRange;
	readonly severity: 'error' | 'warning' | 'info' | 'hint';
	readonly message: string;
	readonly source?: string;
	readonly code?: string;
	readonly related?: readonly { resource: string; range: CrusorAIRange; message: string }[];
}

export interface CrusorAILanguageLocation {
	readonly resource: string;
	readonly range: CrusorAIRange;
	readonly label?: string;
}

export interface CrusorAISymbol {
	readonly name: string;
	readonly kind: string;
	readonly range: CrusorAIRange;
	readonly children?: readonly CrusorAISymbol[];
}

export interface CrusorAISearchMatch {
	readonly resource: string;
	readonly range?: CrusorAIRange;
	readonly preview?: string;
}

export interface CrusorAISCMResource {
	readonly resource: string;
	readonly contextValue?: string;
	readonly tooltip?: string;
	readonly groupId: string;
	readonly groupLabel: string;
}

export interface CrusorAISCMRepository {
	readonly id: string;
	readonly providerId: string;
	readonly label: string;
	readonly root?: string;
	readonly resources: readonly CrusorAISCMResource[];
}

export interface CrusorAITextEdit {
	readonly resource: string;
	readonly range: CrusorAIRange;
	readonly text: string;
	readonly expectedVersionId?: number;
}

export interface CrusorAIWorkspaceEditRequest {
	readonly label: string;
	readonly edits: readonly CrusorAITextEdit[];
	readonly showPreview: boolean;
	readonly approvalToolId: string;
}

export interface CrusorAIApplyResult {
	readonly applied: boolean;
	readonly ariaSummary?: string;
	readonly resources: readonly string[];
}

export interface CrusorAIInlineDiffRequest {
	readonly toolId: string;
	readonly label: string;
	readonly resource?: string;
	readonly original: string;
	readonly modified: string;
}

export interface CrusorAITestItem {
	readonly id: string;
	readonly controllerId: string;
	readonly label: string;
	readonly resource?: string;
	readonly range?: CrusorAIRange;
}

export interface CrusorAITestRequest {
	readonly testIds?: readonly string[];
	readonly resources?: readonly string[];
	readonly excludeIds?: readonly string[];
	readonly approvalToolId: string;
}

export interface CrusorAITestReceipt {
	readonly runId: string;
	readonly state: 'running' | 'passed' | 'failed' | 'cancelled';
	readonly passed: number;
	readonly failed: number;
	readonly skipped: number;
}

export interface CrusorAITaskItem {
	readonly id: string;
	readonly label: string;
	readonly description?: string;
	readonly group?: string;
	readonly background: boolean;
}

export interface CrusorAITaskRequest {
	readonly taskId: string;
	readonly approvalToolId: string;
}

export interface CrusorAITaskReceipt {
	readonly taskId: string;
	readonly state: 'passed' | 'failed' | 'unknown';
	readonly exitCode?: number;
}

export interface CrusorAITerminalRequest {
	readonly command: string;
	readonly cwd?: string;
	readonly name?: string;
	readonly approvalToolId: string;
	readonly timeoutMs?: number;
	readonly maxOutputChars?: number;
	readonly interruptOnTimeout?: boolean;
}

export interface CrusorAITerminalReceipt {
	readonly terminalId: number;
	readonly state: 'passed' | 'failed' | 'unknown' | 'timed_out';
	readonly exitCode?: number;
	readonly durationMs: number;
	readonly output: string;
	readonly outputTruncated: boolean;
	readonly shellIntegration: boolean;
}

export interface ICrusorAIWorkbenchService {
	readonly _serviceBrand: undefined;
	readonly onDidChangeCapabilities: Event<readonly CrusorAICapabilityStatus[]>;
	readonly onDidChangeDiagnostics: Event<readonly CrusorAIDiagnostic[]>;
	readonly onDidChangeTests: Event<CrusorAITestReceipt>;
	readonly onDidResolveDiff: Event<{ toolId: string; approved: boolean }>;

	getCapabilities(): readonly CrusorAICapabilityStatus[];
	isWorkspaceTrusted(): boolean;
	getActiveEditorContext(includeVisibleText?: boolean): Promise<CrusorAIEditorContext | undefined>;
	getDiagnostics(resources?: readonly string[]): readonly CrusorAIDiagnostic[];
	getDocumentSymbols(resource: string): Promise<readonly CrusorAISymbol[]>;
	getDefinitions(resource: string, line: number, column: number): Promise<readonly CrusorAILanguageLocation[]>;
	getReferences(resource: string, line: number, column: number): Promise<readonly CrusorAILanguageLocation[]>;
	searchWorkspace(query: string, maxResults?: number): Promise<readonly CrusorAISearchMatch[]>;
	getSCMState(): readonly CrusorAISCMRepository[];

	openResource(resource: string, range?: CrusorAIRange): Promise<void>;
	openNativeDiff(original: string, modified: string, label: string): Promise<void>;
	openInlineDiff(request: CrusorAIInlineDiffRequest): Promise<void>;
	acceptActiveDiff(): void;
	rejectActiveDiff(): void;
	hasActiveDiff(): boolean;
	applyWorkspaceEdit(request: CrusorAIWorkspaceEditRequest): Promise<CrusorAIApplyResult>;
	discoverTests(resources?: readonly string[]): Promise<readonly CrusorAITestItem[]>;
	runTests(request: CrusorAITestRequest): Promise<CrusorAITestReceipt>;
	discoverTasks(): Promise<readonly CrusorAITaskItem[]>;
	runTask(request: CrusorAITaskRequest): Promise<CrusorAITaskReceipt>;
	runInTerminal(request: CrusorAITerminalRequest): Promise<CrusorAITerminalReceipt>;
	requestWorkspaceTrust(): Promise<boolean>;
}
