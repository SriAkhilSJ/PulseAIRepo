/*---------------------------------------------------------------------------------------------
 * Stable editor input for the full-width Pulse Manager surface.
 *--------------------------------------------------------------------------------------------*/
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { PULSE_AI_MANAGER_EDITOR_ID } from '../common/pulseAI.js';
export class PulseAIManagerInput extends EditorInput {
    static { this.ID = PULSE_AI_MANAGER_EDITOR_ID; }
    static { this.RESOURCE = URI.from({ scheme: 'pulseai', path: '/manager' }); }
    get typeId() { return PulseAIManagerInput.ID; }
    get editorId() { return PulseAIManagerInput.ID; }
    get resource() { return PulseAIManagerInput.RESOURCE; }
    getName() { return localize('pulseAI.manager.name', 'Pulse Manager'); }
    toUntyped() {
        return {
            resource: PulseAIManagerInput.RESOURCE,
            options: { override: PulseAIManagerInput.ID, pinned: true },
        };
    }
    matches(other) {
        return super.matches(other) || other instanceof PulseAIManagerInput;
    }
}
export class PulseAIManagerInputSerializer {
    canSerialize(_editorInput) { return true; }
    serialize(_editorInput) { return '{}'; }
    deserialize(_instantiationService, _serializedEditorInput) {
        return new PulseAIManagerInput();
    }
}
