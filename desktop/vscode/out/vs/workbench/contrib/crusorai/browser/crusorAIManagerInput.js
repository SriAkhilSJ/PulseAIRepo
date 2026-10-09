/*---------------------------------------------------------------------------------------------
 * Stable editor input for the full-width Crusor Manager surface.
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
import { URI } from '../../../../base/common/uri.js';
import { localize } from '../../../../nls.js';
import { EditorInput } from '../../../common/editor/editorInput.js';
import { CRUSOR_AI_MANAGER_EDITOR_ID } from '../common/crusorAI.js';
var CrusorAIManagerInput = /** @class */ (function (_super) {
    __extends(CrusorAIManagerInput, _super);
    function CrusorAIManagerInput() {
        return _super !== null && _super.apply(this, arguments) || this;
    }
    Object.defineProperty(CrusorAIManagerInput.prototype, "typeId", {
        get: function () { return CrusorAIManagerInput.ID; },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIManagerInput.prototype, "editorId", {
        get: function () { return CrusorAIManagerInput.ID; },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIManagerInput.prototype, "resource", {
        get: function () { return CrusorAIManagerInput.RESOURCE; },
        enumerable: false,
        configurable: true
    });
    CrusorAIManagerInput.prototype.getName = function () { return localize('crusorAI.manager.name', 'Crusor Manager'); };
    CrusorAIManagerInput.prototype.toUntyped = function () {
        return {
            resource: CrusorAIManagerInput.RESOURCE,
            options: { override: CrusorAIManagerInput.ID, pinned: true },
        };
    };
    CrusorAIManagerInput.prototype.matches = function (other) {
        return _super.prototype.matches.call(this, other) || other instanceof CrusorAIManagerInput;
    };
    CrusorAIManagerInput.ID = CRUSOR_AI_MANAGER_EDITOR_ID;
    CrusorAIManagerInput.RESOURCE = URI.from({ scheme: 'crusorai', path: '/manager' });
    return CrusorAIManagerInput;
}(EditorInput));
export { CrusorAIManagerInput };
var CrusorAIManagerInputSerializer = /** @class */ (function () {
    function CrusorAIManagerInputSerializer() {
    }
    CrusorAIManagerInputSerializer.prototype.canSerialize = function (_editorInput) { return true; };
    CrusorAIManagerInputSerializer.prototype.serialize = function (_editorInput) { return '{}'; };
    CrusorAIManagerInputSerializer.prototype.deserialize = function (_instantiationService, _serializedEditorInput) {
        return new CrusorAIManagerInput();
    };
    return CrusorAIManagerInputSerializer;
}());
export { CrusorAIManagerInputSerializer };
