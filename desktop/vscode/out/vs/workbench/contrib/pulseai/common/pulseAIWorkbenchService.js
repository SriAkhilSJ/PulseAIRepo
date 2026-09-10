/*---------------------------------------------------------------------------------------------
 * Stable adapter between Pulse and Code OSS internal services.
 * The renderer/engine never imports editor internals directly.
 *--------------------------------------------------------------------------------------------*/
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export const IPulseAIWorkbenchService = createDecorator('pulseAIWorkbenchService');
