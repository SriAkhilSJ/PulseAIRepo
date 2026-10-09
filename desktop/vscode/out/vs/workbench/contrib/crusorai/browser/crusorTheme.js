/**
 * Crusor semantic palette — derived, never hardcoded.
 *
 * Port of the hermes desktop theme machine (apps/desktop/src/themes/color.ts
 * and themes/vscode.ts) onto the workbench. Hermes imports VS Code theme JSON
 * and runs a "naive token converter": ~6 seed colors (background, foreground,
 * accent, elevated surface, sidebar, error), everything else mixed from those
 * seeds, with the accent contrast-enforced (WCAG AA 4.5:1) before use because
 * it renders as small labels — the "invisible purple label" case.
 *
 * Crusor's host IS the workbench, so the seeds are free: the workbench already
 * publishes the live theme as `--vscode-*` custom properties and re-publishes
 * them on every theme change. This module reads the seeds from the pane's
 * computed style, derives the `--crusorai-*` semantic outputs with the same
 * math, and writes them onto the pane root. `media/crusorAI-tokens.css` holds
 * only var() fallback chains (theme-native paint before this runs); the hand
 * per-mode hex palette it used to carry is gone.
 *
 * The only color literals in this file are the documented semantic SEEDS (the
 * machine inputs, same shape as hermes' `#10b981` success seed and `#e25563`
 * destructive fallback) and the WCAG contrast anchors. Every value the UI
 * paints is derived at runtime.
 */
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
// ─── Constants (machine inputs, cited) ──────────────────────────────────────
/** Hermes themes/vscode.ts: the accent renders as small labels on the sidebar
 * surface, so it must clear WCAG AA for normal text or it's unreadable. */
var ACCENT_MIN_CONTRAST = 4.5;
/** WCAG 1.4.11 non-text contrast: status dots and the brand glyph are
 * graphical objects carrying state, so 3:1 against their surface. */
var DOT_MIN_CONTRAST = 3;
/** Contrast anchors. WHITE hermes color.ts ensureContrast/harmonize targets
 * and the light-anchor of the pair readableOn() measures; mid-lightness
 * accents broke every luminance threshold, which is why hermes measures. */
var WHITE = '#ffffff';
/** Hermes context.tsx: `--ui-success` = harmonize('#10b981', accent, 0.25).
 * The constant is the SEMANTIC hue seed; the painted value is derived. */
var SUCCESS_SEED = '#10b981';
/** Hermes themes/vscode.ts destructive fallback (used when the host theme
 * ships no error foreground). */
var DESTRUCTIVE_FALLBACK = '#e25563';
/** Crusor approval seed: the "needs your input" amber. Crusor semantic identity,
 * rendered through the same harmonize/contrast machine as the rest. */
var APPROVAL_SEED = '#efb75c';
/** Crusor agent-identity seed: the agent glyph/memory hue. */
var AGENT_SEED = '#9b8cff';
/** Hermes color.ts harmonize(): how far a semantic hue bends toward the
 * accent along the shortest OKLCH arc — settles the palette without erasing
 * the meaning ("done" must never become "running"). */
var HARMONIZE_STRENGTH = 0.25;
/** Hermes vscode.ts seed fallbacks: accent when a theme ships no brand token
 * (mix(foreground, background, 0.55)), and the dark-mode detection bucket. */
