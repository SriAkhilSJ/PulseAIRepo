/**
 * Pulse semantic palette — derived, never hardcoded.
 *
 * Port of the hermes desktop theme machine (apps/desktop/src/themes/color.ts
 * and themes/vscode.ts) onto the workbench. Hermes imports VS Code theme JSON
 * and runs a "naive token converter": ~6 seed colors (background, foreground,
 * accent, elevated surface, sidebar, error), everything else mixed from those
 * seeds, with the accent contrast-enforced (WCAG AA 4.5:1) before use because
 * it renders as small labels — the "invisible purple label" case.
 *
 * Pulse's host IS the workbench, so the seeds are free: the workbench already
 * publishes the live theme as `--vscode-*` custom properties and re-publishes
 * them on every theme change. This module reads the seeds from the pane's
 * computed style, derives the `--pulseai-*` semantic outputs with the same
 * math, and writes them onto the pane root. `media/pulseAI-tokens.css` holds
 * only var() fallback chains (theme-native paint before this runs); the hand
 * per-mode hex palette it used to carry is gone.
 *
 * The only color literals in this file are the documented semantic SEEDS (the
 * machine inputs, same shape as hermes' `#10b981` success seed and `#e25563`
 * destructive fallback) and the WCAG contrast anchors. Every value the UI
 * paints is derived at runtime.
 */

import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IDisposable } from '../../../../base/common/lifecycle.js';

// ─── Constants (machine inputs, cited) ──────────────────────────────────────

/** Hermes themes/vscode.ts: the accent renders as small labels on the sidebar
 * surface, so it must clear WCAG AA for normal text or it's unreadable. */
const ACCENT_MIN_CONTRAST = 4.5;

/** WCAG 1.4.11 non-text contrast: status dots and the brand glyph are
 * graphical objects carrying state, so 3:1 against their surface. */
const DOT_MIN_CONTRAST = 3;

/** Contrast anchors. WHITE hermes color.ts ensureContrast/harmonize targets
 * and the light-anchor of the pair readableOn() measures; mid-lightness
 * accents broke every luminance threshold, which is why hermes measures. */
const WHITE = '#ffffff';

/** Hermes context.tsx: `--ui-success` = harmonize('#10b981', accent, 0.25).
 * The constant is the SEMANTIC hue seed; the painted value is derived. */
const SUCCESS_SEED = '#10b981';

/** Hermes themes/vscode.ts destructive fallback (used when the host theme
 * ships no error foreground). */
const DESTRUCTIVE_FALLBACK = '#e25563';

/** Pulse approval seed: the "needs your input" amber. Pulse semantic identity,
 * rendered through the same harmonize/contrast machine as the rest. */
const APPROVAL_SEED = '#efb75c';

/** Pulse agent-identity seed: the agent glyph/memory hue. */
const AGENT_SEED = '#9b8cff';

/** Hermes color.ts harmonize(): how far a semantic hue bends toward the
 * accent along the shortest OKLCH arc — settles the palette without erasing
 * the meaning ("done" must never become "running"). */
const HARMONIZE_STRENGTH = 0.25;

/** Hermes vscode.ts seed fallbacks: accent when a theme ships no brand token
 * (mix(foreground, background, 0.55)), and the dark-mode detection bucket. */
const ACCENT_FALLBACK_MIX = 0.55;
const DARK_LUMINANCE_BUCKET = 0.4;

// ─── Color math (ported from hermes themes/color.ts) ────────────────────────

type Rgb = [number, number, number];

const clamp255 = (n: number): number => Math.round(Math.min(255, Math.max(0, n)));

const rgbToHex = ([r, g, b]: Rgb): string =>
	`#${[r, g, b].map(n => clamp255(n).toString(16).padStart(2, '0')).join('')}`;

