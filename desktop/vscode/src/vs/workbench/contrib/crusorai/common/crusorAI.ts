/*---------------------------------------------------------------------------------------------
 * CrusorAI IDE workbench constants.
 *--------------------------------------------------------------------------------------------*/

export const CRUSOR_AI_VIEW_CONTAINER_ID = 'workbench.view.crusorai';
export const CRUSOR_AI_VIEW_ID = 'workbench.view.crusorai.agent';
export const CRUSOR_AI_MANAGER_EDITOR_ID = 'workbench.editors.crusorai.manager';

export const enum CrusorAICommandId {
	Focus = 'crusorai.focus',
	NewSession = 'crusorai.newSession',
	OpenManager = 'crusorai.openManager',
	ReviewChanges = 'crusorai.reviewChanges',
	OpenCheckpoints = 'crusorai.openCheckpoints',
	StopActiveRun = 'crusorai.stopActiveRun',
	OpenSettings = 'crusorai.openSettings',
	AcceptDiff = 'crusorai.acceptDiff',
	RejectDiff = 'crusorai.rejectDiff',
	AccountSignIn = 'crusorai.account.signIn',
	AccountManage = 'crusorai.account.manage',
	AccountSignOut = 'crusorai.account.signOut',
}
