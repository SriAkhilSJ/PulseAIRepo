/*---------------------------------------------------------------------------------------------
 * Stable adapter between Pulse and Code OSS internal services.
 * The renderer/engine never imports editor internals directly.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { PulseAICapabilityStatus } from './pulseAIWorkbenchCapabilities.js';

export const IPulseAIWorkbenchService = createDecorator<IPulseAIWorkbenchService>('pulseAIWorkbenchService');

export interface PulseAIRange {
	readonly startLine: number;
	readonly startColumn: number;
	readonly endLine: number;
	readonly endColumn: number;
}

export interface PulseAIEditorContext {
	readonly resource: string;
	readonly languageId: string;
	readonly versionId: number;
	readonly dirty: boolean;
	readonly selection?: PulseAIRange;
	readonly selectedText?: string;
	readonly visibleText?: string;
}

export interface PulseAIDiagnostic {
	readonly resource: string;
	readonly range: PulseAIRange;
	readonly severity: 'error' | 'warning' | 'info' | 'hint';
	readonly message: string;
	readonly source?: string;
	readonly code?: string;
	readonly related?: readonly { resource: string; range: PulseAIRange; message: string }[];
}

export interface PulseAILanguageLocation {
	readonly resource: string;
	readonly range: PulseAIRange;
	readonly label?: string;
}

export interface PulseAISymbol {
	readonly name: string;
	readonly kind: string;
	readonly range: PulseAIRange;
	readonly children?: readonly PulseAISymbol[];
}

export interface PulseAISearchMatch {
	readonly resource: string;
	readonly range?: PulseAIRange;
	readonly preview?: string;
}

export interface PulseAISCMResource {
	readonly resource: string;
	readonly contextValue?: string;
	readonly tooltip?: string;
	readonly groupId: string;
	readonly groupLabel: string;
}

export interface PulseAISCMRepository {
	readonly id: string;
	readonly providerId: string;
	readonly label: string;
	readonly root?: string;
	readonly resources: readonly PulseAISCMResource[];
}

export interface PulseAITextEdit {
	readonly resource: string;
	readonly range: PulseAIRange;
	readonly text: string;
	readonly expectedVersionId?: number;
}

export interface PulseAIWorkspaceEditRequest {
	readonly label: string;
	readonly edits: readonly PulseAITextEdit[];
	readonly showPreview: boolean;
	readonly approvalToolId: string;
}

export interface PulseAIApplyResult {
	readonly applied: boolean;
	readonly ariaSummary?: string;
	readonly resources: readonly string[];
}

export interface PulseAIInlineDiffRequest {
	readonly toolId: string;
	readonly label: string;
	readonly resource?: string;
	readonly original: string;
	readonly modified: string;
}

export interface PulseAITestItem {
	readonly id: string;
	readonly controllerId: string;
	readonly label: string;
	readonly resource?: string;
	readonly range?: PulseAIRange;
}

export interface PulseAITestRequest {
	readonly testIds?: readonly string[];
	readonly resources?: readonly string[];
	readonly excludeIds?: readonly string[];
	readonly approvalToolId: string;
}

export interface PulseAITestReceipt {
	readonly runId: string;
	readonly state: 'running' | 'passed' | 'failed' | 'cancelled';
	readonly passed: number;
	readonly failed: number;
	readonly skipped: number;
}

export interface PulseAITaskItem {
	readonly id: string;
	readonly label: string;
	readonly description?: string;
	readonly group?: string;
	readonly background: boolean;
}

export interface PulseAITaskRequest {
	readonly taskId: string;
	readonly approvalToolId: string;
}

export interface PulseAITaskReceipt {
	readonly taskId: string;
	readonly state: 'passed' | 'failed' | 'unknown';
	readonly exitCode?: number;
}

export interface PulseAITerminalRequest {
	readonly command: string;
	readonly cwd?: string;
	readonly name?: string;
	readonly approvalToolId: string;
	readonly timeoutMs?: number;
	readonly maxOutputChars?: number;
	readonly interruptOnTimeout?: boolean;
}

export interface PulseAITerminalReceipt {
	readonly terminalId: number;
	readonly state: 'passed' | 'failed' | 'unknown' | 'timed_out';
	readonly exitCode?: number;
	readonly durationMs: number;
	readonly output: string;
	readonly outputTruncated: boolean;
	readonly shellIntegration: boolean;
}

export interface IPulseAIWorkbenchService {
	readonly _serviceBrand: undefined;
	readonly onDidChangeCapabilities: Event<readonly PulseAICapabilityStatus[]>;
	readonly onDidChangeDiagnostics: Event<readonly PulseAIDiagnostic[]>;
	readonly onDidChangeTests: Event<PulseAITestReceipt>;

	getCapabilities(): readonly PulseAICapabilityStatus[];
	isWorkspaceTrusted(): boolean;
	getActiveEditorContext(includeVisibleText?: boolean): Promise<PulseAIEditorContext | undefined>;
	getDiagnostics(resources?: readonly string[]): readonly PulseAIDiagnostic[];
	getDocumentSymbols(resource: string): Promise<readonly PulseAISymbol[]>;
	getDefinitions(resource: string, line: number, column: number): Promise<readonly PulseAILanguageLocation[]>;
	getReferences(resource: string, line: number, column: number): Promise<readonly PulseAILanguageLocation[]>;
	searchWorkspace(query: string, maxResults?: number): Promise<readonly PulseAISearchMatch[]>;
	getSCMState(): readonly PulseAISCMRepository[];

	openResource(resource: string, range?: PulseAIRange): Promise<void>;
	openNativeDiff(original: string, modified: string, label: string): Promise<void>;
	openInlineDiff(request: PulseAIInlineDiffRequest): Promise<void>;
	applyWorkspaceEdit(request: PulseAIWorkspaceEditRequest): Promise<PulseAIApplyResult>;
	discoverTests(resources?: readonly string[]): Promise<readonly PulseAITestItem[]>;
	runTests(request: PulseAITestRequest): Promise<PulseAITestReceipt>;
	discoverTasks(): Promise<readonly PulseAITaskItem[]>;
	runTask(request: PulseAITaskRequest): Promise<PulseAITaskReceipt>;
	runInTerminal(request: PulseAITerminalRequest): Promise<PulseAITerminalReceipt>;
	requestWorkspaceTrust(): Promise<boolean>;
}
