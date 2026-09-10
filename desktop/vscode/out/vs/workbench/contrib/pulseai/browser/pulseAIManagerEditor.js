/*---------------------------------------------------------------------------------------------
 * Full-width Pulse Manager hosted as an editor tab inside PulseAI IDE.
 *--------------------------------------------------------------------------------------------*/
import * as DOM from '../../../../base/browser/dom.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { PULSE_AI_MANAGER_EDITOR_ID } from '../common/pulseAI.js';
import { IPulseAIRendererService } from '../common/pulseAIRendererService.js';
import { installPulseTheme } from './pulseTheme.js';
export class PulseAIManagerEditor extends EditorPane {
    static { this.ID = PULSE_AI_MANAGER_EDITOR_ID; }
    constructor(group, telemetryService, pulseThemeService, storageService, pulseAIRendererService) {
        super(PulseAIManagerEditor.ID, group, telemetryService, pulseThemeService, storageService);
        this.pulseThemeService = pulseThemeService;
        this.pulseAIRendererService = pulseAIRendererService;
    }
    createEditor(parent) {
        this.root = DOM.append(parent, DOM.$('.pulseai-manager-editor.pulseai-render-root'));
        // Same derived palette as the pane: seeds from the live theme, never
        // hardcoded (hermes seed→token machine).
        this._register(installPulseTheme(this.root, this.pulseThemeService));
        this.root.dataset.surface = 'manager';
        this.root.setAttribute('role', 'region');
        this.root.setAttribute('aria-label', 'Pulse Manager');
        this._register(this.pulseAIRendererService.mount(this.root, 'manager'));
    }
    layout(size) {
        if (!this.root) {
            return;
        }
        this.root.style.width = `${size.width}px`;
        this.root.style.height = `${size.height}px`;
    }
}
