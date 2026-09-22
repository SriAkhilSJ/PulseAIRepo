/*---------------------------------------------------------------------------------------------
 * Crusor Preview window — behaviour.
 *
 * The flow this file owns (product spec, Crusor Preview):
 *   3. render the UI the agent built            -> iframe to the target (proxy-injected)
 *   4. one button arms inspect-and-edit         -> #cpw-inspect
 *   5-7. hover wireframes, click opens the small input panel (inside the overlay)
 *   8. fixes accumulate; Review opens the sheet  -> tray + review sheet
 *   9. Send to Crusor hands the batch to the Agent -> postMessage to the workbench host
 *
 * Message protocol (mirrored by common/crusorAIPreview.ts):
 *   workbench -> preview : { source: 'crusor-preview-workbench', command, ... }
 *   preview   -> overlay : { source: 'crusor-preview-host', command, ... }
 *   overlay   -> preview : { source: 'crusor-preview-overlay', type, ... }
 *   preview   -> workbench: { source: 'crusor-preview-window', type, ... }
 *--------------------------------------------------------------------------------------------*/
(function () {
	'use strict';

	var VIEWPORTS = {
		responsive: { label: 'Responsive' },
		desktop: { label: 'Desktop 1440×900', width: 1440, height: 900 },
		tablet: { label: 'Tablet 834×1112', width: 834, height: 1112 },
		phone: { label: 'Phone 390×844', width: 390, height: 844 },
	};

	var THEME_VAR_MAP = {
		accent: '--crusorai-accent',
		agent: '--crusorai-agent',
		verified: '--crusorai-verified',
		approval: '--crusorai-approval',
		failed: '--crusorai-failed',
		bg: '--crusorai-preview-bg',
		surface: '--crusorai-preview-surface',
		surfaceRaised: '--crusorai-preview-surface-raised',
		surfaceStrong: '--crusorai-preview-surface-strong',
		stage: '--crusorai-preview-stage',
		text: '--crusorai-preview-text',
		textWeak: '--crusorai-preview-text-weak',
		textMicro: '--crusorai-preview-text-micro',
		border: '--crusorai-preview-border',
		borderWeak: '--crusorai-preview-border-weak',
		onAccent: '--crusorai-preview-on-accent',
		fontUi: '--crusorai-font-ui',
		fontMono: '--crusorai-font-mono',
		radius: '--crusorai-preview-radius',
	};

	var doc = document;
	var view = doc.getElementById('cpw-view');
	var frame = doc.getElementById('cpw-frame');
	var empty = doc.getElementById('cpw-empty');
	var emptyCopy = doc.getElementById('cpw-empty-copy');
	var inspectBtn = doc.getElementById('cpw-inspect');
	var reloadBtn = doc.getElementById('cpw-reload');
	var closeBtn = doc.getElementById('cpw-close');
	var urlInput = doc.getElementById('cpw-url-input');
	var urlGo = doc.getElementById('cpw-url-go');
	var targetChip = doc.getElementById('cpw-target');
	var stateChip = doc.getElementById('cpw-state');
	var stateText = doc.getElementById('cpw-state-text');
	var tray = doc.getElementById('cpw-tray');
	var trayBadge = doc.getElementById('cpw-tray-badge');
	var trayLabel = doc.getElementById('cpw-tray-label');
	var trayList = doc.getElementById('cpw-tray-list');
	var reviewBtn = doc.getElementById('cpw-review');
	var clearBtn = doc.getElementById('cpw-clear');
	var sheetBackdrop = doc.getElementById('cpw-sheet-backdrop');
	var sheetBody = doc.getElementById('cpw-sheet-body');
	var sheetNote = doc.getElementById('cpw-sheet-note');
	var sheetSend = doc.getElementById('cpw-sheet-send');

	var state = {
		target: '',
		label: '',
		kind: 'url',
		sessionId: '',
		inspecting: false,
		overlayReady: false,
		fixes: [],
		activeFixId: null,
		viewport: 'responsive',
		embedded: window.parent !== window,
	};

	/* ------------------------------------------------------------------ *
	 * Messaging
	 * ------------------------------------------------------------------ */

	function postToHost(type, payload) {
		var message = { source: 'crusor-preview-window', type: type };
		if (payload) { Object.keys(payload).forEach(function (k) { message[k] = payload[k]; }); }
		try { window.parent.postMessage(message, '*'); } catch (_) { /* no host: standalone */ }
		return message;
	}

	function postToOverlay(command, payload) {
		var message = { source: 'crusor-preview-host', command: command };
		if (payload) { Object.keys(payload).forEach(function (k) { message[k] = payload[k]; }); }
		var target = view && view.contentWindow;
		if (!target) { return; }
		try { target.postMessage(message, '*'); } catch (_) { /* frame gone */ }
	}

	/* ------------------------------------------------------------------ *
	 * Theme (derived tokens pushed by the host; never hardcoded here)
	 * ------------------------------------------------------------------ */

	function applyTheme(theme) {
		if (!theme) { return; }
		Object.keys(THEME_VAR_MAP).forEach(function (key) {
			var value = theme[key];
			if (value) { doc.documentElement.style.setProperty(THEME_VAR_MAP[key], value); }
		});
		// The overlay inside the framed page paints with the same palette.
		postToOverlay('configure', { theme: theme });
		postToHost('theme-applied', {});
	}

	/* ------------------------------------------------------------------ *
	 * State chrome
	 * ------------------------------------------------------------------ */

	function setState(next, text) {
		stateChip.setAttribute('data-state', next);
		stateText.textContent = text || next;
	}

	function toast(message, tone, iconName) {
		var existing = doc.querySelector('.cpw-toast');
		if (existing) { existing.remove(); }
		var node = doc.createElement('div');
		node.className = 'cpw-toast';
		node.setAttribute('data-tone', tone || 'verified');
		node.setAttribute('role', 'status');
		node.innerHTML = '<svg aria-hidden="true"><use href="#cp-i-' + (iconName || 'check') + '"/></svg><span></span>';
		node.querySelector('span').textContent = message;
		doc.body.appendChild(node);
		requestAnimationFrame(function () { node.classList.add('is-on'); });
		setTimeout(function () {
			node.classList.remove('is-on');
			setTimeout(function () { node.remove(); }, 200);
		}, 2600);
	}

	function syncInspectButton() {
		inspectBtn.setAttribute('aria-pressed', state.inspecting ? 'true' : 'false');
		inspectBtn.querySelector('span').textContent = state.inspecting ? 'Editing UI' : 'Edit UI';
		inspectBtn.title = state.inspecting
			? 'Inspect is armed — click any element to describe a fix (Esc exits)'
			: 'Edit UI — click any element in the preview to describe a fix (Esc exits)';
		if (state.inspecting) { setState('inspect', 'inspect'); }
		else if (state.fixes.length) { setState('pending', state.fixes.length + ' pending'); }
		else if (state.target) { setState('live', 'live'); }
		else { setState('idle', 'idle'); }
	}

	/* ------------------------------------------------------------------ *
	 * Target loading
	 * ------------------------------------------------------------------ */

	function loadTarget(target, options) {
		var opts = options || {};
		var url = String(target || '').trim();
		if (!url) {
			state.target = '';
			empty.hidden = false;
			view.removeAttribute('src');
			targetChip.textContent = 'no target';
			targetChip.title = '';
			syncInspectButton();
			return;
		}
		state.target = url;
		state.label = opts.label || url;
		state.kind = opts.kind || (isWorkspaceFile(url) ? 'file' : 'url');
		state.overlayReady = false;
		urlInput.value = state.label;
		targetChip.textContent = state.label;
		targetChip.title = url;
		empty.hidden = true;
		setState('idle', 'loading');
		// Cache-bust so a reload after the agent lands a fix actually re-fetches.
		var separator = url.indexOf('?') === -1 ? '?' : '&';
		view.src = opts.noBust ? url : url + separator + 'cpReload=' + Date.now();
		postToHost('navigate', { url: url, label: state.label, kind: state.kind });
		syncInspectButton();
	}

	function isWorkspaceFile(url) {
		return /\.html?($|[?#])/i.test(url) && !/^https?:\/\//i.test(url);
	}

	view.addEventListener('load', function () {
		if (!state.target) { return; }
		setState(state.fixes.length ? 'pending' : 'live', state.fixes.length ? state.fixes.length + ' pending' : 'live');
		// Re-arm inspect after a reload: the overlay is gone with the old document.
		state.overlayReady = false;
		if (state.inspecting) { setTimeout(function () { postToOverlay('inspect', { on: true }); }, 60); }
		if (state.fixes.length) { setTimeout(pushPins, 80); }
	});

	view.addEventListener('error', function () {
		setState('error', 'unreachable');
		empty.hidden = false;
		emptyCopy.textContent = 'Nothing loaded from ' + state.target + '. Is the dev server running?';
	});

	/* ------------------------------------------------------------------ *
	 * Inspect mode
	 * ------------------------------------------------------------------ */

	function setInspecting(on) {
		state.inspecting = !!on;
		postToOverlay('inspect', { on: state.inspecting });
		doc.body.classList.toggle('is-inspecting', state.inspecting);
		syncInspectButton();
		postToHost('inspect', { on: state.inspecting });
	}

	inspectBtn.addEventListener('click', function () { setInspecting(!state.inspecting); });
	reloadBtn.addEventListener('click', function () { loadTarget(state.target, { label: state.label, kind: state.kind }); });
	urlGo.addEventListener('click', function () { loadTarget(urlInput.value); });
	urlInput.addEventListener('keydown', function (event) {
		if (event.key === 'Enter') { loadTarget(urlInput.value); }
	});
	closeBtn.addEventListener('click', function () {
		postToHost('close-request', {});
		if (!state.embedded) { window.close(); }
	});

	Array.prototype.forEach.call(doc.querySelectorAll('.cpw-vp'), function (button) {
		var preset = button.getAttribute('data-viewport');
		button.setAttribute('aria-pressed', preset === state.viewport ? 'true' : 'false');
		button.addEventListener('click', function () {
			state.viewport = preset;
			doc.body.setAttribute('data-viewport', preset);
			Array.prototype.forEach.call(doc.querySelectorAll('.cpw-vp'), function (other) {
				other.setAttribute('aria-pressed', other === button ? 'true' : 'false');
			});
			postToHost('viewport', { preset: preset, size: VIEWPORTS[preset] || null });
		});
	});

	doc.addEventListener('keydown', function (event) {
		if (event.key === 'Escape' && !sheetBackdrop.hidden) { closeSheet(); return; }
		// "e" arms inspect when the chrome (not the framed page) has focus.
		if ((event.key === 'e' || event.key === 'E') && !isTypingTarget(event.target) && sheetBackdrop.hidden) {
			event.preventDefault();
			setInspecting(!state.inspecting);
		}
	});

	function isTypingTarget(node) {
		return node && (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA' || node.isContentEditable);
	}

	/* ------------------------------------------------------------------ *
	 * Fix batch
	 * ------------------------------------------------------------------ */

	function addFix(fix) {
		if (!fix || !fix.instruction) { return; }
		state.fixes.push({
			id: fix.id || ('fix_' + Date.now().toString(36) + '_' + state.fixes.length),
			instruction: fix.instruction,
			label: fix.label || (fix.element && fix.element.tag) || 'element',
			element: fix.element || {},
			addedAt: Date.now(),
		});
		state.activeFixId = state.fixes[state.fixes.length - 1].id;
		renderTray();
		pushPins();
		syncInspectButton();
		postToHost('fix-added', { count: state.fixes.length, fix: state.fixes[state.fixes.length - 1] });
	}

	function dropFix(id) {
		state.fixes = state.fixes.filter(function (fix) { return fix.id !== id; });
		if (state.activeFixId === id) { state.activeFixId = state.fixes.length ? state.fixes[0].id : null; }
		renderTray();
		pushPins();
		syncInspectButton();
	}

	function clearFixes() {
		state.fixes = [];
		state.activeFixId = null;
		renderTray();
		pushPins();
		syncInspectButton();
	}

	function pushPins() {
		postToOverlay('pins', {
			pins: state.fixes.map(function (fix) {
				return { id: fix.id, selector: fix.element && fix.element.selector };
			}),
		});
	}

	function renderTray() {
		var count = state.fixes.length;
		tray.hidden = count === 0;
		trayBadge.textContent = String(count);
		trayLabel.textContent = count === 1 ? 'fix pending' : 'fixes pending';
		trayList.textContent = '';
		state.fixes.forEach(function (fix, index) {
			var item = doc.createElement('li');
			item.className = 'cpw-tray-item' + (fix.id === state.activeFixId ? ' is-active' : '');
			item.title = fix.instruction + '\n' + (fix.element.selector || '');

			var num = doc.createElement('span');
			num.className = 'cpw-tray-num';
			num.textContent = String(index + 1);

			var text = doc.createElement('span');
			text.className = 'cpw-tray-text';
			text.textContent = fix.instruction;

			var drop = doc.createElement('button');
			drop.type = 'button';
			drop.className = 'cpw-tray-drop';
			drop.title = 'Remove this fix';
			drop.setAttribute('aria-label', 'Remove fix ' + (index + 1));
			drop.innerHTML = '<svg aria-hidden="true"><use href="#cp-i-close"/></svg>';
			drop.addEventListener('click', function (event) { event.stopPropagation(); dropFix(fix.id); });

			item.append(num, text, drop);
			item.addEventListener('click', function () {
				state.activeFixId = fix.id;
				renderTray();
				postToOverlay('flash', { selector: fix.element && fix.element.selector });
			});
			trayList.appendChild(item);
		});
		reviewBtn.disabled = count === 0;
	}

	reviewBtn.addEventListener('click', openSheet);
	clearBtn.addEventListener('click', function () {
		clearFixes();
		postToOverlay('clear-pins', {});
		toast('Pending fixes discarded', 'failed', 'trash');
	});

	/* ------------------------------------------------------------------ *
	 * Review sheet (step 8 -> 9)
	 * ------------------------------------------------------------------ */

	function openSheet() {
		if (!state.fixes.length) { return; }
		renderSheet();
		sheetBackdrop.hidden = false;
		var first = sheetBody.querySelector('.cpw-fix-input');
		if (first) { first.focus(); }
		postToHost('review-open', { count: state.fixes.length });
	}

	function closeSheet() {
		sheetBackdrop.hidden = true;
		postToHost('review-close', {});
	}

	function renderSheet() {
		sheetBody.textContent = '';
		if (!state.fixes.length) {
			var none = doc.createElement('p');
			none.className = 'cpw-sheet-empty';
			none.textContent = 'No pending fixes. Arm “Edit UI” and click an element in the preview.';
			sheetBody.appendChild(none);
			sheetNote.textContent = '';
			sheetSend.disabled = true;
			return;
		}
		state.fixes.forEach(function (fix, index) {
			var row = doc.createElement('article');
			row.className = 'cpw-fix';
			row.dataset.id = fix.id;

			var num = doc.createElement('span');
			num.className = 'cpw-fix-num';
			num.textContent = String(index + 1);

			var main = doc.createElement('div');
			main.className = 'cpw-fix-main';

			var el = doc.createElement('span');
			el.className = 'cpw-fix-el';
			el.innerHTML = '<svg aria-hidden="true"><use href="#cp-i-target"/></svg>';
			var elText = doc.createElement('span');
			elText.textContent = fix.label;
			el.appendChild(elText);
			var sourceBtn = doc.createElement('button');
			sourceBtn.type = 'button';
			sourceBtn.className = 'cpw-icon-btn';
			sourceBtn.title = 'Ask Crusor to locate the source of this element';
			sourceBtn.setAttribute('aria-label', 'Locate source for fix ' + (index + 1));
			sourceBtn.innerHTML = '<svg aria-hidden="true"><use href="#cp-i-source"/></svg>';
			sourceBtn.addEventListener('click', function () {
				postToHost('open-source', { element: fix.element, fixId: fix.id });
				toast('Asked Crusor to locate the source', 'accent', 'source');
			});
			el.appendChild(sourceBtn);

			var input = doc.createElement('textarea');
			input.className = 'cpw-fix-input';
			input.rows = 2;
			input.value = fix.instruction;
			input.setAttribute('aria-label', 'Instruction for fix ' + (index + 1));
			input.addEventListener('input', function () { fix.instruction = input.value; });

			var meta = doc.createElement('span');
			meta.className = 'cpw-fix-meta';
			meta.textContent = (fix.element.selector || 'no selector') + ' · ' +
				(fix.element.rect ? fix.element.rect.width + '×' + fix.element.rect.height : '0×0');

			main.append(el, input, meta);

			var drop = doc.createElement('button');
			drop.type = 'button';
			drop.className = 'cpw-fix-drop';
			drop.title = 'Remove this fix';
			drop.setAttribute('aria-label', 'Remove fix ' + (index + 1));
			drop.innerHTML = '<svg aria-hidden="true"><use href="#cp-i-trash"/></svg>';
			drop.addEventListener('click', function () {
				dropFix(fix.id);
				renderSheet();
			});

			row.append(num, main, drop);
			sheetBody.appendChild(row);
		});
		sheetNote.textContent = state.fixes.length + (state.fixes.length === 1 ? ' fix' : ' fixes') +
			' · ' + (state.label || state.target);
		sheetSend.disabled = false;
	}

	doc.getElementById('cpw-sheet-close').addEventListener('click', closeSheet);
	doc.getElementById('cpw-sheet-cancel').addEventListener('click', closeSheet);
	sheetBackdrop.addEventListener('mousedown', function (event) {
		if (event.target === sheetBackdrop) { closeSheet(); }
	});

	sheetSend.addEventListener('click', function () {
		var batch = {
			sessionId: state.sessionId,
			target: state.target,
			targetLabel: state.label,
			kind: state.kind,
			viewport: state.viewport,
			createdAt: new Date().toISOString(),
			fixes: state.fixes.map(function (fix, index) {
				return {
					id: fix.id,
					order: index + 1,
					instruction: fix.instruction.trim(),
					label: fix.label,
					element: fix.element,
				};
			}).filter(function (fix) { return fix.instruction.length > 0; }),
		};
		if (!batch.fixes.length) { toast('Nothing to send — every fix is empty', 'failed', 'close'); return; }
		closeSheet();
		postToHost('review-submit', { batch: batch });
		setState('pending', 'sent');
		toast('Sent ' + batch.fixes.length + (batch.fixes.length === 1 ? ' fix' : ' fixes') + ' to Crusor', 'accent', 'send');
		clearFixes();
		postToOverlay('clear-pins', {});
		setInspecting(false);
	});

	/* ------------------------------------------------------------------ *
	 * Inbound messages
	 * ------------------------------------------------------------------ */

	window.addEventListener('message', function (event) {
		var data = event && event.data;
		if (!data || typeof data !== 'object') { return; }

		if (data.source === 'crusor-preview-overlay') {
			if (data.type === 'ready') {
				state.overlayReady = true;
				postToOverlay('configure', { theme: currentTheme() });
				if (state.inspecting) { postToOverlay('inspect', { on: true }); }
				if (state.fixes.length) { pushPins(); }
				postToHost('overlay-ready', { url: data.url });
				return;
			}
			if (data.type === 'fix') { addFix(data); return; }
			if (data.type === 'selected') { postToHost('element-selected', { element: data.element, label: data.label }); return; }
			if (data.type === 'inspect') {
				// The overlay can exit on its own (Esc) — keep the button honest.
				state.inspecting = !!data.on;
				syncInspectButton();
				postToHost('inspect', { on: state.inspecting });
				return;
			}
			if (data.type === 'pin-click') {
				state.activeFixId = data.id || null;
				renderTray();
				return;
			}
			return;
		}

		if (data.source === 'crusor-preview-workbench') {
			switch (data.command) {
				case 'configure':
					if (data.theme) { applyTheme(data.theme); }
					if (data.sessionId) { state.sessionId = data.sessionId; }
					if (data.target) { loadTarget(data.target, { label: data.label, kind: data.kind }); }
					postToHost('ready', { version: 1 });
					break;
				case 'theme':
					applyTheme(data.theme);
					break;
				case 'set-target':
					loadTarget(data.target, { label: data.label, kind: data.kind });
					break;
				case 'inspect':
					setInspecting(!!data.on);
					break;
				case 'agent-applied':
					// The agent landed the fixes: reload, then flash what changed.
					loadTarget(state.target, { label: state.label, kind: state.kind });
					setState('live', 'applied');
					if (data.selector) { setTimeout(function () { postToOverlay('flash', { selector: data.selector }); }, 700); }
					toast(data.summary || 'Crusor applied the fixes', 'verified', 'check');
					break;
				case 'toast':
					toast(data.message || '', data.tone || 'verified', data.icon || 'check');
					break;
				default:
					break;
			}
		}
	});

	function currentTheme() {
		var computed = getComputedStyle(doc.documentElement);
		var theme = {};
		Object.keys(THEME_VAR_MAP).forEach(function (key) {
			var value = computed.getPropertyValue(THEME_VAR_MAP[key]).trim();
			if (value) { theme[key] = value; }
		});
		return theme;
	}

	/* ------------------------------------------------------------------ *
	 * Boot
	 * ------------------------------------------------------------------ */

	/**
	 * Register the target with the preview proxy (src/preview/server.py) and return the URL to frame.
	 *
	 * This call is made HERE, in the preview window, and not by the workbench host: registering returns
	 * a per-target capability token and has to reach `http://127.0.0.1:<port>`, which the workbench
	 * document's own `connect-src` does not allow. The workbench passes the target and the proxy origin
	 * along in the URL; the window that is allowed to talk to the proxy does the talking.
	 */
	function registerTarget(endpoint, payload) {
		var base = String(endpoint || '').replace(/\/+$/, '');
		return fetch(base + '/crusor-preview/target', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
		}).then(function (response) {
			return response.json().then(function (body) {
				if (!response.ok || !body.ok) { throw new Error(body.error || ('HTTP ' + response.status)); }
				return { base: base, registration: body };
			});
		});
	}

	function boot() {
		var params = new URLSearchParams(window.location.search);
		var endpoint = params.get('endpoint') || '';
		var target = params.get('target') || '';
		var file = params.get('file') || '';
		var label = params.get('label') || '';
		var kind = params.get('kind') || '';
		state.sessionId = params.get('session') || '';
		if (params.get('theme')) {
			try { applyTheme(JSON.parse(params.get('theme'))); } catch (_) { /* ignore malformed theme */ }
		}
		renderTray();
		syncInspectButton();

		if (endpoint && (target || file)) {
			setState('idle', 'registering');
			registerTarget(endpoint, {
				url: target || undefined,
				file: file || undefined,
				label: label,
				session_id: state.sessionId,
			}).then(function (result) {
				var registration = result.registration;
				state.kind = registration.kind || kind || 'url';
				// previewUrl is root-relative, so it survives the window being served from the app, a
				// reverse proxy, or a plain http server (the lab); the proxy origin completes it.
				loadTarget(result.base + registration.previewUrl, {
					label: registration.label || label,
					kind: state.kind,
				});
			}).catch(function (error) {
				empty.hidden = false;
				emptyCopy.textContent = 'The preview proxy could not register this target: ' + error.message +
					'. Is the preview server still running (python -m src.preview.server --endpoint-session …)?';
				setState('error', 'no proxy');
				toast('Preview proxy unavailable', 'failed', 'close');
			});
		} else if (target) {
			loadTarget(target, { label: label, kind: kind });
		} else {
			empty.hidden = false;
			setState('idle', 'idle');
		}
		postToHost('ready', { version: 1, target: state.target, label: state.label });
	}

	// Exposed for the workbench host, the lab harness, and automated checks.
	window.__crusorPreviewWindow = {
		state: state,
		loadTarget: loadTarget,
		setInspecting: setInspecting,
		addFix: addFix,
		clearFixes: clearFixes,
		openSheet: openSheet,
		applyTheme: applyTheme,
		viewports: VIEWPORTS,
	};

	if (doc.readyState === 'loading') { doc.addEventListener('DOMContentLoaded', boot); }
	else { boot(); }
})();
