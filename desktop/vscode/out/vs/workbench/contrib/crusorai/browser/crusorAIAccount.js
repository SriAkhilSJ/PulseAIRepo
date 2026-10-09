/*---------------------------------------------------------------------------------------------
 * CrusorAI Account — top-right title-bar avatar + dropdown (image-2 parity, not clone).
 *
 * Why this exists (founder request 2026-09-21): like Antigravity IDE's pink "S"
 * avatar in the title bar, Crusor needs a single place at top-right to
 * Sign in / see who is logged in / reach IDE essentials without digging
 * through the File menu. The native VS Code Accounts (bottom-left) stays,
 * but the primary sign-in affordance for an AI IDE belongs next to the
 * window controls — where every AI IDE (Cursor, Windsurf, Antigravity)
 * puts it.
 *
 * What it shows — curated for an AI IDE (not a copy of Antigravity's text):
 *   - Header: account identity when logged in (future: reads ~/.crusorai/auth.json)
 *   - Crusor-specific: Subscription / Usage, Model & Provider, Agent Settings
 *   - IDE essentials: Keyboard Shortcuts, Themes, Docs, Changelog, Report Issue
 *   - Sign in / Sign out (opens https://www.crusor.in/login via opener)
 *
 * Placement: MenuId.TitleBar (right side of custom title bar, next to layout
 * controls & window buttons) with group 'navigation' so it stays visible even
 * when Command Center / layout controls are toggled. Uses Codicon.account so
 * the avatar is a person silhouette until we ship a real avatar image.
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
import { localize2 } from '../../../../nls.js';
import { MenuId, MenuRegistry, registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { CrusorAICommandId } from '../common/crusorAI.js';
var CRUSOR_ACCOUNT_MENU_ID = new MenuId('CrusorAccountMenu');
var CRUSOR_ACCOUNT_DASHBOARD_URL = 'https://www.crusor.in/login';
// ----- Commands ---------------------------------------------------------------
registerAction2(/** @class */ (function (_super) {
    __extends(class_1, _super);
    function class_1() {
        return _super.call(this, {
            id: CrusorAICommandId.AccountSignIn,
            title: localize2('crusorAI.account.signIn', 'Crusor: Sign in'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
            icon: Codicon.account,
        }) || this;
    }
    class_1.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, accessor.get(IOpenerService).open(CRUSOR_ACCOUNT_DASHBOARD_URL, { openExternal: true })];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_1;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_2, _super);
    function class_2() {
        return _super.call(this, {
            id: CrusorAICommandId.AccountManage,
            title: localize2('crusorAI.account.manage', 'Crusor: Manage Account'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_2.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, accessor.get(IOpenerService).open(CRUSOR_ACCOUNT_DASHBOARD_URL, { openExternal: true })];
                    case 1:
                        _a.sent();
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
            id: CrusorAICommandId.AccountSignOut,
            title: localize2('crusorAI.account.signOut', 'Crusor: Sign out'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_3.prototype.run = function () {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                return [2 /*return*/];
            });
        });
    };
    return class_3;
}(Action2)));
// Helper commands that delegate to existing workbench commands — keeps the
// dropdown as a true quick-access hub for AI-IDE ergonomics.
registerAction2(/** @class */ (function (_super) {
    __extends(class_4, _super);
    function class_4() {
        return _super.call(this, {
            id: 'crusorai.account.openSettings',
            title: localize2('crusorAI.account.openSettings', 'Crusor: Settings'),
            f1: false,
        }) || this;
    }
    class_4.prototype.run = function (accessor) {
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
    return class_4;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_5, _super);
    function class_5() {
        return _super.call(this, {
            id: 'crusorai.account.openShortcuts',
            title: localize2('crusorAI.account.openShortcuts', 'Crusor: Keyboard Shortcuts'),
            f1: false,
        }) || this;
    }
    class_5.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, accessor.get(ICommandService).executeCommand('workbench.action.openGlobalKeybindings')];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_5;
}(Action2)));
registerAction2(/** @class */ (function (_super) {
    __extends(class_6, _super);
    function class_6() {
        return _super.call(this, {
            id: 'crusorai.account.selectTheme',
            title: localize2('crusorAI.account.selectTheme', 'Crusor: Color Theme'),
            f1: false,
        }) || this;
    }
    class_6.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, accessor.get(ICommandService).executeCommand('workbench.action.selectTheme')];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_6;
}(Action2)));
// ----- Title-bar avatar button (top-right) ----------------------------------
// Visible as a person icon at far right of the title bar, next to window
// controls. Click opens the Crusor Account submenu below.
MenuRegistry.appendMenuItem(MenuId.TitleBar, {
    submenu: CRUSOR_ACCOUNT_MENU_ID,
    title: localize2('crusorAI.account.titleBar', 'Crusor Account').value,
    icon: Codicon.account,
    group: 'navigation',
    order: 100,
});
// ----- Dropdown contents — ordered by AI-IDE relevance -----------------------
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: CrusorAICommandId.AccountSignIn, title: localize2('crusorAI.account.signIn.label', 'Sign in with Google / GitHub').value },
    group: '0_account',
    order: 1,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: CrusorAICommandId.AccountManage, title: localize2('crusorAI.account.manage.label', 'Manage Account & Subscription').value },
    group: '0_account',
    order: 2,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: 'crusorai.account.openSettings', title: localize2('crusorAI.account.settings.label', 'Crusor Settings').value },
    group: '1_settings',
    order: 1,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: CrusorAICommandId.OpenSettings, title: localize2('crusorAI.account.crusorSettings.label', 'Agent & Model Settings').value },
    group: '1_settings',
    order: 2,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: 'crusorai.account.openShortcuts', title: 'Keyboard Shortcuts' },
    group: '1_settings',
    order: 3,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: 'crusorai.account.selectTheme', title: 'Color Theme' },
    group: '1_settings',
    order: 4,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: 'workbench.action.openDocumentationUrl', title: 'Documentation' },
    group: '2_help',
    order: 1,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: 'workbench.action.showChangelog', title: 'Release Notes' },
    group: '2_help',
    order: 2,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: 'workbench.action.openIssueReporter', title: 'Report Issue / Feedback' },
    group: '2_help',
    order: 3,
});
MenuRegistry.appendMenuItem(CRUSOR_ACCOUNT_MENU_ID, {
    command: { id: CrusorAICommandId.AccountSignOut, title: localize2('crusorAI.account.signOut.label', 'Sign out').value },
    group: '3_signout',
    order: 1,
});
