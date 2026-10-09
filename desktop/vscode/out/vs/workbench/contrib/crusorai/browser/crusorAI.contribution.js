/*---------------------------------------------------------------------------------------------
 * CrusorAI IDE first-party workbench registration. Never an extension.
 *
 * Entry points (all fire the same command -> crusorai.focus):
 *   - Top-level "Crusor" menu between Terminal and Help
 *   - Ctrl/Cmd+L (market standard: Cursor, Windsurf)
 *   - Title-bar (command center) Crusor icon, one-click open
 *   - F1 Command Palette: "Crusor: Open Agent"
 *   - View menu (auto-added by viewsService for AuxiliaryBar views)
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
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode, KeyMod } from '../../../../base/common/keyCodes.js';
import { localize, localize2 } from '../../../../nls.js';
import { MenuId, MenuRegistry, registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { ContextKeyExpr } from '../../../../platform/contextkey/common/contextkey.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { SyncDescriptor } from '../../../../platform/instantiation/common/descriptors.js';
import { InstantiationType, registerSingleton } from '../../../../platform/instantiation/common/extensions.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { KeybindingWeight } from '../../../../platform/keybinding/common/keybindingsRegistry.js';
import { Registry } from '../../../../platform/registry/common/platform.js';
import { ConfigurationScope, Extensions as ConfigurationExtensions } from '../../../../platform/configuration/common/configurationRegistry.js';
import { WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { IViewsService } from '../../../services/views/common/viewsService.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { ICrusorAISessionStore, CrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { crusorSessionIdFromUri, crusorSessionRows } from '../common/crusorAISessionProjection.js';
import { CrusorAIPreviewService, ICrusorAIPreviewService } from './crusorAIPreviewService.js';
import { EditorPaneDescriptor } from '../../../browser/editor.js';
import './crusorAISessionController.js';
import './crusorAISkillsHub.js';
import './crusorAIOneShot.js';
import { ViewPaneContainer } from '../../../browser/parts/views/viewPaneContainer.js';
import { Extensions as ViewContainerExtensions, ViewContainerLocation, } from '../../../common/views.js';
import { EditorExtensions } from '../../../common/editor.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { CRUSOR_AI_VIEW_CONTAINER_ID, CRUSOR_AI_VIEW_ID, CrusorAICommandId, } from '../common/crusorAI.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { ICrusorAIWorkbenchService } from '../common/crusorAIWorkbenchService.js';
import { CrusorAIManagerEditor } from './crusorAIManagerEditor.js';
import { CrusorAIManagerInput, CrusorAIManagerInputSerializer } from './crusorAIManagerInput.js';
import { CrusorAIRendererService } from './crusorAIRendererService.js';
import { CrusorAIViewPane } from './crusorAIViewPane.js';
import { CrusorAIWorkbenchService } from './crusorAIWorkbenchService.js';
import { CrusorAIUnavailableEngineService } from './crusorAIUnavailableEngineService.js';
import './media/crusorAI-tokens.css';
import './media/crusorAI.css';
// Hide Copilot's CHAT tab, empty-editor watermark, and title-bar sign-in UI
// when Crusor is the primary AI. No Copilot source is modified; this file
// forces Copilot's own "hidden" context keys at startup.
import './crusorAIHideCopilot.js';
// Top-right account avatar + dropdown — AI-IDE essentials at title bar (image-2 parity)
import './crusorAIAccount.js';
// Connectors hub — MCP/connectors visible in fork (Hermes hub parity)
import './crusorAIConnectors.js';
var CRUSOR_AI_MENU_ID = new MenuId('MenubarCrusorAI');
// Keep common/web hosts constructable. The desktop entrypoint registers its
// utility-process implementation later, replacing this no-process fallback.
registerSingleton(ICrusorAIEngineService, CrusorAIUnavailableEngineService, InstantiationType.Delayed);
registerSingleton(ICrusorAIWorkbenchService, CrusorAIWorkbenchService, InstantiationType.Delayed);
registerSingleton(ICrusorAIRendererService, CrusorAIRendererService, InstantiationType.Delayed);
// The Agent Manager's session list and the workbench's own Agent Sessions list are projections of
// this store. It is a singleton rather than renderer state so that a session the user ran is
// remembered even while neither surface is mounted.
registerSingleton(ICrusorAISessionStore, CrusorAISessionStore, InstantiationType.Delayed);
// Crusor Preview: availability from what the session actually built, the separate preview window, and
// the reviewed-batch handoff back into the Agent (steps 1, 2 and 9 of the flow; 3-8 live in the window).
registerSingleton(ICrusorAIPreviewService, CrusorAIPreviewService, InstantiationType.Delayed);
// --- Crusor container (right-side auxiliary bar) ---------------------------
// Lives on the right (secondary) sidebar — same default location as Cursor's
// chat panel, Windsurf's Cascade, and VS Code's Copilot Chat.
var container = Registry.as(ViewContainerExtensions.ViewContainersRegistry).registerViewContainer({
    id: CRUSOR_AI_VIEW_CONTAINER_ID,
    title: localize2('crusorAI.viewContainer.title', 'Crusor'),
    icon: Codicon.cursor,
    ctorDescriptor: new SyncDescriptor(ViewPaneContainer, [
        CRUSOR_AI_VIEW_CONTAINER_ID,
        { mergeViewWithContainerWhenSingleView: true },
    ]),
    storageId: CRUSOR_AI_VIEW_CONTAINER_ID,
    order: 6,
}, ViewContainerLocation.AuxiliaryBar);
Registry.as(ViewContainerExtensions.ViewsRegistry).registerViews([{
        id: CRUSOR_AI_VIEW_ID,
        name: localize2('crusorAI.view.name', 'Crusor Agent'),
        containerIcon: Codicon.cursor,
        canToggleVisibility: true,
        canMoveView: false,
        ctorDescriptor: new SyncDescriptor(CrusorAIViewPane),
    }], container);
// Fixed agent — hidden until Ctrl+L (no auto-open, no title card)
var CrusorAutoHideContribution = /** @class */ (function () {
    function CrusorAutoHideContribution(viewsService) {
        try {
            viewsService.closeView(CRUSOR_AI_VIEW_ID);
        }
        catch (_a) { }
    }
    CrusorAutoHideContribution.ID = 'workbench.contrib.crusorai.autoHide';
    CrusorAutoHideContribution = __decorate([
        __param(0, IViewsService)
    ], CrusorAutoHideContribution);
    return CrusorAutoHideContribution;
}());
registerWorkbenchContribution2(CrusorAutoHideContribution.ID, CrusorAutoHideContribution, WorkbenchPhase.AfterRestored);
// --- Crusor Manager (full-width editor tab, Copilot "Agents Window" analogue)
Registry.as(EditorExtensions.EditorFactory).registerEditorSerializer(CrusorAIManagerInput.ID, CrusorAIManagerInputSerializer);
Registry.as(EditorExtensions.EditorPane).registerEditorPane(EditorPaneDescriptor.create(CrusorAIManagerEditor, CrusorAIManagerEditor.ID, localize('crusorAI.manager.editor', 'Crusor Manager')), [new SyncDescriptor(CrusorAIManagerInput)]);
// --- Primary open command: crusorai.focus ----------------------------------
// Explicit action, not auto-wired. Keybinding Ctrl/Cmd+L (market-standard
// "talk to the AI" chord: Cursor, Windsurf). Weighted at WorkbenchContrib
// (200) which outranks the editor's built-in expandLineSelection (EditorCore
// = 0) — same global-steal trick Cursor and Windsurf ship.
function openCrusorAgent(accessor) {
    return __awaiter(this, void 0, Promise, function () {
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: 
                // openView with focus=true behaves like every other VS Code "open view"
                // command (Explorer, Search, SCM, Debug, Terminal, Chat): if the view is
                // already open it just focuses it; if closed it opens and mounts the pane.
                // Deliberately avoids casting to any or reaching into private API.
                return [4 /*yield*/, accessor.get(IViewsService).openView(CRUSOR_AI_VIEW_ID, true)];
                case 1:
                    // openView with focus=true behaves like every other VS Code "open view"
                    // command (Explorer, Search, SCM, Debug, Terminal, Chat): if the view is
                    // already open it just focuses it; if closed it opens and mounts the pane.
                    // Deliberately avoids casting to any or reaching into private API.
                    _a.sent();
                    return [2 /*return*/];
            }
        });
    });
}
registerAction2(/** @class */ (function (_super) {
    __extends(class_1, _super);
    function class_1() {
        return _super.call(this, {
            id: CrusorAICommandId.Focus,
            title: localize2('crusorAI.focus', 'Crusor: Open Agent'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
            icon: Codicon.cursor,
            keybinding: {
                weight: KeybindingWeight.WorkbenchContrib,
                primary: KeyMod.CtrlCmd | KeyCode.KeyL,
            },
        }) || this;
    }
    class_1.prototype.run = function (accessor) { return openCrusorAgent(accessor); };
    return class_1;
}(Action2)));
// --- Top-level Crusor menu (between Terminal and Help) ---------------------
// Menubar order reference (menubar.contribution.ts + debug.contribution.ts):
//   File(1) · Edit(2) · Selection(3) · View(4) · Go(5) · Run(6) · Terminal(7)
//   ······ Crusor(7.5) ······ Help(8) · Preferences(9, Mac-only)
MenuRegistry.appendMenuItem(MenuId.MenubarMainMenu, {
    submenu: CRUSOR_AI_MENU_ID,
    title: {
        value: 'Crusor',
        original: 'Crusor',
        mnemonicTitle: localize({ key: 'mCrusor', comment: ['&& denotes a mnemonic'] }, '&&Crusor'),
    },
    order: 7.5,
});
// First item in the Crusor dropdown reuses the explicit open command so the
// Ctrl+L shortcut shows up next to it automatically.
MenuRegistry.appendMenuItem(CRUSOR_AI_MENU_ID, {
    command: {
        id: CrusorAICommandId.Focus,
        title: localize('crusorAI.menu.openAgent', 'Open Crusor Agent'),
    },
    group: '0_open',
    order: 1,
});
// --- Title-bar (command center) Crusor icon --------------------------------
// Copilot shows a Copilot/sparkle icon in the top-center command center that
// one-clicks opens chat. We mirror that with a crusor icon firing the same
// open command as Ctrl+L. Appears when window.commandCenter is enabled
// (default in modern Code OSS).
MenuRegistry.appendMenuItem(MenuId.CommandCenterCenter, {
    command: {
        id: CrusorAICommandId.Focus,
        title: localize2('crusorAI.commandCenter.tooltip', 'Open Crusor Agent (Ctrl+L)'),
        icon: Codicon.cursor,
    },
    order: -100,
});
// --- Session / review / control / settings entries -----------------------
registerAction2(/** @class */ (function (_super) {
    __extends(class_2, _super);
    function class_2() {
        return _super.call(this, {
            id: CrusorAICommandId.NewSession,
            title: localize2('crusorAI.newSession', 'New Agent Session'),
            f1: true,
            icon: Codicon.add,
            menu: [
                { id: CRUSOR_AI_MENU_ID, group: '1_session', order: 1 },
                { id: MenuId.ViewTitle, when: ContextKeyExpr.equals('view', CRUSOR_AI_VIEW_ID), group: 'navigation', order: 0 }
            ],
        }) || this;
    }
    class_2.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var rendererService;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        rendererService = accessor.get(ICrusorAIRendererService);
                        return [4 /*yield*/, openCrusorAgent(accessor)];
                    case 1:
                        _a.sent();
                        rendererService.newSession();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_2;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_3, _super);
    function class_3() {
        return _super.call(this, {
            id: CrusorAICommandId.OpenManager,
            title: localize2('crusorAI.openManager', 'Open Crusor Manager'),
            f1: true,
            icon: Codicon.organization,
            menu: [
                { id: CRUSOR_AI_MENU_ID, group: '1_session', order: 2 },
            ],
        }) || this;
    }
    class_3.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var input;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        input = accessor.get(IInstantiationService).createInstance(CrusorAIManagerInput);
                        return [4 /*yield*/, accessor.get(IEditorService).openEditor(input, { pinned: true })];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_3;
}(Action2)));
MenuRegistry.appendMenuItem(CRUSOR_AI_MENU_ID, {
    command: { id: 'crusorai.showConnectors', title: localize('crusorAI.menu.connectors', 'Connectors') },
    group: '1_session',
    order: 3,
});
registerAction2(/** @class */ (function (_super) {
    __extends(class_4, _super);
    function class_4() {
        return _super.call(this, {
            id: 'crusorai.openPreview',
            title: localize2('crusorAI.openPreview', 'Open Crusor Preview'),
            f1: true,
            icon: Codicon.openPreview,
            menu: [{ id: CRUSOR_AI_MENU_ID, group: '1_session', order: 4 }],
        }) || this;
    }
    class_4.prototype.run = function (accessor, target) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                // Opens the SEPARATE desktop window for the UI the agent built. It REFUSES
                // with a reason when the pre-flight conditions fail (no proxy, dead dev
                // server, nothing to preview) — an honest {ok:false} beats a white window
                // every time, and preview.open forwards that refusal to the agent.
                return [2 /*return*/, accessor.get(ICrusorAIPreviewService).openPreview(target)];
            });
        });
    };
    return class_4;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_5, _super);
    function class_5() {
        return _super.call(this, {
            id: CrusorAICommandId.ReviewChanges,
            title: localize2('crusorAI.reviewChanges', 'Review Changes'),
            f1: true,
            icon: Codicon.diff,
            menu: [{ id: CRUSOR_AI_MENU_ID, group: '2_review', order: 1 }],
        }) || this;
    }
    class_5.prototype.run = function (accessor) { return openCrusorAgent(accessor); };
    return class_5;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_6, _super);
    function class_6() {
        return _super.call(this, {
            id: CrusorAICommandId.OpenCheckpoints,
            title: localize2('crusorAI.openCheckpoints', 'Checkpoints'),
            f1: true,
            icon: Codicon.history,
            menu: [{ id: CRUSOR_AI_MENU_ID, group: '2_review', order: 2 }],
        }) || this;
    }
    class_6.prototype.run = function (accessor) { return openCrusorAgent(accessor); };
    return class_6;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_7, _super);
    function class_7() {
        return _super.call(this, {
            id: CrusorAICommandId.StopActiveRun,
            title: localize2('crusorAI.stopActiveRun', 'Stop Active Run'),
            f1: true,
            icon: Codicon.debugStop,
            menu: [{ id: CRUSOR_AI_MENU_ID, group: '3_control', order: 1 }],
        }) || this;
    }
    class_7.prototype.run = function (accessor) { return openCrusorAgent(accessor); };
    return class_7;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_8, _super);
    function class_8() {
        return _super.call(this, {
            id: CrusorAICommandId.AcceptDiff,
            title: localize2('crusorAI.acceptDiff', 'Accept Change'),
            f1: true,
            icon: Codicon.check,
            menu: [{
                    id: MenuId.EditorTitle,
                    group: 'navigation@1',
                    when: ContextKeyExpr.has('crusorai.hasActiveDiff'),
                }],
        }) || this;
    }
    class_8.prototype.run = function (accessor) {
        accessor.get(ICrusorAIWorkbenchService).acceptActiveDiff();
    };
    return class_8;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_9, _super);
    function class_9() {
        return _super.call(this, {
            id: CrusorAICommandId.RejectDiff,
            title: localize2('crusorAI.rejectDiff', 'Reject Change'),
            f1: true,
            icon: Codicon.close,
            menu: [{
                    id: MenuId.EditorTitle,
                    group: 'navigation@2',
                    when: ContextKeyExpr.has('crusorai.hasActiveDiff'),
                }],
        }) || this;
    }
    class_9.prototype.run = function (accessor) {
        accessor.get(ICrusorAIWorkbenchService).rejectActiveDiff();
    };
    return class_9;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_10, _super);
    function class_10() {
        return _super.call(this, {
            id: CrusorAICommandId.OpenSettings,
            title: localize2('crusorAI.openSettings', 'Crusor Settings'),
            f1: true,
            icon: Codicon.settingsGear,
            menu: [{ id: CRUSOR_AI_MENU_ID, group: '4_settings', order: 1 }],
        }) || this;
    }
    class_10.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, accessor.get(ICommandService).executeCommand('workbench.action.openSettings', 'crusorai')];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_10;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_11, _super);
    function class_11() {
        return _super.call(this, {
            id: 'crusorai.showHistory',
            title: localize2('crusorAI.showHistory', 'Crusor: Show Session History'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
            icon: Codicon.history,
            menu: [{
                    id: MenuId.ViewTitle,
                    when: ContextKeyExpr.equals('view', CRUSOR_AI_VIEW_ID),
                    group: 'navigation',
                    order: 1
                }]
        }) || this;
    }
    class_11.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var quickInput, store, viewsService, rendererService, records, rows, byId, picks, pick;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        quickInput = accessor.get(IQuickInputService);
                        store = accessor.get(ICrusorAISessionStore);
                        viewsService = accessor.get(IViewsService);
                        rendererService = accessor.get(ICrusorAIRendererService);
                        records = store.records();
                        rows = crusorSessionRows(records, undefined, Date.now());
                        byId = new Map(records.map(function (item) { return [item.sessionId, item]; }));
                        picks = rows.slice(0, 20).map(function (row) {
                            var _a, _b;
                            var id = (_a = crusorSessionIdFromUri(row.resource)) !== null && _a !== void 0 ? _a : '';
                            var count = (_b = byId.get(id)) === null || _b === void 0 ? void 0 : _b.messageCount;
                            return {
                                label: row.label || 'Untitled session',
                                description: [row.description, typeof count === 'number' && count > 0 ? "".concat(count, " messages") : ''].filter(function (part) { return part.length > 0; }).join(' · '),
                                id: id,
                            };
                        });
                        if (picks.length === 0)
                            picks.push({ label: 'No sessions yet', description: 'Start a chat with Ctrl+L', id: '' });
                        return [4 /*yield*/, quickInput.pick(picks, { placeHolder: 'Crusor Session History — pick to open' })];
                    case 1:
                        pick = _a.sent();
                        if (!(pick && pick.id)) return [3 /*break*/, 3];
                        return [4 /*yield*/, viewsService.openView(CRUSOR_AI_VIEW_ID, true)];
                    case 2:
                        _a.sent();
                        rendererService.openSession(pick.id);
                        _a.label = 3;
                    case 3: return [2 /*return*/];
                }
            });
        });
    };
    return class_11;
}(Action2)));
Registry.as(ConfigurationExtensions.Configuration).registerConfiguration({
    id: 'crusorai',
    title: localize2('crusorai.copilotWebview.title', 'CrusorAI CopilotKit Webview').value,
    type: 'object',
    properties: {
        'crusorai.copilotWebview.enabled': {
            type: 'boolean',
            default: true,
            scope: ConfigurationScope.APPLICATION,
            description: localize('crusorai.copilotWebview.enabled.desc', "Show the CopilotKit React surface (crusor-webview) under the native Crusor Agent view. Turn off to give the whole pane to the native renderer."),
        },
        'crusorai.copilotWebview.url': {
            type: 'string',
            default: 'local',
            scope: ConfigurationScope.APPLICATION,
            description: localize('crusorai.copilotWebview.url.desc', "What the CopilotKit tab loads. 'local' (default) uses the SPA built into the app by `npm run build` in crusor-webview, which needs no server and works in packaged or remote windows. Any other value is an absolute URL framed as-is -- the workbench CSP allows only 'self' and vscode-webview:, so an http URL will be refused unless you extend the frame policy, and a dev server on :5173 therefore belongs in a browser tab, not here.")
        },
        'crusorai.copilotWebview.height': {
            type: 'number',
            default: 50,
            minimum: 10,
            maximum: 85,
            scope: ConfigurationScope.APPLICATION,
            description: localize('crusorai.copilotWebview.height.desc', "Share of the Crusor view given to the CopilotKit webview, in percent. The native Agent renderer keeps the rest."),
        },
        'crusorai.notifyOnComplete': {
            type: 'boolean',
            default: true,
            scope: ConfigurationScope.APPLICATION,
            description: localize('crusorAI.notifyOnComplete.desc', "Show a 'Response Ready — Crusor' notification when the agent finishes a run. Disable to keep runs silent."),
        },
    },
});
