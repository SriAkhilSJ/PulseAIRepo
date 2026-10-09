/*---------------------------------------------------------------------------------------------
 * Full-width Crusor Manager hosted as an editor tab inside CrusorAI IDE.
 *--------------------------------------------------------------------------------------------*/
var __extends = (this && this.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import * as DOM from '../../../../base/browser/dom.js';
import { IStorageService } from '../../../../platform/storage/common/storage.js';
import { ITelemetryService } from '../../../../platform/telemetry/common/telemetry.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { EditorPane } from '../../../browser/parts/editor/editorPane.js';
import { CRUSOR_AI_MANAGER_EDITOR_ID } from '../common/crusorAI.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { installCrusorTheme } from './crusorTheme.js';
var CrusorAIManagerEditor = /** @class */ (function (_super) {
    __extends(CrusorAIManagerEditor, _super);
    function CrusorAIManagerEditor(group, telemetryService, crusorThemeService, storageService, crusorAIRendererService) {
        var _this = _super.call(this, CrusorAIManagerEditor_1.ID, group, telemetryService, crusorThemeService, storageService) || this;
        _this.crusorThemeService = crusorThemeService;
        _this.crusorAIRendererService = crusorAIRendererService;
        return _this;
    }
    CrusorAIManagerEditor_1 = CrusorAIManagerEditor;
    CrusorAIManagerEditor.prototype.createEditor = function (parent) {
        this.root = DOM.append(parent, DOM.$('.crusorai-manager-editor.crusorai-render-root'));
        // Same derived palette as the pane: seeds from the live theme, never
        // hardcoded (hermes seed→token machine).
        this._register(installCrusorTheme(this.root, this.crusorThemeService));
        this.root.dataset.surface = 'manager';
        this.root.setAttribute('role', 'region');
        this.root.setAttribute('aria-label', 'Crusor Manager');
        this._register(this.crusorAIRendererService.mount(this.root, 'manager'));
    };
    CrusorAIManagerEditor.prototype.layout = function (size) {
        if (!this.root) {
            return;
        }
        this.root.style.width = "".concat(size.width, "px");
        this.root.style.height = "".concat(size.height, "px");
    };
    var CrusorAIManagerEditor_1;
    CrusorAIManagerEditor.ID = CRUSOR_AI_MANAGER_EDITOR_ID;
    CrusorAIManagerEditor = CrusorAIManagerEditor_1 = __decorate([
        __param(1, ITelemetryService),
        __param(2, IThemeService),
        __param(3, IStorageService),
        __param(4, ICrusorAIRendererService)
    ], CrusorAIManagerEditor);
    return CrusorAIManagerEditor;
}(EditorPane));
export { CrusorAIManagerEditor };
