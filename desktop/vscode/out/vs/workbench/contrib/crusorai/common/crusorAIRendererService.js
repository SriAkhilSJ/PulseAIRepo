/*---------------------------------------------------------------------------------------------
 * Shared native renderer/model contract used by both the compact Agent view and Crusor Manager.
 *--------------------------------------------------------------------------------------------*/
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export const ICrusorAIRendererService = createDecorator('crusorAIRendererService');
