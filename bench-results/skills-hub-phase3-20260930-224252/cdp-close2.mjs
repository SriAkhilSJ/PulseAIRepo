// Staged attempts to close a stuck quick input: outside click → palette-switch + no-op command.
const PORT = Number(process.env.CDP_PORT || 9222);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
	const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
	const t = list.find((x) => x.type === 'page' && /workbench.*\.html/.test(x.url || ''));
	if (!t) { console.error('NO TARGET'); process.exit(1); }
	const ws = new WebSocket(t.webSocketDebuggerUrl);
	let id = 1; const pending = new Map();
	ws.addEventListener('message', (e) => {
		const m = JSON.parse(String(e.data));
		if (m.id && pending.has(m.id)) { const s = pending.get(m.id); pending.delete(m.id); m.error ? s.rej(new Error(JSON.stringify(m.error))) : s.res(m.result || {}); }
	});
	await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', () => rej(new Error('ws err')), { once: true }); });
	const call = (method, params = {}) => new Promise((res, rej) => { const i = id++; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
	const evalJs = async (expression) => (await call('Runtime.evaluate', { expression, returnByValue: true })).result?.value;
	const info = async () => evalJs(`(() => { const w = document.querySelector('.quick-input-widget'); const open = !!w && !w.classList.contains('hidden'); return { open, placeholder: open ? (w.querySelector('input')?.placeholder || null) : null }; })()`);
	const tap = async (base) => { await call('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base }); await call('Input.dispatchKeyEvent', { type: 'keyUp', ...base }); };
	const mouse = async (x, y) => { await call('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 }); await call('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 }); };
	const out = { start: await info() };

	// 1. outside click in the empty editor area
	await mouse(850, 550);
	await sleep(700);
	out.afterOutsideClick = await info();

	// 2. switch to command palette, run a harmless no-op command (closes the widget)
	if (out.afterOutsideClick.open) {
		await tap({ windowsVirtualKeyCode: 80, code: 'KeyP', key: 'P', modifiers: 10 });
		await sleep(700);
		await call('Input.insertText', { text: 'Toggle Word Wrap' });
		await sleep(600);
		out.paletteRows = await evalJs(`[...document.querySelectorAll('.quick-input-list .monaco-list-row')].map(r => (r.innerText || '').split('\n')[0]).slice(0, 6)`);
		const rect = await evalJs(`(() => { const r = [...document.querySelectorAll('.quick-input-list .monaco-list-row')].find(x => /Word Wrap/i.test(x.innerText || '')); if (!r) return null; const b = r.getBoundingClientRect(); return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) }; })()`);
		if (rect) { await mouse(rect.x, rect.y); await sleep(900); }
		out.afterNoopCommand = await info();
	}
	console.log(JSON.stringify(out, null, 2));
	ws.close();
})().catch((e) => { console.error('ERR', e); process.exit(1); });
