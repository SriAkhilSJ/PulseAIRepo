/*---------------------------------------------------------------------------------------------
 * Port of hermes desktop `lib/reasoning-effort.ts` (D:/hermes/hermes-agent/apps/desktop/src/lib/reasoning-effort.ts)
 * — the reasoning-effort ladder the Think picker renders.
 *--------------------------------------------------------------------------------------------*/
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
/** Hermes' reasoning levels, in ascending order — mirrors the backend's
 *  VALID_REASONING_EFFORTS (src/config/reasoning_config.py). `none` is not a
 *  level: it is thinking disabled, owned by the Off entry rather than the scale. */
export var CRUSOR_AI_REASONING_EFFORTS = ['low', 'medium', 'high'];
/** The scale plus the off state — the full set a config value may hold. */
export var CRUSOR_AI_REASONING_EFFORT_VALUES = __spreadArray(['none'], CRUSOR_AI_REASONING_EFFORTS, true);
/** Hermes' built-in level when neither the surface nor the config specifies
 *  one (mirrors the backend's own fallback). */
export var CRUSOR_AI_DEFAULT_REASONING_EFFORT = 'medium';
/** Compact labels for chrome where space is tight (pill, picker rows). The
 *  backend accepts the full hermes ladder; this surface exposes the three
 *  levels the Think picker offers plus Off. */
var SHORT_LABELS = {
    none: 'Off',
    low: 'Low',
    medium: 'Med',
    high: 'High',
};
export function reasoningEffortLabel(effort) {
    var _a;
    var key = effort.trim().toLowerCase();
    return key ? ((_a = SHORT_LABELS[key]) !== null && _a !== void 0 ? _a : effort) : '';
}
export var isReasoningEffort = function (value) {
    return CRUSOR_AI_REASONING_EFFORTS.includes(value.trim().toLowerCase());
};
/** Thinking is on unless a level explicitly says otherwise; an empty value
 *  means "inherit", so it resolves through `fallback` first. */
export var isThinkingEnabled = function (effort, fallback) {
    if (fallback === void 0) { fallback = CRUSOR_AI_DEFAULT_REASONING_EFFORT; }
    return (effort.trim().toLowerCase() || fallback) !== 'none';
};
/** The level a scale control should show. Empty inherits `fallback`; `none`
 *  (thinking off) selects nothing; anything unrecognized clamps to the default. */
export function resolveReasoningEffort(effort, fallback) {
    if (fallback === void 0) { fallback = CRUSOR_AI_DEFAULT_REASONING_EFFORT; }
    var value = effort.trim().toLowerCase() || fallback;
    if (value === 'none') {
        return '';
    }
    return isReasoningEffort(value) ? value : CRUSOR_AI_DEFAULT_REASONING_EFFORT;
}
