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

	/**
	 * Begin a turn whose prompt frame is dispatched by someone other than the
	 * composer (today: the Preview window's reviewed batch). Runs the same
	 * turn bookkeeping `submitPrompt` does — archive the live turn, set the
	 * user bubble, flip the running state — WITHOUT sending anything. The
	 * caller owns the frame; the transcript owns the story of it.
	 *
	 * Returns whether the caller should still send its frame: true when a
	 * session is live, false when there was none — the text was parked behind
	 * a `session_create` and the `session_info` handler will start the turn
	 * with it (the caller's frame, session-less, would only be refused).
	 */
	beginExternalTurn(text: string): boolean;
}
