/*---------------------------------------------------------------------------------------------
 * Stable editor input for the full-width Crusor Manager surface.
 *--------------------------------------------------------------------------------------------*/
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { CRUSOR_AI_MANAGER_EDITOR_ID } from '../common/crusorAI.js';
export class CrusorAIManagerInput extends EditorInput {
    static { this.ID = CRUSOR_AI_MANAGER_EDITOR_ID; }
    static { this.RESOURCE = URI.from({ scheme: 'crusorai', path: '/manager' }); }
    get typeId() { return CrusorAIManagerInput.ID; }
    get editorId() { return CrusorAIManagerInput.ID; }
    get resource() { return CrusorAIManagerInput.RESOURCE; }
    getName() { return localize('crusorAI.manager.name', 'Crusor Manager'); }
    toUntyped() {
        return {
            resource: CrusorAIManagerInput.RESOURCE,
            options: { override: CrusorAIManagerInput.ID, pinned: true },
        };
    }
    matches(other) {
        return super.matches(other) || other instanceof CrusorAIManagerInput;
    }
}
export class CrusorAIManagerInputSerializer {
    canSerialize(_editorInput) { return true; }
    serialize(_editorInput) { return '{}'; }
    deserialize(_instantiationService, _serializedEditorInput) {
        return new CrusorAIManagerInput();
    }
}
