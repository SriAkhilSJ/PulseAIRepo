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

/** Hermes' built-in level when neither the surface nor the config specifies
 *  one (mirrors the backend's own fallback). */
export const CRUSOR_AI_DEFAULT_REASONING_EFFORT: CrusorReasoningEffort = 'medium';

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
	return key ? (SHORT_LABELS[key] ?? effort) : '';
}

export const isReasoningEffort = (value: string): value is CrusorReasoningEffort =>
	(CRUSOR_AI_REASONING_EFFORTS as readonly string[]).includes(value.trim().toLowerCase());

/** Thinking is on unless a level explicitly says otherwise; an empty value
 *  means "inherit", so it resolves through `fallback` first. */
export const isThinkingEnabled = (effort: string, fallback: string = CRUSOR_AI_DEFAULT_REASONING_EFFORT): boolean =>
	(effort.trim().toLowerCase() || fallback) !== 'none';

/** The level a scale control should show. Empty inherits `fallback`; `none`
 *  (thinking off) selects nothing; anything unrecognized clamps to the default. */
export function resolveReasoningEffort(effort: string, fallback: string = CRUSOR_AI_DEFAULT_REASONING_EFFORT): string {
	const value = effort.trim().toLowerCase() || fallback;
	if (value === 'none') {
		return '';
	}
	return isReasoningEffort(value) ? value : CRUSOR_AI_DEFAULT_REASONING_EFFORT;
}
