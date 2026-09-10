/*---------------------------------------------------------------------------------------------
 * PulseAI IDE workbench constants.
 *--------------------------------------------------------------------------------------------*/
export const PULSE_AI_VIEW_CONTAINER_ID = 'workbench.view.pulseai';
export const PULSE_AI_VIEW_ID = 'workbench.view.pulseai.agent';
export const PULSE_AI_MANAGER_EDITOR_ID = 'workbench.editors.pulseai.manager';
export var PulseAICommandId;
(function (PulseAICommandId) {
    PulseAICommandId["Focus"] = "pulseai.focus";
    PulseAICommandId["NewSession"] = "pulseai.newSession";
    PulseAICommandId["OpenManager"] = "pulseai.openManager";
    PulseAICommandId["ReviewChanges"] = "pulseai.reviewChanges";
    PulseAICommandId["OpenCheckpoints"] = "pulseai.openCheckpoints";
    PulseAICommandId["StopActiveRun"] = "pulseai.stopActiveRun";
    PulseAICommandId["OpenSettings"] = "pulseai.openSettings";
})(PulseAICommandId || (PulseAICommandId = {}));