var ACCENT_FALLBACK_MIX = 0.55;
var DARK_LUMINANCE_BUCKET = 0.4;
var clamp255 = function (n) { return Math.round(Math.min(255, Math.max(0, n))); };
var rgbToHex = function (_a) {
    var r = _a[0], g = _a[1], b = _a[2];
    return "#".concat([r, g, b].map(function (n) { return clamp255(n).toString(16).padStart(2, '0'); }).join(''));
};
var hexToRgb = function (hex) {
    var clean = hex.trim().replace(/^#/, '');
    if (!/^[0-9a-f]{6}$/i.test(clean)) {
        return null;
    }
    return [0, 2, 4].map(function (i) { return parseInt(clean.slice(i, i + 2), 16); });
};
/** Linear blend of two colors in sRGB — hermes `mix`. Correct for neutrals;
 * accent-derived SURFACE blends wait for P3, where hermes applies its
 * hue-stable mixOklab. */
function mix(a, b, amount) {
    var ar = hexToRgb(a);
    var br = hexToRgb(b);
    if (!ar || !br) {
        return a;
    }
    return rgbToHex([
        ar[0] + (br[0] - ar[0]) * amount,
        ar[1] + (br[1] - ar[1]) * amount,
        ar[2] + (br[2] - ar[2]) * amount
    ]);
}
var linearize = function (channel) {
    return channel <= 0.03928 ? channel / 12.92 : Math.pow(((channel + 0.055) / 1.055), 2.4);
};
/** WCAG relative luminance (gamma-corrected), 0..1 — hermes color.ts. */
function relativeLuminance(hex) {
    var rgb = hexToRgb(hex);
    if (!rgb) {
        return 0;
    }
    var _a = rgb.map(function (v) { return linearize(v / 255); }), r = _a[0], g = _a[1], b = _a[2];
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
/** WCAG contrast ratio (1..21) — hermes color.ts. */
function contrastRatio(a, b) {
    var la = relativeLuminance(a);
    var lb = relativeLuminance(b);
    return la >= lb ? (la + 0.05) / (lb + 0.05) : (lb + 0.05) / (la + 0.05);
}
/** Guarantee `color` reads against `bg`: below `min`, mix toward white on a
 * dark bg (black on light) in 0.2 steps until it clears — hermes
 * `ensureContrast`, which keeps the hue as much as the space allows. */
function ensureContrast(color, bg, min) {
    if (contrastRatio(color, bg) >= min) {
        return color;
    }
    var towards = relativeLuminance(bg) < 0.5 ? WHITE : '#000000';
    var best = color;
    for (var amount = 0.2; amount <= 1.0001; amount += 0.2) {
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
var linearize01 = function (c) { return (c <= 0.04045 ? c / 12.92 : Math.pow(((c + 0.055) / 1.055), 2.4)); };
var delinearize01 = function (c) { return (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, (1 / 2.4)) - 0.055); };
/** 0–255 sRGB triple → OKLab [L, a, b] (hermes rgbToOklab). */
function rgbToOklab(_a) {
    var r255 = _a[0], g255 = _a[1], b255 = _a[2];
    var _b = [r255, g255, b255].map(function (v) { return linearize01(v / 255); }), r = _b[0], g = _b[1], b = _b[2];
    var l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    var m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    var s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
        0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
    ];
}
function hexToOklch(hex) {
    var rgb = hexToRgb(hex);
    if (!rgb) {
        return null;
    }
    var _a = rgbToOklab(rgb), okL = _a[0], okA = _a[1], okB = _a[2];
    return {
        l: okL,
        c: Math.hypot(okA, okB),
        h: ((Math.atan2(okB, okA) * 180) / Math.PI + 360) % 360
    };
}
/** Raw (possibly out-of-gamut) linear-sRGB triple for an OKLCH color. */
function oklchToRgbRaw(_a) {
    var okL = _a.l, c = _a.c, h = _a.h;
    var rad = (h * Math.PI) / 180;
    var okA = c * Math.cos(rad);
    var okB = c * Math.sin(rad);
    var l = Math.pow((okL + 0.3963377774 * okA + 0.2158037573 * okB), 3);
    var m = Math.pow((okL - 0.1055613458 * okA - 0.0638541728 * okB), 3);
    var s = Math.pow((okL - 0.0894841775 * okA - 1.291485548 * okB), 3);
    return [
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
    ];
}
var inSrgbGamut = function (rgb) { return rgb.every(function (c) { return c >= -0.001 && c <= 1.001; }); };
/** OKLCH → `#rrggbb`, binary-searching chroma until sRGB fits (hermes
 * oklchToHex): clipping channels would shift hue; reducing chroma keeps it. */
function oklchToHex(color) {
    if (inSrgbGamut(oklchToRgbRaw(color))) {
        return rgbToHex(oklchToRgbRaw(color).map(function (c) { return delinearize01(c) * 255; }));
    }
    var lo = 0;
    var hi = color.c;
    for (var i = 0; i < 24; i += 1) {
        var mid = (lo + hi) / 2;
        if (inSrgbGamut(oklchToRgbRaw(__assign(__assign({}, color), { c: mid })))) {
            lo = mid;
        }
        else {
            hi = mid;
        }
    }
    return rgbToHex(oklchToRgbRaw(__assign(__assign({}, color), { c: lo })).map(function (c) { return delinearize01(c) * 255; }));
}
/** Largest in-gamut chroma for a lightness+hue (hermes maxChroma). */
function maxChroma(l, h) {
    var lo = 0;
    var hi = 0.4;
    for (var i = 0; i < 20; i += 1) {
        var mid = (lo + hi) / 2;
        if (inSrgbGamut(oklchToRgbRaw({ l: l, c: mid, h: h }))) {
            lo = mid;
        }
        else {
            hi = mid;
        }
    }
    return lo;
}
/** Signed shortest angular distance -180..180 (hermes hueDelta): hue is a
 * circle, 350° and 10° are 20° apart. */
function hueDelta(from, to) {
    return ((to - from + 540) % 360) - 180;
}
/** Bend a semantic color toward the accent along the shortest hue arc
 * (hermes `harmonize`): at strength 0 nothing moves, at 1 it lands on the
 * accent hue. A green accent barely moves its success green; a blue one turns
 * it teal so eight emerald dots stop fighting the theme. */
function harmonize(hex, accent, strength) {
    var base = hexToOklch(hex);
    var target = hexToOklch(accent);
    if (!base || !target) {
        return hex;
    }
    var h = (base.h + hueDelta(base.h, target.h) * Math.min(1, Math.max(0, strength)) + 360) % 360;
    return oklchToHex(__assign(__assign({}, base), { c: Math.min(Math.max(base.c, target.c * 0.85), maxChroma(base.l, h)), h: h }));
}
/** Clear `min` contrast by moving OKLCH LIGHTNESS only (hermes
 * ensureContrastOklch): the sRGB version drags chroma down with it and a brand
 * color comes out washed; this keeps hue and chroma intact. */
function ensureContrastOklch(hex, bg, min) {
    if (contrastRatio(hex, bg) >= min) {
        return hex;
    }
    var lch = hexToOklch(hex);
    if (!lch) {
        return hex;
    }
    var up = relativeLuminance(bg) < 0.5;
    var best = hex;
    for (var step = 1; step <= 40; step += 1) {
        var l = lch.l + (up ? step : -step) * 0.02;
        if (l <= 0 || l >= 1) {
            break;
        }
        best = oklchToHex(__assign(__assign({}, lch), { l: l }));
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
function readSeed(style, names, backdrop) {
    for (var _i = 0, names_1 = names; _i < names_1.length; _i++) {
        var name = names_1[_i];
        var raw = style.getPropertyValue(name).trim();
        if (!raw) {
            continue;
        }
        var hex = normalizeCssColor(raw, backdrop);
        if (hex) {
            return hex;
        }
    }
    return null;
}
/** `#rgb` / `#rrggbb` / `#rrggbbaa` / `rgb()` / `rgba()` → flat `#rrggbb`. */
function normalizeCssColor(input, backdrop) {
    var _a, _b;
    var value = input.trim().toLowerCase();
    if (value.startsWith('#')) {
        var clean = value.slice(1);
        if (clean.length === 3 || clean.length === 4) {
            clean = clean.split('').map(function (ch) { return ch + ch; }).join('');
        }
        if (!/^[0-9a-f]{6}([0-9a-f]{2})?$/.test(clean)) {
            return null;
        }
        var rgb_1 = hexToRgb("#".concat(clean.slice(0, 6)));
        if (!rgb_1) {
            return null;
        }
        if (clean.length === 6) {
            return rgbToHex(rgb_1);
        }
        var alpha_1 = parseInt(clean.slice(6, 8), 16) / 255;
        var base_1 = (_a = hexToRgb(backdrop)) !== null && _a !== void 0 ? _a : [0, 0, 0];
        return rgbToHex([
            base_1[0] + (rgb_1[0] - base_1[0]) * alpha_1,
            base_1[1] + (rgb_1[1] - base_1[1]) * alpha_1,
            base_1[2] + (rgb_1[2] - base_1[2]) * alpha_1
        ]);
    }
    var fn = value.match(/^rgba?\(([^)]+)\)$/);
    if (!fn) {
        return null;
    }
    var parts = fn[1].split(/[\s,/]+/).filter(Boolean).slice(0, 4).map(Number);
    if (parts.length < 3 || parts.some(function (n) { return Number.isNaN(n); })) {
        return null;
    }
    var rgb = [parts[0], parts[1], parts[2]];
    var alpha = parts.length > 3 ? parts[3] : 1;
    var base = (_b = hexToRgb(backdrop)) !== null && _b !== void 0 ? _b : [0, 0, 0];
    return rgbToHex([
        base[0] + (rgb[0] - base[0]) * alpha,
        base[1] + (rgb[1] - base[1]) * alpha,
        base[2] + (rgb[2] - base[2]) * alpha
    ]);
}
// ─── The derivation (hermes themes/vscode.ts seed chain → crusor tokens) ─────
/**
 * Derive the `--crusorai-*` semantic palette from the live workbench theme and
 * write it onto `container`. Returns a disposable that unsubscribes from
 * theme changes. Pure CSS var() fallbacks in media/crusorAI-tokens.css paint
 * the pane natively if this never runs.
 */
export function installCrusorTheme(container, themeService) {
    var apply = function () {
        var _a, _b, _c, _d, _e, _f;
        var style = (_a = container.ownerDocument.defaultView) === null || _a === void 0 ? void 0 : _a.getComputedStyle(container);
        if (!style) {
            return;
        }
        // Background first: every other token is measured against it (hermes
        // vscode.ts picks editor.background before anything else).
        var sidebar = (_b = readSeed(style, ['--vscode-sideBar-background'], '#000000')) !== null && _b !== void 0 ? _b : mix('#1e1e1e', '#d4d4d4', 0.02);
        var background = (_c = readSeed(style, ['--vscode-editor-background', '--vscode-editorPane-background', '--vscode-panel-background'], '#000000')) !== null && _c !== void 0 ? _c : sidebar;
        var foreground = (_d = readSeed(style, ['--vscode-editor-foreground', '--vscode-foreground'], background)) !== null && _d !== void 0 ? _d : mix(background, relativeLuminance(background) < DARK_LUMINANCE_BUCKET ? WHITE : '#000000', 0.12);
        // Brand accent — hermes' preference chain: saturated brand tokens
        // first, focusBorder late (many themes mute it to gray).
        var accentSource = (_e = readSeed(style, [
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
        ], background)) !== null && _e !== void 0 ? _e : mix(foreground, background, ACCENT_FALLBACK_MIX);
        // The accent labels the sidebar surface, so it must read there —
        // hermes ACCENT_MIN_CONTRAST (WCAG AA 4.5:1).
        var accent = ensureContrast(accentSource, sidebar, ACCENT_MIN_CONTRAST);
        // Host error seed (hermes destructive chain: editorError/error
        // foregrounds first, constant fallback only when the theme is silent).
        var errorSeed = (_f = readSeed(style, ['--vscode-errorForeground'], background)) !== null && _f !== void 0 ? _f : DESTRUCTIVE_FALLBACK;
        // Semantic set: constant hue seeds bent toward the accent (hermes
        // harmonize, strength 0.25), then guaranteed 3:1 (WCAG 1.4.11) against
        // the sidebar they sit on — lightness-only, so the seed keeps its
        // colorfulness.
        var deriveDot = function (seed) {
            return ensureContrastOklch(harmonize(seed, accent, HARMONIZE_STRENGTH), sidebar, DOT_MIN_CONTRAST);
        };
        var set = function (name, value) { return container.style.setProperty(name, value); };
        set('--crusorai-accent', accent);
        set('--crusorai-running', accent);
        set('--crusorai-verified', deriveDot(SUCCESS_SEED));
        set('--crusorai-approval', deriveDot(APPROVAL_SEED));
        set('--crusorai-failed', deriveDot(errorSeed));
        set('--crusorai-agent', deriveDot(AGENT_SEED));
        container.dataset.crusoraiThemed = 'true';
    };
    apply();
    return themeService.onDidColorThemeChange(function () { return apply(); });
}
// Re-exported for tests/pins and future consumers; keeps the hermes names.
export { mix as crusorMix, contrastRatio as crusorContrastRatio, harmonize as crusorHarmonize };
