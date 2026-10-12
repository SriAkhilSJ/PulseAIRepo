/*---------------------------------------------------------------------------------------------
 * Port of hermes desktop `lib/reasoning-effort.ts` (D:/hermes/hermes-agent/apps/desktop/src/lib/reasoning-effort.ts)
 * — the reasoning-effort ladder the Think picker renders.
 *--------------------------------------------------------------------------------------------*/

/** Hermes' reasoning levels, in ascending order — mirrors the backend's
 *  VALID_REASONING_EFFORTS (src/config/reasoning_config.py). `none` is not a
 *  level: it is thinking disabled, owned by the Off entry rather than the scale. */
export const CRUSOR_AI_REASONING_EFFORTS = ['low', 'medium', 'high'] as const;

export type CrusorReasoningEffort = (typeof CRUSOR_AI_REASONING_EFFORTS)[number];

/** The scale plus the off state — the full set a config value may hold. */
export const CRUSOR_AI_REASONING_EFFORT_VALUES = ['none', ...CRUSOR_AI_REASONING_EFFORTS] as const;

export type CrusorReasoningEffortValue = (typeof CRUSOR_AI_REASONING_EFFORT_VALUES)[number];

/** Built-in level when neither the surface nor the config specifies
 *  one: thinking is disabled by default unless explicitly chosen. */
export const CRUSOR_AI_DEFAULT_REASONING_EFFORT: CrusorReasoningEffortValue = 'none';

/** Compact labels for chrome where space is tight (pill, picker rows). The
 *  backend accepts the full hermes ladder; this surface exposes the three
 *  levels the Think picker offers plus Off. */
const SHORT_LABELS: Record<string, string> = {
	none: 'Off',
	low: 'Low',
	medium: 'Med',
	high: 'High',
};

export function reasoningEffortLabel(effort: string): string {
	const key = effort.trim().toLowerCase();
	return key ? (SHORT_LABELS[key] ?? effort) : 'Off';
}

export const isReasoningEffort = (value: string): value is CrusorReasoningEffort =>
	(CRUSOR_AI_REASONING_EFFORTS as readonly string[]).includes(value.trim().toLowerCase());

/** Thinking is off unless a level explicitly enables it (e.g. low, medium, high). */
export const isThinkingEnabled = (effort: string, fallback: string = CRUSOR_AI_DEFAULT_REASONING_EFFORT): boolean => {
	const val = (effort.trim().toLowerCase() || fallback);
	return val !== 'none' && val !== '';
};

/** The level a scale control should show. Empty or 'none' selects 'none';
 *  anything unrecognized clamps to 'none'. */
export function resolveReasoningEffort(effort: string, fallback: string = CRUSOR_AI_DEFAULT_REASONING_EFFORT): string {
	const value = effort.trim().toLowerCase() || fallback;
	if (value === 'none' || !value) {
		return 'none';
	}
	return isReasoningEffort(value) ? value : 'none';
}
