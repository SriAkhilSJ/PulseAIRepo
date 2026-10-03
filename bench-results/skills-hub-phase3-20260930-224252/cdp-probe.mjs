// Probe: locate Crusor AI UI entry points in the live workbench.
const PORT = 9222;
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
	const evalJs = async (expression) => {
		const out = await new Promise((res, rej) => { const i = id++; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate', params: { expression, returnByValue: true } })); });
		return out.result?.value;
	};
	const report = {};
	report.activityBar = await evalJs(`[...document.querySelectorAll('.activitybar .action-item')].map(e => ({
		aria: e.querySelector('[aria-label]')?.getAttribute('aria-label') || e.getAttribute('aria-label') || null,
		title: e.getAttribute('title') || e.querySelector('[title]')?.getAttribute('title') || null,
		id: e.id || null }))`);
	report.editorTabs = await evalJs(`[...document.querySelectorAll('.tabs-container .tab, .tab[data-tooltip]')].map(e => ({
		text: (e.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 60),
		tooltip: e.getAttribute('data-tooltip') || e.title || null }))`);
	report.aiPowered = await evalJs(`[...document.querySelectorAll('*')]
		.filter(e => e.children.length === 0 && /AI-Powered/.test(e.textContent || ''))
		.slice(0, 5)
		.map(e => { let p = e, path = []; for (let i = 0; i < 6 && p; i++) { path.unshift(p.tagName + (p.className && typeof p.className === 'string' ? '.' + p.className.trim().split(/\\s+/).slice(0, 3).join('.') : '')); p = p.parentElement; } return path.join(' > '); })`);
	report.idOrClassCrusor = await evalJs(`[...document.querySelectorAll('[id*="crusor" i], [class*="crusor" i], [aria-label*="crusor" i], [title*="crusor" i]')]
		.slice(0, 15).map(e => ({ tag: e.tagName, cls: String(e.className).slice(0, 60), id: e.id || null, aria: (e.getAttribute('aria-label') || '').slice(0, 50), visible: e.offsetWidth > 0 }))`);
	console.log(JSON.stringify(report, null, 2));
	ws.close();
})().catch((e) => { console.error('ERR', e); process.exit(1); });
