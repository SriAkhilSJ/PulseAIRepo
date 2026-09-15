/*---------------------------------------------------------------------------------------------
 * Stable Crusor capability vocabulary. Code OSS service names stay behind the workbench host.
 *--------------------------------------------------------------------------------------------*/

export type CrusorAICapabilityPhase = 'context' | 'actuation' | 'advanced';
export type CrusorAICapabilityRisk = 'read' | 'mutate' | 'execute' | 'credential';

export type CrusorAICapabilityId =
	| 'editor.activeSelection'
	| 'editor.dirtyText'
	| 'editor.history'
	| 'language.symbols'
	| 'language.definitions'
	| 'language.references'
	| 'language.codeActions'
	| 'language.rename'
	| 'diagnostics.markers'
	| 'search.workspace'
	| 'scm.state'
	| 'timeline.fileHistory'
	| 'edit.nativeDiff'
	| 'edit.bulkApply'
	| 'edit.undoRedo'
	| 'terminal.native'
	| 'tasks.discover'
	| 'tasks.run'
	| 'tests.discover'
	| 'tests.run'
	| 'tests.results'
	| 'workspace.trust'
	| 'extensions.providers'
	| 'debug.sessions'
	| 'notebook.context'
	| 'mcp.tools'
	| 'editor.tools'
	| 'remote.authority'
	| 'secrets.crusorOwned';

export interface CrusorAICapabilityDescriptor {
	readonly id: CrusorAICapabilityId;
	readonly phase: CrusorAICapabilityPhase;
	readonly risk: CrusorAICapabilityRisk;
	readonly requiresTrust: boolean;
	readonly provider: string;
}

const cap = (
	id: CrusorAICapabilityId,
	phase: CrusorAICapabilityPhase,
	risk: CrusorAICapabilityRisk,
	provider: string,
	requiresTrust = false,
): CrusorAICapabilityDescriptor => ({ id, phase, risk, provider, requiresTrust });

export const CRUSOR_AI_WORKBENCH_CAPABILITIES: readonly CrusorAICapabilityDescriptor[] = [
	cap('editor.activeSelection', 'context', 'read', 'editorService'),
	cap('editor.dirtyText', 'context', 'read', 'textFileService'),
	cap('editor.history', 'context', 'read', 'historyService'),
	cap('language.symbols', 'context', 'read', 'languageFeaturesService'),
	cap('language.definitions', 'context', 'read', 'languageFeaturesService'),
	cap('language.references', 'context', 'read', 'languageFeaturesService'),
	cap('language.codeActions', 'context', 'read', 'languageFeaturesService'),
	cap('language.rename', 'actuation', 'mutate', 'languageFeaturesService', true),
	cap('diagnostics.markers', 'context', 'read', 'markerService'),
	cap('search.workspace', 'context', 'read', 'searchService'),
	cap('scm.state', 'context', 'read', 'scmService'),
	cap('timeline.fileHistory', 'context', 'read', 'timelineService'),
	cap('edit.nativeDiff', 'actuation', 'read', 'editorService'),
	cap('edit.bulkApply', 'actuation', 'mutate', 'bulkEditService', true),
	cap('edit.undoRedo', 'actuation', 'mutate', 'bulkEditService', true),
	cap('terminal.native', 'actuation', 'execute', 'terminalService', true),
	cap('tasks.discover', 'context', 'read', 'taskService'),
	cap('tasks.run', 'actuation', 'execute', 'taskService', true),
	cap('tests.discover', 'context', 'read', 'testService'),
	cap('tests.run', 'actuation', 'execute', 'testService', true),
	cap('tests.results', 'context', 'read', 'testResultService'),
	cap('workspace.trust', 'context', 'read', 'workspaceTrustManagementService'),
	cap('extensions.providers', 'context', 'read', 'extensionService'),
	cap('debug.sessions', 'advanced', 'execute', 'debugService', true),
	cap('notebook.context', 'advanced', 'read', 'notebookEditorService'),
	cap('mcp.tools', 'advanced', 'execute', 'mcpService', true),
	cap('editor.tools', 'advanced', 'execute', 'languageModelToolsService', true),
	cap('remote.authority', 'advanced', 'execute', 'remoteAgentService', true),
	cap('secrets.crusorOwned', 'advanced', 'credential', 'secretStorageService', true),
] as const;

export type CrusorAICapabilityAvailability = 'available' | 'unavailable' | 'degraded' | 'blocked';

export interface CrusorAICapabilityStatus {
	readonly id: CrusorAICapabilityId;
	readonly availability: CrusorAICapabilityAvailability;
	readonly detail?: string;
	readonly providerExtension?: string;
}
