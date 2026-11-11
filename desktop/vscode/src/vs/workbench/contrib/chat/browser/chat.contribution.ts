/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

import { registerAction2 } from '../../../../platform/actions/common/actions.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { ExportAgentHostDebugLogsAction } from './actions/exportAgentHostDebugLogsAction.js';
import { ForkConversationAction } from './actions/chatForkActions.js';
import { IChatResponseFileChangesService } from './chatResponseFileChangesService.js';
import { EditorChatResponseFileChangesService } from './editorChatResponseFileChangesService.js';

// The chat context picker (`SessionReferenceContextPickerPick`) injects
// IChatSessionRoutingProviderService. Upstream registers the real singleton
// only from the separate sessions app entry; the regular workbench loads the
// consumer but not the registration, which makes the contribution fail with
// "depends on UNKNOWN service chatSessionRoutingProviderService". Register the
// same real service here so the workbench chat surface initializes correctly
// (provider stays optional and is registered by the sessions adapter only).
import './sessionRouter/chatSessionRoutingProviderService.js';

registerAction2(ForkConversationAction);
registerAction2(ExportAgentHostDebugLogsAction);
registerSingleton(IChatResponseFileChangesService, EditorChatResponseFileChangesService, InstantiationType.Delayed);
