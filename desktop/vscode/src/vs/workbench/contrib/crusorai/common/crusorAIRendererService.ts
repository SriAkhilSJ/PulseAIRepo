/*---------------------------------------------------------------------------------------------
 * Shared native renderer/model contract used by both the compact Agent view and Crusor Manager.
 *--------------------------------------------------------------------------------------------*/

import type { IDisposable } from '../../../../base/common/lifecycle.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';

export type CrusorAISurface = 'agent' | 'manager';

export const ICrusorAIRendererService = createDecorator<ICrusorAIRendererService>('crusorAIRendererService');

export interface ICrusorAIRendererService {
	readonly _serviceBrand: undefined;
	mount(root: unknown /* HTMLElement */, surface: CrusorAISurface): IDisposable;
}
