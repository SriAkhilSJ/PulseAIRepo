/*---------------------------------------------------------------------------------------------
 * Shared native renderer/model contract used by both the compact Agent view and Pulse Manager.
 *--------------------------------------------------------------------------------------------*/

import type { IDisposable } from '../../../../base/common/lifecycle.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';

export type PulseAISurface = 'agent' | 'manager';

export const IPulseAIRendererService = createDecorator<IPulseAIRendererService>('pulseAIRendererService');

export interface IPulseAIRendererService {
	readonly _serviceBrand: undefined;
	mount(root: HTMLElement, surface: PulseAISurface): IDisposable;
}
