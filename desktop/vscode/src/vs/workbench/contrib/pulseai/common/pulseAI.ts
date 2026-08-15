/*---------------------------------------------------------------------------------------------
 * PulseAI IDE workbench constants.
 *--------------------------------------------------------------------------------------------*/

export const PULSE_AI_VIEW_CONTAINER_ID = 'workbench.view.pulseai';
export const PULSE_AI_VIEW_ID = 'workbench.view.pulseai.agent';
export const PULSE_AI_MANAGER_EDITOR_ID = 'workbench.editors.pulseai.manager';

export const enum PulseAICommandId {
	Focus = 'pulseai.focus',
	NewSession = 'pulseai.newSession',
	OpenManager = 'pulseai.openManager',
	ReviewChanges = 'pulseai.reviewChanges',
	OpenCheckpoints = 'pulseai.openCheckpoints',
	StopActiveRun = 'pulseai.stopActiveRun',
	OpenSettings = 'pulseai.openSettings',
}