const hexToRgb = (hex: string): Rgb | null => {
	const clean = hex.trim().replace(/^#/, '');
	if (!/^[0-9a-f]{6}$/i.test(clean)) {
		return null;
	}
	return [0, 2, 4].map(i => parseInt(clean.slice(i, i + 2), 16)) as Rgb;
};

/** Linear blend of two colors in sRGB — hermes `mix`. Correct for neutrals;
 * accent-derived SURFACE blends wait for P3, where hermes applies its
 * hue-stable mixOklab. */
function mix(a: string, b: string, amount: number): string {
	const ar = hexToRgb(a);
	const br = hexToRgb(b);
	if (!ar || !br) {
		return a;
	}
	return rgbToHex([
		ar[0] + (br[0] - ar[0]) * amount,
		ar[1] + (br[1] - ar[1]) * amount,
		ar[2] + (br[2] - ar[2]) * amount
	]);
}

const linearize = (channel: number): number =>
	channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;

/** WCAG relative luminance (gamma-corrected), 0..1 — hermes color.ts. */
function relativeLuminance(hex: string): number {
	const rgb = hexToRgb(hex);
	if (!rgb) {
		return 0;
	}
	const [r, g, b] = rgb.map(v => linearize(v / 255));
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio (1..21) — hermes color.ts. */
function contrastRatio(a: string, b: string): number {
	const la = relativeLuminance(a);
	const lb = relativeLuminance(b);
	return la >= lb ? (la + 0.05) / (lb + 0.05) : (lb + 0.05) / (la + 0.05);
}

/** Guarantee `color` reads against `bg`: below `min`, mix toward white on a
 * dark bg (black on light) in 0.2 steps until it clears — hermes
 * `ensureContrast`, which keeps the hue as much as the space allows. */
function ensureContrast(color: string, bg: string, min: number): string {
	if (contrastRatio(color, bg) >= min) {
		return color;
	}
	const towards = relativeLuminance(bg) < 0.5 ? WHITE : '#000000';
	let best = color;
	for (let amount = 0.2; amount <= 1.0001; amount += 0.2) {
		best = mix(color, towards, Math.min(amount, 1));
		if (contrastRatio(best, bg) >= min) {
			return best;
		}
	}
	return best;
}

// ─── OKLCH (ported from hermes themes/color.ts) ─────────────────────────────
// Hue work happens in a perceptual space or it lies: HSL sweeps produce mud at
// 60° and washed teal at 200°. OKLCH holds perceived lightness/colorfulness so
// every hue lands with the same visual weight.

const linearize01 = (c: number): number => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const delinearize01 = (c: number): number => (c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055);

interface Oklch { l: number; c: number; h: number }

/** 0–255 sRGB triple → OKLab [L, a, b] (hermes rgbToOklab). */
function rgbToOklab([r255, g255, b255]: readonly number[]): [number, number, number] {
	const [r, g, b] = [r255, g255, b255].map(v => linearize01(v / 255));
	const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
	const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
	const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
	return [
		0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
		1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
		0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
	];
}

function hexToOklch(hex: string): Oklch | null {
	const rgb = hexToRgb(hex);
	if (!rgb) {
		return null;
	}
	const [okL, okA, okB] = rgbToOklab(rgb);
	return {
		l: okL,
		c: Math.hypot(okA, okB),
		h: ((Math.atan2(okB, okA) * 180) / Math.PI + 360) % 360
	};
}

/** Raw (possibly out-of-gamut) linear-sRGB triple for an OKLCH color. */
function oklchToRgbRaw({ l: okL, c, h }: Oklch): Rgb {
	const rad = (h * Math.PI) / 180;
	const okA = c * Math.cos(rad);
	const okB = c * Math.sin(rad);
	const l = (okL + 0.3963377774 * okA + 0.2158037573 * okB) ** 3;
	const m = (okL - 0.1055613458 * okA - 0.0638541728 * okB) ** 3;
	const s = (okL - 0.0894841775 * okA - 1.291485548 * okB) ** 3;
	return [
		4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
		-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
		-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
	];
}

const inSrgbGamut = (rgb: readonly number[]): boolean => rgb.every(c => c >= -0.001 && c <= 1.001);

/** OKLCH → `#rrggbb`, binary-searching chroma until sRGB fits (hermes
 * oklchToHex): clipping channels would shift hue; reducing chroma keeps it. */
function oklchToHex(color: Oklch): string {
	if (inSrgbGamut(oklchToRgbRaw(color))) {
		return rgbToHex(oklchToRgbRaw(color).map(c => delinearize01(c) * 255) as Rgb);
	}
	let lo = 0;
	let hi = color.c;
	for (let i = 0; i < 24; i += 1) {
		const mid = (lo + hi) / 2;
		if (inSrgbGamut(oklchToRgbRaw({ ...color, c: mid }))) {
			lo = mid;
		} else {
			hi = mid;
		}
	}
	return rgbToHex(oklchToRgbRaw({ ...color, c: lo }).map(c => delinearize01(c) * 255) as Rgb);
}

/** Largest in-gamut chroma for a lightness+hue (hermes maxChroma). */
function maxChroma(l: number, h: number): number {
	let lo = 0;
	let hi = 0.4;
	for (let i = 0; i < 20; i += 1) {
		const mid = (lo + hi) / 2;
		if (inSrgbGamut(oklchToRgbRaw({ l, c: mid, h }))) {
			lo = mid;
		} else {
			hi = mid;
		}
	}
	return lo;
}

/** Signed shortest angular distance -180..180 (hermes hueDelta): hue is a
 * circle, 350° and 10° are 20° apart. */
function hueDelta(from: number, to: number): number {
	return ((to - from + 540) % 360) - 180;
}

/** Bend a semantic color toward the accent along the shortest hue arc
 * (hermes `harmonize`): at strength 0 nothing moves, at 1 it lands on the
 * accent hue. A green accent barely moves its success green; a blue one turns
 * it teal so eight emerald dots stop fighting the theme. */
function harmonize(hex: string, accent: string, strength: number): string {
	const base = hexToOklch(hex);
	const target = hexToOklch(accent);
	if (!base || !target) {
		return hex;
	}
	const h = (base.h + hueDelta(base.h, target.h) * Math.min(1, Math.max(0, strength)) + 360) % 360;
	return oklchToHex({ ...base, c: Math.min(Math.max(base.c, target.c * 0.85), maxChroma(base.l, h)), h });
}

/** Clear `min` contrast by moving OKLCH LIGHTNESS only (hermes
 * ensureContrastOklch): the sRGB version drags chroma down with it and a brand
 * color comes out washed; this keeps hue and chroma intact. */
function ensureContrastOklch(hex: string, bg: string, min: number): string {
	if (contrastRatio(hex, bg) >= min) {
		return hex;
	}
	const lch = hexToOklch(hex);
	if (!lch) {
		return hex;
	}
	const up = relativeLuminance(bg) < 0.5;
	let best = hex;
	for (let step = 1; step <= 40; step += 1) {
		const l = lch.l + (up ? step : -step) * 0.02;
		if (l <= 0 || l >= 1) {
			break;
		}
		best = oklchToHex({ ...lch, l });
		if (contrastRatio(best, bg) >= min) {
			return best;
		}
	}
	return best;
}

// ─── Seed reading (the workbench is the theme file) ─────────────────────────

/**
 * Resolve a `--vscode-*` custom property from the live workbench theme and
 * flatten it to `#rrggbb` over `backdrop`. The workbench publishes opaque
 * colors as hex and translucent ones as `rgba()`; alpha is composited over
 * the backdrop so downstream math is simple — the same contract as hermes'
 * `normalizeHex` front door.
 */
function readSeed(style: CSSStyleDeclaration, names: string[], backdrop: string): string | null {
	for (const name of names) {
		const raw = style.getPropertyValue(name).trim();
		if (!raw) {
			continue;
		}
		const hex = normalizeCssColor(raw, backdrop);
		if (hex) {
			return hex;
		}
	}
	return null;
}

/** `#rgb` / `#rrggbb` / `#rrggbbaa` / `rgb()` / `rgba()` → flat `#rrggbb`. */
function normalizeCssColor(input: string, backdrop: string): string | null {
	const value = input.trim().toLowerCase();
	if (value.startsWith('#')) {
		let clean = value.slice(1);
		if (clean.length === 3 || clean.length === 4) {
			clean = clean.split('').map(ch => ch + ch).join('');
		}
		if (!/^[0-9a-f]{6}([0-9a-f]{2})?$/.test(clean)) {
			return null;
		}
		const rgb = hexToRgb(`#${clean.slice(0, 6)}`);
		if (!rgb) {
			return null;
		}
		if (clean.length === 6) {
			return rgbToHex(rgb);
		}
		const alpha = parseInt(clean.slice(6, 8), 16) / 255;
		const base = hexToRgb(backdrop) ?? [0, 0, 0];
		return rgbToHex([
			base[0] + (rgb[0] - base[0]) * alpha,
			base[1] + (rgb[1] - base[1]) * alpha,
			base[2] + (rgb[2] - base[2]) * alpha
		]);
	}
	const fn = value.match(/^rgba?\(([^)]+)\)$/);
	if (!fn) {
		return null;
	}
	const parts = fn[1].split(/[\s,/]+/).filter(Boolean).slice(0, 4).map(Number);
	if (parts.length < 3 || parts.some(n => Number.isNaN(n))) {
		return null;
	}
	const rgb: Rgb = [parts[0], parts[1], parts[2]];
	const alpha = parts.length > 3 ? parts[3] : 1;
	const base = hexToRgb(backdrop) ?? [0, 0, 0];
	return rgbToHex([
		base[0] + (rgb[0] - base[0]) * alpha,
		base[1] + (rgb[1] - base[1]) * alpha,
		base[2] + (rgb[2] - base[2]) * alpha
	]);
}

// ─── The derivation (hermes themes/vscode.ts seed chain → pulse tokens) ─────

/**
 * Derive the `--pulseai-*` semantic palette from the live workbench theme and
 * write it onto `container`. Returns a disposable that unsubscribes from
 * theme changes. Pure CSS var() fallbacks in media/pulseAI-tokens.css paint
 * the pane natively if this never runs.
 */
export function installPulseTheme(container: HTMLElement, themeService: IThemeService): IDisposable {
	const apply = () => {
		const style = container.ownerDocument.defaultView?.getComputedStyle(container);
		if (!style) {
			return;
		}
		// Background first: every other token is measured against it (hermes
		// vscode.ts picks editor.background before anything else).
		const sidebar = readSeed(style, ['--vscode-sideBar-background'], '#000000')
			?? mix('#1e1e1e', '#d4d4d4', 0.02);
		const background = readSeed(
			style,
			['--vscode-editor-background', '--vscode-editorPane-background', '--vscode-panel-background'],
			'#000000'
		) ?? sidebar;
		const foreground = readSeed(
			style,
			['--vscode-editor-foreground', '--vscode-foreground'],
			background
		) ?? mix(background, relativeLuminance(background) < DARK_LUMINANCE_BUCKET ? WHITE : '#000000', 0.12);

		// Brand accent — hermes' preference chain: saturated brand tokens
		// first, focusBorder late (many themes mute it to gray).
		const accentSource = readSeed(
			style,
			[
				'--vscode-button-background',
				'--vscode-textLink-activeForeground',
				'--vscode-textLink-foreground',
				'--vscode-activityBarBadge-background',
				'--vscode-badge-background',
				'--vscode-progressBar-background',
				'--vscode-list-highlightForeground',
				'--vscode-editorLink-activeForeground',
				'--vscode-focusBorder',
				'--vscode-tab-activeBorder'
			],
			background
		) ?? mix(foreground, background, ACCENT_FALLBACK_MIX);

		// The accent labels the sidebar surface, so it must read there —
		// hermes ACCENT_MIN_CONTRAST (WCAG AA 4.5:1).
		const accent = ensureContrast(accentSource, sidebar, ACCENT_MIN_CONTRAST);

		// Host error seed (hermes destructive chain: editorError/error
		// foregrounds first, constant fallback only when the theme is silent).
		const errorSeed = readSeed(style, ['--vscode-errorForeground'], background) ?? DESTRUCTIVE_FALLBACK;

		// Semantic set: constant hue seeds bent toward the accent (hermes
		// harmonize, strength 0.25), then guaranteed 3:1 (WCAG 1.4.11) against
		// the sidebar they sit on — lightness-only, so the seed keeps its
		// colorfulness.
		const deriveDot = (seed: string): string =>
			ensureContrastOklch(harmonize(seed, accent, HARMONIZE_STRENGTH), sidebar, DOT_MIN_CONTRAST);

		const set = (name: string, value: string): void => container.style.setProperty(name, value);
		set('--pulseai-accent', accent);
		set('--pulseai-running', accent);
		set('--pulseai-verified', deriveDot(SUCCESS_SEED));
		set('--pulseai-approval', deriveDot(APPROVAL_SEED));
		set('--pulseai-failed', deriveDot(errorSeed));
		set('--pulseai-agent', deriveDot(AGENT_SEED));
		container.dataset.pulseaiThemed = 'true';
	};

	apply();
	return themeService.onDidColorThemeChange(() => apply());
}

// Re-exported for tests/pins and future consumers; keeps the hermes names.
export { mix as pulseMix, contrastRatio as pulseContrastRatio, harmonize as pulseHarmonize };
