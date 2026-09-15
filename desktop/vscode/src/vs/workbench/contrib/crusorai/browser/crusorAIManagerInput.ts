/*---------------------------------------------------------------------------------------------
 * Stable editor input for the full-width Crusor Manager surface.
 *--------------------------------------------------------------------------------------------*/

import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IUntypedEditorInput, IEditorSerializer } from '../../../common/editor.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { CRUSOR_AI_MANAGER_EDITOR_ID } from '../common/crusorAI.js';

export class CrusorAIManagerInput extends EditorInput {
	static readonly ID = CRUSOR_AI_MANAGER_EDITOR_ID;
	static readonly RESOURCE = URI.from({ scheme: 'crusorai', path: '/manager' });

	override get typeId(): string { return CrusorAIManagerInput.ID; }
	override get editorId(): string { return CrusorAIManagerInput.ID; }
	override get resource(): URI { return CrusorAIManagerInput.RESOURCE; }
	override getName(): string { return localize('crusorAI.manager.name', 'Crusor Manager'); }

	override toUntyped(): IUntypedEditorInput {
		return {
			resource: CrusorAIManagerInput.RESOURCE,
			options: { override: CrusorAIManagerInput.ID, pinned: true },
		};
	}

	override matches(other: EditorInput | IUntypedEditorInput): boolean {
		return super.matches(other) || other instanceof CrusorAIManagerInput;
	}
}

export class CrusorAIManagerInputSerializer implements IEditorSerializer {
	canSerialize(_editorInput: CrusorAIManagerInput): boolean { return true; }
	serialize(_editorInput: CrusorAIManagerInput): string { return '{}'; }
	deserialize(_instantiationService: IInstantiationService, _serializedEditorInput: string): CrusorAIManagerInput {
		return new CrusorAIManagerInput();
	}
}
