/*---------------------------------------------------------------------------------------------
 * Stable editor input for the full-width Pulse Manager surface.
 *--------------------------------------------------------------------------------------------*/

import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IUntypedEditorInput, IEditorSerializer } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { PULSE_AI_MANAGER_EDITOR_ID } from '../common/pulseAI.js';

export class PulseAIManagerInput extends EditorInput {
	static readonly ID = PULSE_AI_MANAGER_EDITOR_ID;
	static readonly RESOURCE = URI.from({ scheme: 'pulseai', path: '/manager' });

	override get typeId(): string { return PulseAIManagerInput.ID; }
	override get editorId(): string { return PulseAIManagerInput.ID; }
	override get resource(): URI { return PulseAIManagerInput.RESOURCE; }
	override getName(): string { return localize('pulseAI.manager.name', 'Pulse Manager'); }

	override toUntyped(): IUntypedEditorInput {
		return {
			resource: PulseAIManagerInput.RESOURCE,
			options: { override: PulseAIManagerInput.ID, pinned: true },
		};
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof PulseAIManagerInput;
	}
}

export class PulseAIManagerInputSerializer implements IEditorSerializer {
	canSerialize(_editorInput: PulseAIManagerInput): boolean { return true; }
	serialize(_editorInput: PulseAIManagerInput): string { return '{}'; }
	deserialize(_instantiationService: IInstantiationService, _serializedEditorInput: string): PulseAIManagerInput {
		return new PulseAIManagerInput();
	}
}
