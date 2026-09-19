/*---------------------------------------------------------------------------------------------
 * CrusorAI IDE workbench constants.
 *--------------------------------------------------------------------------------------------*/
export const CRUSOR_AI_VIEW_CONTAINER_ID = 'workbench.view.crusorai';
export const CRUSOR_AI_VIEW_ID = 'workbench.view.crusorai.agent';
export const CRUSOR_AI_MANAGER_EDITOR_ID = 'workbench.editors.crusorai.manager';
export var CrusorAICommandId;
(function (CrusorAICommandId) {
    CrusorAICommandId["Focus"] = "crusorai.focus";
    CrusorAICommandId["NewSession"] = "crusorai.newSession";
    CrusorAICommandId["OpenManager"] = "crusorai.openManager";
    CrusorAICommandId["ReviewChanges"] = "crusorai.reviewChanges";
    CrusorAICommandId["OpenCheckpoints"] = "crusorai.openCheckpoints";
    CrusorAICommandId["StopActiveRun"] = "crusorai.stopActiveRun";
    CrusorAICommandId["OpenSettings"] = "crusorai.openSettings";
    CrusorAICommandId["AcceptDiff"] = "crusorai.acceptDiff";
    CrusorAICommandId["RejectDiff"] = "crusorai.rejectDiff";
})(CrusorAICommandId || (CrusorAICommandId = {}));
