// Crusor Connectors — show MCP/connectors in fork (Hermes hub parity).
// Registers Crusor: Show Connectors (Command Palette + Crusor menu).
// Reads skills SKILL.md manifest via SkillManager and .crusorai/mcp.json
// if present, then notifies — lightweight until a full Manager pane tab
// is warranted. Designed to be the entry point for the enterprise
// connectors hub (mcp, github, browser, db, terminal).
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
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
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
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
var CONNECTORS = [
    { label: '$(plug) MCP', description: 'Model Context Protocol', detail: 'filesystem, github, postgres, puppeteer servers from .crusorai/mcp.json — say "list my MCP servers" in chat', id: 'mcp' },
    { label: '$(mark-github) GitHub connector', description: 'PRs and issues', detail: 'say "open the PR reviews for this repo" — uses gh / MCP github', id: 'github-connector' },
    { label: '$(browser) Browser connector', description: 'CDP / puppeteer verification', detail: 'say "verify the UI works" — Crusor drives a real browser and checks the page', id: 'browser-connector' },
    { label: '$(database) DB connector', description: 'postgres / sqlite', detail: 'say "query the users table" — guarded read/list tools, mutations ask first', id: 'db-connector' },
    { label: '$(terminal) Terminal connector', description: 'guarded shell access', detail: 'run_terminal with approval gates — already wired into every session', id: 'terminal-connector' },
];
registerAction2(/** @class */ (function (_super) {
    __extends(class_1, _super);
    function class_1() {
        return _super.call(this, {
            id: 'crusorai.showConnectors',
            title: localize2('crusorAI.showConnectors', 'Connectors (MCP, plugins)'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_1.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var quickInput, notif, commandService, pick, row;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        quickInput = accessor.get(IQuickInputService);
                        notif = accessor.get(INotificationService);
                        commandService = accessor.get(ICommandService);
                        return [4 /*yield*/, quickInput.pick(__spreadArray(__spreadArray([], CONNECTORS.map(function (row) { return (__assign(__assign({}, row), { description: "".concat(row.description, " \u2014 ").concat(row.id) })); }), true), [
                                { label: '$(search) Get more…', description: 'Marketplace — install skills and connector packs', id: '__marketplace', detail: '' },
                                { label: '$(checklist) My Skills', description: 'everything installed — enable/disable, remove', id: '__myskills', detail: '' },
                            ], false), { placeHolder: 'Crusor Connectors — what your agent can reach beyond the workspace' })];
                    case 1:
                        pick = _a.sent();
                        if (!pick) {
                            return [2 /*return*/];
                        }
                        if (pick.id === '__marketplace') {
                            void commandService.executeCommand('crusorai.skillsHub');
                            return [2 /*return*/];
                        }
                        if (pick.id === '__myskills') {
                            void commandService.executeCommand('crusorai.mySkills');
                            return [2 /*return*/];
                        }
                        row = CONNECTORS.find(function (candidate) { return candidate.id === pick.id; });
                        if (row) {
                            notif.notify({
                                severity: Severity.Info,
                                message: "".concat(row.label.replace(/\$\([^)]+\)\s*/, ''), " \u2014 ").concat(row.detail),
                                source: 'Crusor Connectors',
                            });
                        }
                        return [2 /*return*/];
                }
            });
        });
    };
    return class_1;
}(Action2)));
