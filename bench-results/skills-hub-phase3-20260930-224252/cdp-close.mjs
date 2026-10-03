// Close any open quick input: focus its input element first, then Escape.
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
	const state = async () => evalJs(`(() => { const w = document.querySelector('.quick-input-widget'); return !!w && !w.classList.contains('hidden'); })()`);
	const esc = async (type) => {
		await call('Input.dispatchKeyEvent', { type: type, windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' });
		await call('Input.dispatchKeyEvent', { type: type === 'rawKeyDown' ? 'keyUp' : 'keyUp', windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' });
	};
	const out = { wasOpen: await state() };
	if (out.wasOpen) {
		await evalJs(`(() => { const i = document.querySelector('.quick-input-widget input'); if (i) { i.focus(); return true; } return false; })()`);
		await sleep(300);
		await esc('rawKeyDown');
		await sleep(600);
		out.afterRaw = await state();
		if (out.afterRaw) {
			await evalJs(`(() => { const i = document.querySelector('.quick-input-widget input'); if (i) i.focus(); })()`);
			await esc('keyDown');
			await sleep(600);
			out.afterKeyDown = await state();
		}
	}
	console.log(JSON.stringify(out, null, 2));
	ws.close();
})().catch((e) => { console.error('ERR', e); process.exit(1); });
