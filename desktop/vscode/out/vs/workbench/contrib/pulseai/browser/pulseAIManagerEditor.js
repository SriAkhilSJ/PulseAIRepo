/*---------------------------------------------------------------------------------------------
 * Full-width Pulse Manager hosted as an editor tab inside PulseAI IDE.
 *--------------------------------------------------------------------------------------------*/
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
var PulseAIManagerEditor_1;
import * as DOM from '../../../../base/browser/dom.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { PULSE_AI_MANAGER_EDITOR_ID } from '../common/pulseAI.js';
import { IPulseAIRendererService } from '../common/pulseAIRendererService.js';
import { installPulseTheme } from './pulseTheme.js';
let PulseAIManagerEditor = class PulseAIManagerEditor extends EditorPane {
    static { PulseAIManagerEditor_1 = this; }
    static { this.ID = PULSE_AI_MANAGER_EDITOR_ID; }
    constructor(group, telemetryService, pulseThemeService, storageService, pulseAIRendererService) {
        super(PulseAIManagerEditor_1.ID, group, telemetryService, pulseThemeService, storageService);
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
};
PulseAIManagerEditor = PulseAIManagerEditor_1 = __decorate([
    __param(1, ITelemetryService),
    __param(2, IThemeService),
    __param(3, IStorageService),
    __param(4, IPulseAIRendererService)
], PulseAIManagerEditor);
export { PulseAIManagerEditor };
