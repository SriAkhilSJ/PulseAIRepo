/*---------------------------------------------------------------------------------------------
 * Shared native renderer/model contract used by both the compact Agent view and Pulse Manager.
 *--------------------------------------------------------------------------------------------*/
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export const IPulseAIRendererService = createDecorator('pulseAIRendererService');
