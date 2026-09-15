/*---------------------------------------------------------------------------------------------
 * Stable Pulse capability vocabulary. Code OSS service names stay behind the workbench host.
 *--------------------------------------------------------------------------------------------*/
const cap = (id, phase, risk, provider, requiresTrust = false) => ({ id, phase, risk, provider, requiresTrust });
export const PULSE_AI_WORKBENCH_CAPABILITIES = [
    cap('editor.activeSelection', 'context', 'read', 'editorService'),
    cap('editor.dirtyText', 'context', 'read', 'textFileService'),
    cap('editor.history', 'context', 'read', 'historyService'),
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
    cap('secrets.pulseOwned', 'advanced', 'credential', 'secretStorageService', true),
];
