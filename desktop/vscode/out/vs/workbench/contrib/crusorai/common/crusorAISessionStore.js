/*---------------------------------------------------------------------------------------------
 * The one place that remembers which Crusor sessions exist. Both the Agent Manager's own list and
 * the workbench's session list are projections of this store; neither is allowed to keep a copy.
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
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Emitter } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export var ICrusorAISessionStore = createDecorator('crusorAISessionStore');
/** Sessions the manager remembers before the engine can list them. Oldest go first. */
var MAX_TRACKED_SESSIONS = 64;
function signature(facts) {
    var _a, _b, _c, _d, _e, _f, _g, _h, _j;
    var changes = facts.changes ? "".concat(facts.changes.files, ":").concat(facts.changes.insertions, ":").concat(facts.changes.deletions) : '';
    return [facts.label, facts.workspaceLabel, (_a = facts.statusName) !== null && _a !== void 0 ? _a : '', (_b = facts.firstSeenAt) !== null && _b !== void 0 ? _b : '', (_c = facts.turnStartedAt) !== null && _c !== void 0 ? _c : '', (_d = facts.turnEndedAt) !== null && _d !== void 0 ? _d : '', changes, (_e = facts.archived) !== null && _e !== void 0 ? _e : '', (_f = facts.pinned) !== null && _f !== void 0 ? _f : '', (_g = facts.unread) !== null && _g !== void 0 ? _g : '', (_h = facts.messageCount) !== null && _h !== void 0 ? _h : '', (_j = facts.lastActiveAt) !== null && _j !== void 0 ? _j : ''].join('|');
}
var CrusorAISessionStore = /** @class */ (function (_super) {
    __extends(CrusorAISessionStore, _super);
    function CrusorAISessionStore() {
        var _this = _super !== null && _super.apply(this, arguments) || this;
        _this._onDidChange = _this._register(new Emitter());
        _this.onDidChange = _this._onDidChange.event;
        /** Insertion ordered on purpose: the projection sorts for display. */
        _this.sessions = new Map();
        _this.reads = new Map();
        return _this;
    }
    CrusorAISessionStore.prototype.note = function (facts) {
        var _a;
        var previous = this.sessions.get(facts.sessionId);
        // `firstSeenAt` is a sighting, so the first one wins: a re-render must not move the age of
        // a session backwards to now.
        var merged = (previous === null || previous === void 0 ? void 0 : previous.firstSeenAt) !== undefined && previous.firstSeenAt <= ((_a = facts.firstSeenAt) !== null && _a !== void 0 ? _a : Infinity)
            ? __assign(__assign({}, facts), { firstSeenAt: previous.firstSeenAt }) : facts;
        if (previous && signature(previous) === signature(merged)) {
            return;
        }
        this.sessions.set(facts.sessionId, merged);
        while (this.sessions.size > MAX_TRACKED_SESSIONS) {
            var oldest = this.sessions.keys().next();
            if (oldest.done) {
                break;
            }
            this.sessions.delete(oldest.value);
            this.reads.delete(oldest.value);
        }
        this._onDidChange.fire();
    };
    CrusorAISessionStore.prototype.forget = function (sessionId) {
        if (!this.sessions.delete(sessionId)) {
            return;
        }
        this.reads.delete(sessionId);
        this._onDidChange.fire();
    };
    CrusorAISessionStore.prototype.markRead = function (sessionId, isRead) {
        if (this.reads.get(sessionId) === isRead) {
            return;
        }
        this.reads.set(sessionId, isRead);
        this._onDidChange.fire();
    };
    CrusorAISessionStore.prototype.isRead = function (sessionId) {
        return this.reads.get(sessionId);
    };
    CrusorAISessionStore.prototype.records = function () {
        return __spreadArray([], this.sessions.values(), true);
    };
    return CrusorAISessionStore;
}(Disposable));
export { CrusorAISessionStore };
