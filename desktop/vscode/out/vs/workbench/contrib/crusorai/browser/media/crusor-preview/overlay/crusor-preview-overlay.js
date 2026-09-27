/*---------------------------------------------------------------------------------------------
 * Crusor Preview — inspect & fix overlay.
 *
 * This file is INJECTED into the page the agent built (a running dev server or a static HTML
 * file the agent wrote). It is deliberately dependency-free classic JS: it must evaluate inside
 * an arbitrary third-party document, in an Electron <iframe>, with no bundler and no module
 * loader, and it must never break the page it lands in.
 *
 * Contract with the host (the Crusor Preview window, media/crusor-preview/preview.js):
 *   overlay -> host : postMessage({ source: 'crusor-preview-overlay', type, ... })
 *   host  -> overlay: postMessage({ source: 'crusor-preview-host', command, ... })
 *
 * Colors are NEVER hardcoded here beyond a last-resort seed chain: every paint reads the
 * `--crusorai-*` tokens the host pushes in (`configure` command), which are the same derived
 * tokens crusorTheme.ts computes from the live workbench theme. Fallback order is
 * --crusorai-* -> --vscode-* -> seed, matching media/crusorAI-tokens.css.
 *--------------------------------------------------------------------------------------------*/
(function (global) {
	'use strict';

	var VERSION = 1;
	var NS = 'http://www.w3.org/2000/svg';
	/** Last-resort seeds only. crusorTheme.ts overrides all of these at runtime. */
	var SEED = {
		accent: '#fab283',
		agent: '#9d7cd8',
		verified: '#7fd88f',
		approval: '#fcd53a',
		failed: '#fc533a',
		surface: '#1f1f1f',
		surfaceRaised: '#282828',
		surfaceStrong: '#2d2d2d',
		text: '#f1ece8',
		textWeak: '#a0a0a0',
		border: '#3c3c3c',
		fontUi: 'system-ui, -apple-system, "Segoe UI", sans-serif',
		fontMono: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
		radius: '6px',
	};

	var STYLE = [
		':host{all:initial}',
		'.cp-root{position:fixed;inset:0;z-index:2147483000;pointer-events:none;',
		'--cp-accent:var(--crusorai-accent,var(--vscode-focusBorder,' + SEED.accent + '));',
		'--cp-agent:var(--crusorai-agent,var(--vscode-symbolKindClass,' + SEED.agent + '));',
		'--cp-verified:var(--crusorai-verified,var(--vscode-testing-iconPassed,' + SEED.verified + '));',
		'--cp-approval:var(--crusorai-approval,var(--vscode-editorWarning-foreground,' + SEED.approval + '));',
		'--cp-failed:var(--crusorai-failed,var(--vscode-errorForeground,' + SEED.failed + '));',
		'--cp-surface:var(--crusorai-preview-surface,var(--vscode-sideBar-background,' + SEED.surface + '));',
		'--cp-surface-raised:var(--crusorai-preview-surface-raised,var(--vscode-editorWidget-background,' + SEED.surfaceRaised + '));',
		'--cp-surface-strong:var(--crusorai-preview-surface-strong,var(--vscode-button-secondaryBackground,' + SEED.surfaceStrong + '));',
		'--cp-text:var(--crusorai-preview-text,var(--vscode-foreground,' + SEED.text + '));',
		'--cp-text-weak:var(--crusorai-preview-text-weak,var(--vscode-descriptionForeground,' + SEED.textWeak + '));',
		'--cp-border:var(--crusorai-preview-border,var(--vscode-widget-border,' + SEED.border + '));',
		'--cp-font-ui:var(--crusorai-font-ui,var(--vscode-font-family,' + SEED.fontUi + '));',
		'--cp-font-mono:var(--crusorai-font-mono,var(--vscode-editor-font-family,' + SEED.fontMono + '));',
		'--cp-radius:var(--crusorai-preview-radius,' + SEED.radius + ');',
		'--cp-track-caps:var(--crusorai-track-caps,0.08em);',
		'}',
		'.cp-canvas{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}',
		/* Hover wireframe: full outline + corner brackets + edge guides = "the wireframe gets fully highlighted". */
		'.cp-hover-box{fill:var(--cp-accent);fill-opacity:.07;stroke:var(--cp-accent);stroke-width:1.5;stroke-dasharray:5 3}',
		'.cp-corner{stroke:var(--cp-accent);stroke-width:2.5;fill:none;stroke-linecap:square}',
		'.cp-guide{stroke:var(--cp-accent);stroke-width:1;stroke-opacity:.45;stroke-dasharray:2 4}',
		'.cp-selected-box{fill:none;stroke:var(--cp-accent);stroke-width:2}',
		'.cp-selected-tick{stroke:var(--cp-accent);stroke-width:2;stroke-linecap:square}',
		'.cp-flash-box{fill:var(--cp-verified);fill-opacity:.16;stroke:var(--cp-verified);stroke-width:2}',
		/* Element label chip riding the top-left corner of the wireframe. */
		'.cp-label{position:absolute;display:none;max-width:min(420px,80vw);padding:2px 6px;',
		'background:var(--cp-surface);border:1px solid var(--cp-border);border-left:2px solid var(--cp-accent);',
		'border-radius:var(--cp-radius);color:var(--cp-text);font:400 11px/1.5 var(--cp-font-ui);',
		'box-shadow:0 4px 14px rgba(0,0,0,.35);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
		'.cp-label.is-on{display:block}',
		'.cp-label-tag{color:var(--cp-accent);font:500 11px/1.5 var(--cp-font-mono)}',
		'.cp-label-cls{color:var(--cp-text-weak);font:400 11px/1.5 var(--cp-font-mono)}',
		'.cp-label-size{color:var(--cp-text-weak);font:400 10px/1.5 var(--cp-font-mono);font-variant-numeric:tabular-nums}',
		/* Numbered pins left on elements that already carry a pending fix. */
		'.cp-pin{cursor:pointer;pointer-events:auto}',
		'.cp-pin circle{fill:var(--cp-accent);stroke:var(--cp-surface);stroke-width:1.5}',
		'.cp-pin text{fill:var(--cp-surface);font:600 10px/1 var(--cp-font-ui);text-anchor:middle;dominant-baseline:central}',
		/* The small input panel anchored on the selected element. */
		'.cp-panel{position:absolute;display:none;width:308px;pointer-events:auto;',
		'background:var(--cp-surface-raised);border:1px solid var(--cp-border);border-radius:var(--cp-radius);',
		'box-shadow:0 16px 48px -6px rgba(0,0,0,.55),0 0 0 1px rgba(0,0,0,.2);',
		'font:400 12px/1.5 var(--cp-font-ui);color:var(--cp-text)}',
		'.cp-panel.is-on{display:block}',
		'.cp-panel-head{display:flex;align-items:center;gap:6px;padding:7px 8px;border-bottom:1px solid var(--cp-border)}',
		'.cp-panel-title{display:flex;align-items:center;gap:5px;font-size:11px;letter-spacing:var(--cp-track-caps);',
		'text-transform:uppercase;color:var(--cp-text-weak)}',
		'.cp-panel-el{margin-left:auto;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
		'font:400 10px/1.6 var(--cp-font-mono);color:var(--cp-accent)}',
		'.cp-icon-btn{display:flex;align-items:center;justify-content:center;width:20px;height:20px;padding:0;',
		'background:transparent;border:0;border-radius:4px;color:var(--cp-text-weak);cursor:pointer}',
		'.cp-icon-btn:hover{background:var(--cp-surface-strong);color:var(--cp-text)}',
		'.cp-panel svg{display:block}',
		'.cp-input{display:block;box-sizing:border-box;width:100%;min-height:58px;max-height:180px;margin:0;padding:8px;',
		'resize:vertical;background:var(--cp-surface);color:var(--cp-text);border:1px solid var(--cp-border);',
		'border-radius:calc(var(--cp-radius) - 2px);font:400 12px/1.5 var(--cp-font-ui);outline:none}',
		'.cp-input:focus{border-color:var(--cp-accent)}',
		'.cp-input::placeholder{color:var(--cp-text-weak)}',
		'.cp-body{padding:8px;display:flex;flex-direction:column;gap:8px}',
		'.cp-chips{display:flex;flex-wrap:wrap;gap:4px}',
		'.cp-chip{padding:2px 7px;background:var(--cp-surface);border:1px solid var(--cp-border);',
		'border-radius:999px;color:var(--cp-text-weak);font:400 10.5px/1.6 var(--cp-font-ui);cursor:pointer}',
		'.cp-chip:hover{border-color:var(--cp-accent);color:var(--cp-text)}',
		'.cp-foot{display:flex;align-items:center;gap:6px;padding:0 8px 8px}',
		'.cp-hint{margin-right:auto;color:var(--cp-text-weak);font-size:10px;font-variant-numeric:tabular-nums}',
		'.cp-btn{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:calc(var(--cp-radius) - 2px);',
		'border:1px solid var(--cp-border);background:var(--cp-surface-strong);color:var(--cp-text);',
		'font:500 11.5px/1.6 var(--cp-font-ui);cursor:pointer}',
		'.cp-btn:hover{border-color:var(--cp-accent)}',
		'.cp-btn-primary{background:var(--cp-accent);border-color:var(--cp-accent);color:var(--cp-surface)}',
		'.cp-btn-primary:hover{filter:brightness(1.08)}',
		'.cp-btn[disabled]{opacity:.45;cursor:default;filter:none}',
		'.cp-toast{position:absolute;left:50%;bottom:20px;transform:translate(-50%,8px);display:none;align-items:center;gap:7px;',
		'padding:6px 12px;background:var(--cp-surface-raised);border:1px solid var(--cp-border);',
		'border-left:2px solid var(--cp-verified);border-radius:var(--cp-radius);color:var(--cp-text);',
		'font:400 11.5px/1.5 var(--cp-font-ui);box-shadow:0 8px 24px rgba(0,0,0,.4);pointer-events:none;opacity:0;',
		'transition:opacity .16s ease,transform .16s ease}',
		'.cp-toast.is-on{display:flex;opacity:1;transform:translate(-50%,0)}',
		/* Banner shown while inspect mode is armed, so the page never silently eats clicks. */
		'.cp-armed{position:absolute;left:50%;top:12px;transform:translateX(-50%);display:none;align-items:center;gap:7px;',
		'padding:4px 10px;background:var(--cp-surface);border:1px solid var(--cp-border);border-radius:999px;',
		'color:var(--cp-text-weak);font:400 10.5px/1.6 var(--cp-font-ui);letter-spacing:var(--cp-track-caps);',
		'text-transform:uppercase;pointer-events:none}',
		'.cp-armed.is-on{display:flex}',
		'.cp-dot{width:6px;height:6px;border-radius:50%;background:var(--cp-accent)}',
	].join('\n');

	/* --- inline SVG icons (20x20 grid, currentColor, square caps — the Crusor icon grammar) --- */
	var ICONS = {
		edit: '<path d="M17.08 17.08V17.58H17.58V17.08H17.08ZM2.92 17.08H2.42V17.58H2.92V17.08ZM9.58 3.42H10.08V2.42H9.58V3.42ZM17.58 10.42V9.92H16.58V10.42H17.58ZM10.42 7.08H9.92V9.58H12.92V9.08H10.42V7.08ZM10.42 7.08 15.42 2.08 17.92 4.58 12.92 9.58" stroke="currentColor" stroke-linecap="square" fill="none"/>',
		close: '<path d="M3.75 3.75 16.25 16.25M16.25 3.75 3.75 16.25" stroke="currentColor" stroke-linecap="square"/>',
		check: '<path d="M6.5 11.44 8.97 13.5 13.5 6.5" stroke="currentColor" stroke-linecap="square" fill="none"/>',
		target: '<path d="M10 2.5V5M10 15V17.5M2.5 10H5M15 10H17.5" stroke="currentColor" stroke-linecap="square"/><rect x="5" y="5" width="10" height="10" stroke="currentColor" fill="none" stroke-linecap="square"/>',
	};

	function svg(name, size) {
		var px = size || 14;
		return '<svg width="' + px + '" height="' + px + '" viewBox="0 0 20 20" fill="none" aria-hidden="true">' +
			(ICONS[name] || '') + '</svg>';
	}

	/* ------------------------------------------------------------------ *
	 * Element description — the payload that makes a click actionable.
	 * Pure functions, exported for tests (see src/tests/test_preview_*).
	 * ------------------------------------------------------------------ */

	var IGNORED_ANCESTORS = ['HTML', 'BODY'];

	function isVisible(el) {
		if (!el || el.nodeType !== 1) { return false; }
		var r = el.getBoundingClientRect();
		if (r.width <= 0 && r.height <= 0) { return false; }
		var s = global.getComputedStyle(el);
		return s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.01;
	}

	/** CSS.escape with a fallback for exotic identifiers. */
	function esc(value) {
		if (global.CSS && typeof global.CSS.escape === 'function') { return global.CSS.escape(value); }
		return String(value).replace(/[^a-zA-Z0-9_-]/g, function (c) { return '\\' + c; });
	}

	/**
	 * Shortest selector that uniquely resolves to `el` in this document.
	 * Preference order: id -> data-testid/test id -> tag+classes -> structural path.
	 */
	function buildSelector(el) {
		if (!el || el.nodeType !== 1) { return ''; }
		if (el.id) {
			try { if (global.document.querySelectorAll('#' + esc(el.id)).length === 1) { return '#' + esc(el.id); } } catch (_) { /* fall through */ }
		}
		var testId = el.getAttribute && (el.getAttribute('data-testid') || el.getAttribute('data-test-id') || el.getAttribute('data-qa'));
		if (testId) {
			var attr = el.hasAttribute('data-testid') ? 'data-testid' : (el.hasAttribute('data-test-id') ? 'data-test-id' : 'data-qa');
			var byTest = '[' + attr + '="' + testId.replace(/"/g, '\\"') + '"]';
			try { if (global.document.querySelectorAll(byTest).length === 1) { return byTest; } } catch (_) { /* fall through */ }
		}
		// Structural path, walking up until the prefix is unique on its own.
		var parts = [];
		var node = el;
		var guard = 0;
		while (node && node.nodeType === 1 && IGNORED_ANCESTORS.indexOf(node.tagName) === -1 && guard++ < 8) {
			var piece = node.tagName.toLowerCase();
			if (node.id) {
				parts.unshift('#' + esc(node.id));
				break;
			}
			var classes = (node.getAttribute('class') || '').trim().split(/\s+/).filter(isMeaningfulClass);
			if (classes.length) { piece += '.' + classes.slice(0, 2).map(esc).join('.'); }
			var parent = node.parentElement;
			if (parent) {
				var siblings = Array.prototype.filter.call(parent.children, function (c) { return c.tagName === node.tagName; });
				if (siblings.length > 1) { piece += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')'; }
			}
			parts.unshift(piece);
			var candidate = parts.join(' > ');
			try { if (global.document.querySelectorAll(candidate).length === 1) { return candidate; } } catch (_) { /* keep walking */ }
			node = parent;
		}
		return parts.join(' > ');
	}

	/** Tailwind/utility noise and framework internals make selectors brittle; drop them. */
	function isMeaningfulClass(c) {
		if (!c) { return false; }
		if (/^(?:css-|sc-|jsx-|svelte-|v-|_)[A-Za-z0-9]/.test(c)) { return false; }
		if (/[:[\]().,#%]/.test(c)) { return false; }
		if (c.length > 40) { return false; }
		return true;
	}

	function buildXPath(el) {
		var parts = [];
		var node = el;
		var guard = 0;
		while (node && node.nodeType === 1 && guard++ < 12) {
			var idx = 1;
			var sib = node.previousElementSibling;
			while (sib) { if (sib.tagName === node.tagName) { idx++; } sib = sib.previousElementSibling; }
			parts.unshift(node.tagName.toLowerCase() + '[' + idx + ']');
			node = node.parentElement;
		}
		return '/' + parts.join('/');
	}

	var STYLE_KEYS = [
		'display', 'position', 'width', 'height', 'min-width', 'max-width', 'min-height', 'max-height',
		'margin', 'padding', 'color', 'background-color', 'background-image', 'font-family', 'font-size',
		'font-weight', 'line-height', 'letter-spacing', 'text-align', 'text-transform', 'border',
		'border-radius', 'box-shadow', 'opacity', 'flex-direction', 'justify-content', 'align-items',
		'gap', 'grid-template-columns', 'z-index', 'overflow',
	];

	function collectStyles(el) {
		var out = {};
		var cs = global.getComputedStyle(el);
		for (var i = 0; i < STYLE_KEYS.length; i++) {
			var key = STYLE_KEYS[i];
			var value = cs.getPropertyValue(key);
			if (value && value !== 'none' && value !== 'normal' && value !== 'auto' && value !== '0px') {
				out[key] = String(value).trim();
			}
		}
		return out;
	}

	function textOf(el) {
		var raw = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
		return raw.length > 220 ? raw.slice(0, 217) + '…' : raw;
	}

	function outerHtmlOf(el) {
		var html = '';
		try { html = el.outerHTML || ''; } catch (_) { html = ''; }
		html = html.replace(/\s+/g, ' ');
		return html.length > 1600 ? html.slice(0, 1597) + '…' : html;
	}

	var FINGERPRINT_ATTRS = ['data-testid', 'data-test-id', 'data-qa', 'data-cy', 'aria-label', 'name', 'href', 'src', 'alt', 'placeholder', 'title', 'role', 'type', 'id'];

	/**
	 * Grep-able fingerprints: the tokens most likely to appear verbatim in the source file that
	 * produced this element. This is what lets the agent locate the exact component without a
	 * build plugin stamping source positions into the DOM.
	 */
	function fingerprint(el) {
		var out = { classes: [], attrs: [], text: '', tag: el.tagName.toLowerCase() };
		var classes = (el.getAttribute('class') || '').trim().split(/\s+/).filter(isMeaningfulClass);
		out.classes = classes.slice(0, 8);
		for (var i = 0; i < FINGERPRINT_ATTRS.length; i++) {
			var name = FINGERPRINT_ATTRS[i];
			var value = el.getAttribute && el.getAttribute(name);
			if (value && value.length <= 120) { out.attrs.push({ name: name, value: value }); }
		}
		var text = textOf(el);
		out.text = text.length > 80 ? text.slice(0, 80) : text;
		// Precise mapping when the project opts in (any of the common stamping conventions).
		var stamped = el.closest('[data-crusor-source],[data-source],[data-src-file]');
		if (stamped) {
			out.source = {
				file: stamped.getAttribute('data-crusor-source') || stamped.getAttribute('data-source') || stamped.getAttribute('data-src-file'),
				line: Number(stamped.getAttribute('data-crusor-line') || stamped.getAttribute('data-line') || 0) || undefined,
				component: stamped.getAttribute('data-crusor-component') || stamped.getAttribute('data-component') || undefined,
			};
		}
		return out;
	}

	function describeElement(el, pageUrl) {
		var rect = el.getBoundingClientRect();
		return {
			selector: buildSelector(el),
			xpath: buildXPath(el),
			tag: el.tagName.toLowerCase(),
			id: el.id || undefined,
			classes: (el.getAttribute('class') || '').trim().split(/\s+/).filter(isMeaningfulClass),
			text: textOf(el),
			outerHtml: outerHtmlOf(el),
			styles: collectStyles(el),
			fingerprint: fingerprint(el),
			rect: {
				x: Math.round(rect.left), y: Math.round(rect.top),
				width: Math.round(rect.width), height: Math.round(rect.height),
			},
			pageUrl: pageUrl || global.location.href,
			viewport: { width: global.innerWidth, height: global.innerHeight, dpr: global.devicePixelRatio || 1 },
			scroll: { x: Math.round(global.scrollX), y: Math.round(global.scrollY) },
		};
	}

	/** One-line human label for the selected element, used in the tray and the review sheet. */
	function elementLabel(el) {
		var tag = el.tagName.toLowerCase();
		var classes = (el.getAttribute('class') || '').trim().split(/\s+/).filter(isMeaningfulClass);
		var text = textOf(el);
		var what = text ? '"' + (text.length > 28 ? text.slice(0, 27) + '…' : text) + '"' : (classes[0] ? '.' + classes[0] : '');
		return tag + (what ? ' ' + what : '');
	}

	/* ------------------------------------------------------------------ *
	 * Overlay runtime
	 * ------------------------------------------------------------------ */

	var QUICK_FIXES = ['Make it bigger', 'Make it smaller', 'Center it', 'Round the corners', 'More spacing', 'Bolder text'];

	function Overlay() {
		this.host = null;
		this.inspecting = false;
		this.hoverEl = null;
		this.selectedEl = null;
		this.pins = [];
		this.fixCount = 0;
		this.theme = {};
		this.mounted = false;
		this._raf = 0;
		this._toastTimer = 0;
	}

	Overlay.prototype.emit = function (type, payload) {
		var message = { source: 'crusor-preview-overlay', version: VERSION, type: type };
		if (payload) { for (var k in payload) { if (Object.prototype.hasOwnProperty.call(payload, k)) { message[k] = payload[k]; } } }
		try {
			if (global.parent && global.parent !== global) { global.parent.postMessage(message, '*'); }
			global.postMessage(message, '*');
		} catch (_) { /* host gone; nothing to do */ }
	};

	Overlay.prototype.mount = function () {
		if (this.mounted || !global.document || !global.document.documentElement) { return; }
		var host = global.document.createElement('div');
		host.id = 'crusor-preview-overlay-host';
		host.style.cssText = 'position:fixed;inset:0;z-index:2147483000;pointer-events:none;all:initial;';
		var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
		var style = global.document.createElement('style');
		style.textContent = STYLE;
		root.appendChild(style);

		var wrap = global.document.createElement('div');
		wrap.className = 'cp-root';
		wrap.innerHTML = [
			'<svg class="cp-canvas" aria-hidden="true">',
			'<g class="cp-hover-layer"></g><g class="cp-selected-layer"></g><g class="cp-flash-layer"></g><g class="cp-pin-layer"></g>',
			'</svg>',
			'<div class="cp-armed"><span class="cp-dot"></span><span>Inspect — click any element</span></div>',
			'<div class="cp-label" role="status"></div>',
			'<div class="cp-panel" role="dialog" aria-label="Edit this element"></div>',
			'<div class="cp-toast" role="status"></div>',
		].join('');
		root.appendChild(wrap);
		(global.document.documentElement || global.document.body).appendChild(host);

		this.hostEl = host;
		this.root = root;
		this.wrap = wrap;
		this.canvas = wrap.querySelector('.cp-canvas');
		this.hoverLayer = wrap.querySelector('.cp-hover-layer');
		this.selectedLayer = wrap.querySelector('.cp-selected-layer');
		this.flashLayer = wrap.querySelector('.cp-flash-layer');
		this.pinLayer = wrap.querySelector('.cp-pin-layer');
		this.label = wrap.querySelector('.cp-label');
		this.panel = wrap.querySelector('.cp-panel');
		this.toast = wrap.querySelector('.cp-toast');
		this.armed = wrap.querySelector('.cp-armed');
		this.mounted = true;
		this.bind();
	};

	Overlay.prototype.bind = function () {
		var self = this;
		var doc = global.document;

		this._onMove = function (event) {
			if (!self.inspecting || self.panelOpen) { return; }
			var el = self.elementAt(event.clientX, event.clientY);
			if (el === self.hoverEl) { return; }
			self.hoverEl = el;
			self.schedule(function () { self.paintHover(); });
		};
		this._onClick = function (event) {
			if (!self.inspecting) { return; }
			// Clicks inside our own panel are ours; everything else is a selection.
			if (self.panelOpen && self.panel.contains(event.target)) { return; }
			var el = self.elementAt(event.clientX, event.clientY);
			if (!el) { return; }
			event.preventDefault();
			event.stopPropagation();
			self.select(el);
		};
		this._onKey = function (event) {
			if (event.key === 'Escape') {
				if (self.panelOpen) { self.closePanel(); event.preventDefault(); event.stopPropagation(); }
				else if (self.inspecting) { self.setInspecting(false); event.preventDefault(); }
			}
			if ((event.key === 'Enter' || event.key === 'Return') && self.panelOpen && (event.metaKey || event.ctrlKey)) {
				self.submitFix();
				event.preventDefault();
			}
		};
		this._onScroll = function () { self.schedule(function () { self.paintHover(); self.paintSelected(); self.paintPins(); }); };
		this._onResize = this._onScroll;
		this._onMessage = function (event) {
			var data = event && event.data;
			if (!data || data.source !== 'crusor-preview-host') { return; }
			self.command(data.command, data);
		};

		doc.addEventListener('mousemove', this._onMove, true);
		doc.addEventListener('click', this._onClick, true);
		doc.addEventListener('keydown', this._onKey, true);
		global.addEventListener('scroll', this._onScroll, true);
		global.addEventListener('resize', this._onResize, true);
		global.addEventListener('message', this._onMessage, false);
	};

	Overlay.prototype.schedule = function (fn) {
		var self = this;
		if (this._raf) { global.cancelAnimationFrame(this._raf); }
		this._raf = global.requestAnimationFrame(function () { self._raf = 0; fn(); });
	};

	/** elementFromPoint, but never our own overlay (the shadow host is pointer-events:none anyway). */
	Overlay.prototype.elementAt = function (x, y) {
		var el = global.document.elementFromPoint(x, y);
		while (el && el !== global.document.documentElement) {
			if (el.id === 'crusor-preview-overlay-host') { return null; }
			if (isVisible(el) && el.tagName !== 'HTML' && el.tagName !== 'BODY') { return el; }
			el = el.parentElement;
		}
		return null;
	};

	Overlay.prototype.command = function (command, data) {
		switch (command) {
			case 'configure':
				this.theme = data.theme || {};
				this.applyTheme();
				this.mount();
				this.emit('ready', {
					url: global.location ? global.location.href : '',
					title: global.document ? global.document.title : '',
					version: VERSION,
				});
				break;
			case 'inspect':
				this.setInspecting(!!data.on);
				break;
			case 'pins':
				this.pins = data.pins || [];
				this.paintPins();
				break;
			case 'clear-pins':
				this.pins = [];
				this.paintPins();
				break;
			case 'flash':
				this.flash(data.selector);
				break;
			case 'close-panel':
				this.closePanel();
				break;
			default:
				break;
		}
	};

	Overlay.prototype.applyTheme = function () {
		if (!this.mounted || !this.theme) { return; }
		var map = {
			'--crusorai-accent': 'accent', '--crusorai-agent': 'agent', '--crusorai-verified': 'verified',
			'--crusorai-approval': 'approval', '--crusorai-failed': 'failed',
			'--crusorai-preview-surface': 'surface', '--crusorai-preview-surface-raised': 'surfaceRaised',
			'--crusorai-preview-surface-strong': 'surfaceStrong', '--crusorai-preview-text': 'text',
			'--crusorai-preview-text-weak': 'textWeak', '--crusorai-preview-border': 'border',
			'--crusorai-font-ui': 'fontUi', '--crusorai-font-mono': 'fontMono',
			'--crusorai-preview-radius': 'radius',
		};
		for (var name in map) {
			if (!Object.prototype.hasOwnProperty.call(map, name)) { continue; }
			var value = this.theme[map[name]];
			if (value) { this.wrap.style.setProperty(name, value); }
		}
	};

	Overlay.prototype.setInspecting = function (on) {
		this.inspecting = !!on;
		this.mount();
		this.armed.classList.toggle('is-on', this.inspecting);
		this.hostEl.style.pointerEvents = this.inspecting ? 'auto' : 'none';
		this.wrap.style.cursor = this.inspecting ? 'crosshair' : '';
		global.document.documentElement.style.cursor = this.inspecting ? 'crosshair' : '';
		if (!this.inspecting) {
			this.hoverEl = null;
			this.hoverLayer.textContent = '';
			this.label.classList.remove('is-on');
			this.closePanel();
			this.selectedLayer.textContent = '';
		}
		this.emit('inspect', { on: this.inspecting });
	};

	function el(tagName, attrs, parent) {
		var node = global.document.createElementNS(NS, tagName);
		for (var k in attrs) { if (Object.prototype.hasOwnProperty.call(attrs, k)) { node.setAttribute(k, attrs[k]); } }
		if (parent) { parent.appendChild(node); }
		return node;
	}

	function rectOf(target) { return target.getBoundingClientRect(); }

	/* ------------------------------------------------------------------ *
	 * Contrast-enforced paint (port of crusorTheme.ts, browser-side).
	 *
	 * The derived accent is a mid grey in CrusorAI Dark, and the page under it
	 * can be anything the agent built — a white landing page or a black
	 * dashboard. WCAG 1.4.11 wants 3:1 for a graphical object against its
	 * background, so the wireframe color is MEASURED against the element it
	 * frames and lightened/darkened until it clears. Same math, same reason:
	 * an invisible outline is the whole feature failing silently.
	 * ------------------------------------------------------------------ */

	function parseColor(value) {
		if (!value) { return null; }
		var text = String(value).trim();
		var rgb = text.match(/^rgba?\(([^)]+)\)$/i);
		if (rgb) {
			var parts = rgb[1].split(/[\s,/]+/).filter(Boolean);
			var alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
			return { r: Number(parts[0]), g: Number(parts[1]), b: Number(parts[2]), a: isNaN(alpha) ? 1 : alpha };
		}
		var hex = text.match(/^#([0-9a-f]{3,8})$/i);
		if (hex) {
			var h = hex[1];
			if (h.length === 3 || h.length === 4) {
				h = h.split('').map(function (c) { return c + c; }).join('');
			}
			return {
				r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16),
				a: h.length >= 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1,
			};
		}
		return null;
	}

	function channel(component) {
		var c = component / 255;
		return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
	}

	function luminance(color) {
		return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
	}

	function contrastRatio(a, b) {
		var la = luminance(a);
		var lb = luminance(b);
		var light = Math.max(la, lb);
		var dark = Math.min(la, lb);
		return (light + 0.05) / (dark + 0.05);
	}

	function toCss(color) {
		return 'rgb(' + Math.round(color.r) + ',' + Math.round(color.g) + ',' + Math.round(color.b) + ')';
	}

	function mixToward(color, target, amount) {
		return {
			r: color.r + (target.r - color.r) * amount,
			g: color.g + (target.g - color.g) * amount,
			b: color.b + (target.b - color.b) * amount,
			a: 1,
		};
	}

	/** Lightness-only steps toward white or black until `min` contrast is cleared. */
	function ensureContrast(hex, background, min) {
		var base = parseColor(hex) || { r: 122, g: 122, b: 122, a: 1 };
		if (contrastRatio(base, background) >= min) { return base; }
		var toward = luminance(background) < 0.4 ? { r: 255, g: 255, b: 255 } : { r: 0, g: 0, b: 0 };
		var best = base;
		for (var step = 1; step <= 20; step++) {
			var candidate = mixToward(base, toward, step / 20);
			if (contrastRatio(candidate, background) >= min) { return candidate; }
			best = candidate;
		}
		return best;
	}

	/** The first non-transparent background painted behind `target` (canvas white if none). */
	function backdropOf(target) {
		var node = target;
		var guard = 0;
		while (node && node.nodeType === 1 && guard++ < 24) {
			var raw = global.getComputedStyle(node).backgroundColor;
			var color = parseColor(raw);
			if (color && color.a > 0.6) { return color; }
			node = node.parentElement;
		}
		return { r: 255, g: 255, b: 255, a: 1 };
	}

	/** The wireframe color for one element: the derived accent, contrast-enforced. */
	Overlay.prototype.wireColor = function (target) {
		return this.semanticColor('accent', target);
	};

	/**
	 * Any Crusor semantic color, measured against the element it annotates.
	 * Reads the token the host pushed (--cp-*), else the documented seed, and
	 * clears 3:1 (WCAG 1.4.11) so a state color can never vanish into the page.
	 */
	Overlay.prototype.semanticColor = function (token, target) {
		var seeds = {
			accent: '#7a7a7a', agent: '#9b8cff', verified: '#3fd68a',
			approval: '#efb75c', failed: '#e25563',
		};
		var value = seeds[token] || seeds.accent;
		if (this.mounted) {
			var resolved = global.getComputedStyle(this.wrap).getPropertyValue('--cp-' + token);
			if (resolved && resolved.trim()) { value = resolved.trim(); }
		}
		var backdrop = target && target.nodeType === 1 ? backdropOf(target) : { r: 255, g: 255, b: 255, a: 1 };
		return ensureContrast(value, backdrop, 3);
	};

	/** Black or white, whichever reads on `color` (for text inside a filled dot). */
	function readableOn(color) {
		return luminance(color) > 0.42 ? 'rgb(20,20,20)' : 'rgb(250,250,250)';
	}

	/** Corner brackets: the "fully wired" look — four L-shaped brackets hugging the box. */
	function paintCorners(layer, r, cls, len, stroke) {
		var L = Math.min(len || 12, Math.max(4, Math.min(r.width, r.height) / 3));
		var corners = [
			[[r.left, r.top + L], [r.left, r.top], [r.left + L, r.top]],
			[[r.right - L, r.top], [r.right, r.top], [r.right, r.top + L]],
			[[r.right, r.bottom - L], [r.right, r.bottom], [r.right - L, r.bottom]],
			[[r.left + L, r.bottom], [r.left, r.bottom], [r.left, r.bottom - L]],
		];
		corners.forEach(function (c) {
			var attrs = { class: cls, points: c.map(function (p) { return p[0] + ',' + p[1]; }).join(' ') };
			if (stroke) { attrs.stroke = stroke; }
			el('polyline', attrs, layer);
		});
	}

	Overlay.prototype.paintHover = function () {
		if (!this.mounted) { return; }
		this.hoverLayer.textContent = '';
		if (!this.inspecting || !this.hoverEl || !global.document.contains(this.hoverEl)) {
			this.label.classList.remove('is-on');
			return;
		}
		var r = rectOf(this.hoverEl);
		if (r.width < 2 || r.height < 2) { this.label.classList.remove('is-on'); return; }
		var wire = toCss(this.wireColor(this.hoverEl));
		var strokeAttrs = { stroke: wire };
		// Edge guides make the extent readable even for zero-height flex rows.
		el('line', Object.assign({ class: 'cp-guide', x1: 0, y1: r.top, x2: global.innerWidth, y2: r.top }, strokeAttrs), this.hoverLayer);
		el('line', Object.assign({ class: 'cp-guide', x1: 0, y1: r.bottom, x2: global.innerWidth, y2: r.bottom }, strokeAttrs), this.hoverLayer);
		el('line', Object.assign({ class: 'cp-guide', x1: r.left, y1: 0, x2: r.left, y2: global.innerHeight }, strokeAttrs), this.hoverLayer);
		el('line', Object.assign({ class: 'cp-guide', x1: r.right, y1: 0, x2: r.right, y2: global.innerHeight }, strokeAttrs), this.hoverLayer);
		el('rect', Object.assign({
			class: 'cp-hover-box', x: r.left, y: r.top, width: r.width, height: r.height, rx: 2,
			fill: wire, 'fill-opacity': '.08',
		}, strokeAttrs), this.hoverLayer);
		paintCorners(this.hoverLayer, r, 'cp-corner', 12, wire);
		this.paintLabel(this.hoverEl, r, wire);
	};

	Overlay.prototype.paintLabel = function (target, r, wire) {
		var classes = (target.getAttribute('class') || '').trim().split(/\s+/).filter(isMeaningfulClass);
		var cls = classes.length ? '.' + classes.slice(0, 2).join('.') : '';
		this.label.innerHTML =
			'<span class="cp-label-tag">' + target.tagName.toLowerCase() + '</span>' +
			(cls ? '<span class="cp-label-cls"> ' + escapeHtml(cls) + '</span>' : '') +
			'<span class="cp-label-size">  ' + Math.round(r.width) + '×' + Math.round(r.height) + '</span>';
		this.label.style.borderLeftColor = wire || '';
		var tag = this.label.querySelector('.cp-label-tag');
		if (tag && wire) { tag.style.color = wire; }
		var above = r.top - 24 < 4;
		this.label.style.left = clamp(r.left, 4, global.innerWidth - 200) + 'px';
		this.label.style.top = (above ? r.bottom + 4 : r.top - 22) + 'px';
		this.label.classList.add('is-on');
	};

	Overlay.prototype.paintSelected = function () {
		if (!this.mounted) { return; }
		this.selectedLayer.textContent = '';
		if (!this.selectedEl || !global.document.contains(this.selectedEl)) { return; }
		var r = rectOf(this.selectedEl);
		var wire = toCss(this.wireColor(this.selectedEl));
		el('rect', {
			class: 'cp-selected-box', x: r.left, y: r.top, width: r.width, height: r.height, rx: 2, stroke: wire,
		}, this.selectedLayer);
		// Midpoint ticks: reads as measurement, not decoration.
		el('line', { class: 'cp-selected-tick', stroke: wire, x1: r.left + r.width / 2 - 4, y1: r.top, x2: r.left + r.width / 2 + 4, y2: r.top }, this.selectedLayer);
		el('line', { class: 'cp-selected-tick', stroke: wire, x1: r.left + r.width / 2 - 4, y1: r.bottom, x2: r.left + r.width / 2 + 4, y2: r.bottom }, this.selectedLayer);
		if (this.panelOpen) { this.placePanel(r); }
	};

	Overlay.prototype.paintPins = function () {
		if (!this.mounted) { return; }
		this.pinLayer.textContent = '';
		var self = this;
		(this.pins || []).forEach(function (pin, index) {
			var target = pin.selector ? safeQuery(pin.selector) : null;
			if (!target) { return; }
			var r = rectOf(target);
			if (r.width <= 0 && r.height <= 0) { return; }
			var g = el('g', { class: 'cp-pin', role: 'button', 'aria-label': 'Pending fix ' + (index + 1) }, self.pinLayer);
			// Pins are Crusor-authored annotations, so they wear the agent hue, not the accent.
			var pin = self.semanticColor('agent', target);
			el('circle', { cx: r.right - 9, cy: r.top + 9, r: 9, fill: toCss(pin) }, g);
			var text = el('text', { x: r.right - 9, y: r.top + 9.5, fill: readableOn(pin) }, g);
			text.textContent = String(index + 1);
			g.addEventListener('click', function (event) {
				event.preventDefault();
				event.stopPropagation();
				self.emit('pin-click', { index: index, id: pin.id, selector: pin.selector });
			});
		});
	};

	function safeQuery(selector) {
		try { return global.document.querySelector(selector); } catch (_) { return null; }
	}

	Overlay.prototype.select = function (target) {
		this.mount();
		this.selectedEl = target;
		this.paintSelected();
		this.openPanel(target);
		this.emit('selected', { element: describeElement(target), label: elementLabel(target) });
	};

	Overlay.prototype.openPanel = function (target) {
		var self = this;
		this.panelOpen = true;
		this.panel.innerHTML = [
			'<div class="cp-panel-head">',
			'<span class="cp-panel-title">' + svg('edit', 12) + '<span>Edit element</span></span>',
			'<span class="cp-panel-el" title="' + escapeHtml(buildSelector(target)) + '">' + escapeHtml(elementLabel(target)) + '</span>',
			'<button class="cp-icon-btn" type="button" data-act="close" aria-label="Close">' + svg('close', 12) + '</button>',
			'</div>',
			'<div class="cp-body">',
			'<textarea class="cp-input" rows="2" placeholder="Describe the fix — e.g. make this rounded, blue and bigger"></textarea>',
			'<div class="cp-chips">' + QUICK_FIXES.map(function (q, i) {
				return '<button class="cp-chip" type="button" data-quick="' + i + '">' + escapeHtml(q) + '</button>';
			}).join('') + '</div>',
			'</div>',
			'<div class="cp-foot">',
			'<span class="cp-hint">Enter to add · Esc to close</span>',
			'<button class="cp-btn" type="button" data-act="cancel">Cancel</button>',
			'<button class="cp-btn cp-btn-primary" type="button" data-act="add" disabled>' + svg('check', 12) + '<span>Add fix</span></button>',
			'</div>',
		].join('');

		var input = this.panel.querySelector('.cp-input');
		var addBtn = this.panel.querySelector('[data-act="add"]');
		this.panelInput = input;

		input.addEventListener('input', function () { addBtn.disabled = input.value.trim().length === 0; });
		input.addEventListener('keydown', function (event) {
			event.stopPropagation();
			if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); self.submitFix(); }
			if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); self.closePanel(); }
		});
		this.panel.addEventListener('click', function (event) {
			event.stopPropagation();
			var button = event.target.closest ? event.target.closest('button') : null;
			if (!button) { return; }
			var act = button.getAttribute('data-act');
			var quick = button.getAttribute('data-quick');
			if (act === 'close' || act === 'cancel') { self.closePanel(); return; }
			if (act === 'add') { self.submitFix(); return; }
			if (quick !== null) {
				var value = QUICK_FIXES[Number(quick)];
				input.value = input.value.trim() ? input.value.trim().replace(/[,;]\s*$/, '') + ', ' + value.toLowerCase() : value;
				addBtn.disabled = false;
				input.focus();
			}
		});
		this.panel.addEventListener('mousemove', function (event) { event.stopPropagation(); });

		this.placePanel(rectOf(target));
		this.panel.classList.add('is-on');
		// Focus after layout so the page's own focus traps don't steal it back.
		global.setTimeout(function () { try { input.focus(); } catch (_) { /* ignore */ } }, 0);
	};

	Overlay.prototype.placePanel = function (r) {
		var w = 308;
		var panelHeight = this.panel.offsetHeight || 168;
		var gap = 8;
		var left = clamp(r.left, gap, Math.max(gap, global.innerWidth - w - gap));
		var top = r.bottom + gap;
		if (top + panelHeight > global.innerHeight - gap) {
			top = Math.max(gap, r.top - panelHeight - gap);
		}
		this.panel.style.left = Math.round(left) + 'px';
		this.panel.style.top = Math.round(top) + 'px';
	};

	Overlay.prototype.submitFix = function () {
		if (!this.panelOpen || !this.selectedEl) { return; }
		var instruction = (this.panelInput && this.panelInput.value || '').trim();
		if (!instruction) { return; }
		this.fixCount++;
		var payload = {
			id: 'fix_' + Date.now().toString(36) + '_' + this.fixCount,
			instruction: instruction,
			element: describeElement(this.selectedEl),
			label: elementLabel(this.selectedEl),
		};
		this.emit('fix', payload);
		var keep = this.selectedEl;
		this.closePanel();
		this.selectedEl = keep;
		this.paintSelected();
		this.say('Fix added — ' + this.fixCount + ' pending');
	};

	Overlay.prototype.closePanel = function () {
		this.panelOpen = false;
		if (this.mounted) { this.panel.classList.remove('is-on'); this.panel.innerHTML = ''; }
	};

	Overlay.prototype.say = function (message) {
		var self = this;
		if (!this.mounted) { return; }
		this.toast.innerHTML = svg('check', 12) + '<span>' + escapeHtml(message) + '</span>';
		this.toast.classList.add('is-on');
		global.clearTimeout(this._toastTimer);
		this._toastTimer = global.setTimeout(function () { self.toast.classList.remove('is-on'); }, 2200);
	};

	/** Flash an element after the agent lands a fix, so the change is visible without hunting. */
	Overlay.prototype.flash = function (selector) {
		var self = this;
		this.mount();
		var target = selector ? safeQuery(selector) : this.selectedEl;
		if (!target) { return; }
		this.flashLayer.textContent = '';
		var r = rectOf(target);
		var verified = this.semanticColor('verified', target);
		el('rect', {
			class: 'cp-flash-box', x: r.left, y: r.top, width: r.width, height: r.height, rx: 2,
			stroke: toCss(verified), fill: toCss(verified), 'fill-opacity': '.16',
		}, this.flashLayer);
		global.setTimeout(function () { self.flashLayer.textContent = ''; }, 1400);
	};

	function clamp(value, min, max) { return Math.min(Math.max(value, min), max); }

	function escapeHtml(value) {
		return String(value == null ? '' : value)
			.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
	}

	/* ------------------------------------------------------------------ *
	 * Boot
	 * ------------------------------------------------------------------ */

	var overlay = new Overlay();
	// Node loads this file for its unit tests (the pure descriptor helpers); only a real document
	// gets the overlay mounted and the host handshake fired.
	var hasDom = !!(global.document && global.document.createElement && global.document.documentElement);
	if (hasDom) { overlay.mount(); }

	var api = {
		version: VERSION,
		overlay: overlay,
		start: function () { overlay.setInspecting(true); },
		stop: function () { overlay.setInspecting(false); },
		configure: function (theme) { overlay.theme = theme || {}; overlay.applyTheme(); },
		flash: function (selector) { overlay.flash(selector); },
		setPins: function (pins) { overlay.pins = pins || []; overlay.paintPins(); },
		// Pure helpers, exported for unit tests.
		describe: describeElement,
		buildSelector: buildSelector,
		buildXPath: buildXPath,
		elementLabel: elementLabel,
		isMeaningfulClass: isMeaningfulClass,
		fingerprint: fingerprint,
	};
	global.__crusorPreviewOverlay = api;
	if (hasDom) {
		overlay.emit('ready', { url: global.location.href, title: global.document.title, version: VERSION });
	}

	if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
})(typeof window !== 'undefined' ? window : globalThis);
