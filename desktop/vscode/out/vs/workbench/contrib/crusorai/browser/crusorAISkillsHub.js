// Crusor Skills Hub — the visual skills surface (Phase 3).
// Two Command Palette entries, QuickPick-driven (same shape as
// Crusor: Show Session History), talking to the engine through the
// skills_hub_op bridge envelope:
//
//   Crusor: Skills Hub  — browse the curated catalog, install, update,
//                         remove hub-installed skills (with update badges)
//   Crusor: My Skills   — every installed skill (any origin): enable /
//                         disable, remove hub installs, usage counts
//
// Everything rides the sandboxed pipeline (SHA pins, caps, collision
// guard) — the UI adds zero trust decisions of its own. Results come
// back as skills_hub_result frames; each request awaits exactly one
// matching frame with a timeout, and the flows are serial by design so
// same-op requests can never cross-resolve.
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
import { localize2 } from '../../../../nls.js';
import { registerAction2, Action2 } from '../../../../platform/actions/common/actions.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { IQuickInputService } from '../../../../platform/quickinput/common/quickInput.js';
import { IProgressService, ProgressLocation } from '../../../../platform/progress/common/progress.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
var HUB_TIMEOUT_MS = 12000;
function hubRequest(renderer, progress, op, extra) {
    if (extra === void 0) { extra = {}; }
    // The progress badge is the click's first ACK: palette flows must show
    // life IMMEDIATELY (field 2026-10-01: a silent 45s wait read as "nothing
    // happened" when the running bridge predated the Skills Hub build).
    return progress.withProgress({ location: ProgressLocation.Window, title: "Skills Hub: ".concat(op, "\u2026") }, function () {
        return new Promise(function (resolve, reject) {
            var listener;
            var timer = setTimeout(function () {
                listener === null || listener === void 0 ? void 0 : listener.dispose();
                reject(new Error("Skills Hub: the engine did not answer the '".concat(op, "' request. Fully restart CrusorAI so the bridge process runs the Skills Hub build (pull \u2192 npx gulp compile in desktop/vscode \u2192 restart).")));
            }, HUB_TIMEOUT_MS);
            listener = renderer.onSkillsHubResult(function (frame) {
                var _a;
                if (frame.op !== op) {
                    return; // not ours (a future concurrent flow) — keep waiting
                }
                clearTimeout(timer);
                listener === null || listener === void 0 ? void 0 : listener.dispose();
                resolve(((_a = frame.result) !== null && _a !== void 0 ? _a : {}));
            });
            renderer.sendSkillsHubOp(op, extra);
        });
    });
}
function hubError(result, fallback) {
    var err = typeof (result === null || result === void 0 ? void 0 : result.error) === 'string' ? result.error : fallback;
    return "Skills Hub: ".concat(err);
}
registerAction2(/** @class */ (function (_super) {
    __extends(class_1, _super);
    function class_1() {
        return _super.call(this, {
            id: 'crusorai.skillsHub',
            title: localize2('crusorAI.skillsHub', 'Skills Hub'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_1.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var quickInput, notif, renderer, progress, installed, res, error_1, updates, commandService, picks, _i, _a, row, pick, query, results, res, error_2, resultPicks, chosen, res, error_3, res, done, moved, error_4, actions, action, res, detail, error_5;
            var _b, _c, _d, _e, _f, _g, _h;
            return __generator(this, function (_j) {
                switch (_j.label) {
                    case 0:
                        quickInput = accessor.get(IQuickInputService);
                        notif = accessor.get(INotificationService);
                        renderer = accessor.get(ICrusorAIRendererService);
                        progress = accessor.get(IProgressService);
                        installed = [];
                        _j.label = 1;
                    case 1:
                        _j.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, hubRequest(renderer, progress, 'list')];
                    case 2:
                        res = _j.sent();
                        if (res.ok === false) {
                            // A failed list must say so — rendering the empty state here
                            // told the user "no skills installed" while the engine was
                            // actually erroring (field 2026-10-01).
                            notif.notify({ severity: Severity.Error, message: hubError(res, 'could not list hub-installed skills'), source: 'Crusor Skills Hub' });
                            return [2 /*return*/];
                        }
                        installed = Array.isArray(res.installed) ? res.installed : [];
                        return [3 /*break*/, 4];
                    case 3:
                        error_1 = _j.sent();
                        notif.notify({ severity: Severity.Error, message: String((_b = error_1.message) !== null && _b !== void 0 ? _b : error_1), source: 'Crusor Skills Hub' });
                        return [2 /*return*/];
                    case 4:
                        updates = installed.filter(function (row) { return row.update_available; });
                        commandService = accessor.get(ICommandService);
                        picks = [
                            { label: '$(search) Search the Skills Hub…', description: 'curated catalog — install with one click', id: '__search' },
                            // The composer + button opens THIS dialog directly, so the other
                            // quick actions ride as rows — one entry point, no dropdown.
                            { label: '$(checklist) My Skills', description: 'every installed skill — enable/disable, usage, remove', id: '__myskills' },
                            { label: '$(zap) One-Shot Task…', description: 'commit message, summarize, name ideas — to clipboard', id: '__oneshot' },
                        ];
                        if (updates.length > 0) {
                            picks.push({
                                label: "$(cloud-download) Update all (".concat(updates.length, ")"),
                                description: updates.map(function (row) { return row.name; }).join(', '),
                                id: '__update',
                            });
                        }
                        for (_i = 0, _a = installed.slice(0, 40); _i < _a.length; _i++) {
                            row = _a[_i];
                            picks.push({
                                label: "".concat(row.update_available ? '$(arrow-up)' : '$(check)', " ").concat(row.name),
                                description: "".concat(row.repo, " @ ").concat(String((_c = row.sha) !== null && _c !== void 0 ? _c : '').slice(0, 12), " [").concat(row.trust, "]").concat(row.update_available ? ' — update available' : ''),
                                id: String(row.name),
                            });
                        }
                        if (installed.length === 0) {
                            picks.push({ label: 'No hub-installed skills yet', description: 'Search the catalog to install your first one', id: '__none' });
                        }
                        return [4 /*yield*/, quickInput.pick(picks, { placeHolder: 'Crusor Skills Hub — browse, install, update' })];
                    case 5:
                        pick = _j.sent();
                        if (!pick) {
                            return [2 /*return*/];
                        }
                        if (pick.id === '__myskills') {
                            void commandService.executeCommand('crusorai.mySkills');
                            return [2 /*return*/];
                        }
                        if (pick.id === '__oneshot') {
                            void commandService.executeCommand('crusorai.oneshot');
                            return [2 /*return*/];
                        }
                        if (!(pick.id === '__search')) return [3 /*break*/, 16];
                        return [4 /*yield*/, quickInput.input({ prompt: 'Search the Skills Hub catalog (keywords, e.g. "security review" or "react")' })];
                    case 6:
                        query = _j.sent();
                        if (!query || !query.trim()) {
                            return [2 /*return*/];
                        }
                        results = [];
                        _j.label = 7;
                    case 7:
                        _j.trys.push([7, 9, , 10]);
                        return [4 /*yield*/, hubRequest(renderer, progress, 'search', { query: query.trim() })];
                    case 8:
                        res = _j.sent();
                        results = Array.isArray(res.results) ? res.results : [];
                        return [3 /*break*/, 10];
                    case 9:
                        error_2 = _j.sent();
                        notif.notify({ severity: Severity.Error, message: String((_d = error_2.message) !== null && _d !== void 0 ? _d : error_2), source: 'Crusor Skills Hub' });
                        return [2 /*return*/];
                    case 10:
                        if (results.length === 0) {
                            notif.notify({ severity: Severity.Info, message: "Skills Hub: no catalog match for \"".concat(query.trim(), "\". You can install any GitHub repo from chat: hub_install(\"owner/repo@<sha>\")."), source: 'Crusor Skills Hub' });
                            return [2 /*return*/];
                        }
                        resultPicks = results.map(function (entry) { return ({
                            label: "$(package) ".concat(entry.name, " [").concat(entry.category || 'general', "]"),
                            description: "".concat(entry.trust, " \u2014 ").concat(entry.description),
                            id: String(entry.name),
                        }); });
                        return [4 /*yield*/, quickInput.pick(resultPicks, { placeHolder: 'Crusor Skills Hub — pick a skill to install' })];
                    case 11:
                        chosen = _j.sent();
                        if (!chosen) {
                            return [2 /*return*/];
                        }
                        _j.label = 12;
                    case 12:
                        _j.trys.push([12, 14, , 15]);
                        return [4 /*yield*/, hubRequest(renderer, progress, 'install', { source: chosen.id })];
                    case 13:
                        res = _j.sent();
                        if (res.ok) {
                            notif.notify({ severity: Severity.Info, message: "Skills Hub: installed \"".concat(chosen.id, "\" (").concat(res.files, " files, pinned at ").concat(String((_e = res.sha) !== null && _e !== void 0 ? _e : '').slice(0, 12), "). It is live in the skills index now."), source: 'Crusor Skills Hub' });
                        }
                        else {
                            notif.notify({ severity: Severity.Error, message: hubError(res, 'install failed'), source: 'Crusor Skills Hub' });
                        }
                        return [3 /*break*/, 15];
                    case 14:
                        error_3 = _j.sent();
                        notif.notify({ severity: Severity.Error, message: String((_f = error_3.message) !== null && _f !== void 0 ? _f : error_3), source: 'Crusor Skills Hub' });
                        return [3 /*break*/, 15];
                    case 15: return [2 /*return*/];
                    case 16:
                        if (!(pick.id === '__update')) return [3 /*break*/, 21];
                        _j.label = 17;
                    case 17:
                        _j.trys.push([17, 19, , 20]);
                        return [4 /*yield*/, hubRequest(renderer, progress, 'update')];
                    case 18:
                        res = _j.sent();
                        done = Array.isArray(res.updated) ? res.updated : [];
                        moved = done.filter(function (row) { return row.ok && row.updated; });
                        notif.notify({
                            severity: Severity.Info,
                            message: moved.length > 0
                                ? "Skills Hub: updated ".concat(moved.length, " skill(s) \u2014 ").concat(moved.map(function (row) { var _a; return "".concat(row.name, " \u2192 ").concat(String((_a = row.to_sha) !== null && _a !== void 0 ? _a : '').slice(0, 12)); }).join(', '))
                                : 'Skills Hub: everything is already at the catalog-pinned versions.',
                            source: 'Crusor Skills Hub',
                        });
                        return [3 /*break*/, 20];
                    case 19:
                        error_4 = _j.sent();
                        notif.notify({ severity: Severity.Error, message: String((_g = error_4.message) !== null && _g !== void 0 ? _g : error_4), source: 'Crusor Skills Hub' });
                        return [3 /*break*/, 20];
                    case 20: return [2 /*return*/];
                    case 21:
                        if (!(pick.id !== '__none')) return [3 /*break*/, 26];
                        actions = [
                            { label: '$(arrow-up) Update to the catalog-pinned version', id: 'update' },
                            { label: '$(trash) Remove this skill', id: 'remove' },
                        ];
                        return [4 /*yield*/, quickInput.pick(actions, { placeHolder: "".concat(pick.id, " \u2014 choose an action") })];
                    case 22:
                        action = _j.sent();
                        if (!action) {
                            return [2 /*return*/];
                        }
                        _j.label = 23;
                    case 23:
                        _j.trys.push([23, 25, , 26]);
                        return [4 /*yield*/, hubRequest(renderer, progress, action.id, { name: pick.id })];
                    case 24:
                        res = _j.sent();
                        if (res.ok) {
                            detail = action.id === 'update' && !res.updated
                                ? ' (already at the pinned version)'
                                : '';
                            notif.notify({ severity: Severity.Info, message: "Skills Hub: ".concat(action.id, "d \"").concat(pick.id, "\"").concat(detail), source: 'Crusor Skills Hub' });
                        }
                        else {
                            notif.notify({ severity: Severity.Error, message: hubError(res, "".concat(action.id, " failed")), source: 'Crusor Skills Hub' });
                        }
                        return [3 /*break*/, 26];
                    case 25:
                        error_5 = _j.sent();
                        notif.notify({ severity: Severity.Error, message: String((_h = error_5.message) !== null && _h !== void 0 ? _h : error_5), source: 'Crusor Skills Hub' });
                        return [3 /*break*/, 26];
                    case 26: return [2 /*return*/];
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
            id: 'crusorai.mySkills',
            title: localize2('crusorAI.mySkills', 'My Skills'),
            f1: true,
            category: localize2('crusorAI.category', 'Crusor'),
        }) || this;
    }
    class_2.prototype.run = function (accessor) {
        return __awaiter(this, void 0, Promise, function () {
            var quickInput, notif, renderer, progress, skills, res, error_6, originLabel, picks, chosen, row, actions, action, res, _a, detail, error_7;
            var _b, _c, _d;
            return __generator(this, function (_e) {
                switch (_e.label) {
                    case 0:
                        quickInput = accessor.get(IQuickInputService);
                        notif = accessor.get(INotificationService);
                        renderer = accessor.get(ICrusorAIRendererService);
                        progress = accessor.get(IProgressService);
                        skills = [];
                        _e.label = 1;
                    case 1:
                        _e.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, hubRequest(renderer, progress, 'all')];
                    case 2:
                        res = _e.sent();
                        if (res.ok === false) {
                            notif.notify({ severity: Severity.Error, message: hubError(res, 'could not list installed skills'), source: 'Crusor Skills Hub' });
                            return [2 /*return*/];
                        }
                        skills = Array.isArray(res.skills) ? res.skills : [];
                        return [3 /*break*/, 4];
                    case 3:
                        error_6 = _e.sent();
                        notif.notify({ severity: Severity.Error, message: String((_b = error_6.message) !== null && _b !== void 0 ? _b : error_6), source: 'Crusor Skills Hub' });
                        return [2 /*return*/];
                    case 4:
                        if (skills.length === 0) {
                            notif.notify({ severity: Severity.Info, message: 'No skills installed yet — open Crusor: Skills Hub to browse the catalog.', source: 'Crusor Skills Hub' });
                            return [2 /*return*/];
                        }
                        originLabel = { hub: 'hub', bundled: 'bundled', user: 'yours', agent: 'agent-learned' };
                        picks = skills.slice(0, 60).map(function (row) {
                            var _a;
                            return ({
                                label: "".concat(row.enabled ? '$(check)' : '$(circle-slash)', " ").concat(row.name),
                                description: "[".concat((_a = originLabel[row.origin]) !== null && _a !== void 0 ? _a : row.origin).concat(row.enabled ? '' : ', disabled', "] uses: ").concat(row.use_count, " \u2014 ").concat(row.description),
                                id: String(row.name),
                            });
                        });
                        return [4 /*yield*/, quickInput.pick(picks, { placeHolder: 'Crusor My Skills — pick a skill to manage' })];
                    case 5:
                        chosen = _e.sent();
                        if (!chosen) {
                            return [2 /*return*/];
                        }
                        row = skills.find(function (candidate) { return candidate.name === chosen.id; });
                        actions = [
                            { label: (row === null || row === void 0 ? void 0 : row.enabled) ? '$(circle-slash) Disable' : '$(check) Enable', id: 'toggle' },
                            { label: '$(trash) Remove (hub-installed skills only)', id: 'remove' },
                        ];
                        return [4 /*yield*/, quickInput.pick(actions, { placeHolder: "".concat(chosen.id, " \u2014 choose an action") })];
                    case 6:
                        action = _e.sent();
                        if (!action) {
                            return [2 /*return*/];
                        }
                        _e.label = 7;
                    case 7:
                        _e.trys.push([7, 12, , 13]);
                        if (!(action.id === 'toggle')) return [3 /*break*/, 9];
                        return [4 /*yield*/, hubRequest(renderer, progress, 'toggle', { name: chosen.id, enabled: !((_c = row === null || row === void 0 ? void 0 : row.enabled) !== null && _c !== void 0 ? _c : true) })];
                    case 8:
                        _a = _e.sent();
                        return [3 /*break*/, 11];
                    case 9: return [4 /*yield*/, hubRequest(renderer, progress, 'remove', { name: chosen.id })];
                    case 10:
                        _a = _e.sent();
                        _e.label = 11;
                    case 11:
                        res = _a;
                        if (res.ok) {
                            detail = action.id === 'toggle'
                                ? " \u2192 ".concat(res.enabled ? 'enabled' : 'disabled')
                                : '';
                            notif.notify({ severity: Severity.Info, message: "Skills Hub: \"".concat(chosen.id, "\"").concat(detail), source: 'Crusor Skills Hub' });
                        }
                        else {
                            notif.notify({ severity: Severity.Error, message: hubError(res, 'action failed'), source: 'Crusor Skills Hub' });
                        }
                        return [3 /*break*/, 13];
                    case 12:
                        error_7 = _e.sent();
                        notif.notify({ severity: Severity.Error, message: String((_d = error_7.message) !== null && _d !== void 0 ? _d : error_7), source: 'Crusor Skills Hub' });
                        return [3 /*break*/, 13];
                    case 13: return [2 /*return*/];
                }
            });
        });
    };
    return class_2;
}(Action2)));
