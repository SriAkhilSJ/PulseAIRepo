// Run Skills Hub + My Skills commands via CDP; capture quick-pick or notification state.
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';

const DIR = dirname(fileURLToPath(import.meta.url));
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
	const evalJs = async (expression) => {
		const out = await call('Runtime.evaluate', { expression, returnByValue: true });
		if (out.exceptionDetails) { throw new Error(String(out.exceptionDetails.exception?.description || JSON.stringify(out.exceptionDetails))); }
		return out.result?.value;
	};
	const tap = async (base) => { await call('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base }); await call('Input.dispatchKeyEvent', { type: 'keyUp', ...base }); };
	const esc = async () => { await tap({ windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' }); await sleep(400); };
	const shot = async (name) => { const s = await call('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(DIR, name), Buffer.from(s.data, 'base64')); return name; };

	const stateExpr = String.raw`(() => {
		const w = document.querySelector('.quick-input-widget');
		const open = !!w && !w.classList.contains('hidden');
		const rows = open ? [...document.querySelectorAll('.quick-input-list .monaco-list-row')]
			.map(r => (r.innerText || '').split('\n').map(s => s.trim()).filter(Boolean).join(' — '))
			.slice(0, 12) : [];
		const placeholder = open ? (w.querySelector('input')?.placeholder || null) : null;
		const toasts = [...document.querySelectorAll('.notifications-toasts .notification')]
			.map(n => (n.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 240));
		return { open, placeholder, rows, toasts };
	})()`;
	const state = async () => evalJs(stateExpr);

	const runViaPalette = async (query, matchText, excludeText, label) => {
		const out = { query, label };
		await tap({ windowsVirtualKeyCode: 80, code: 'KeyP', key: 'P', modifiers: 10 }); // Ctrl+Shift+P
		await sleep(700);
		await call('Input.insertText', { text: query });
		await sleep(600);
		out.matchedRows = (await state()).rows;
		const rectExpr = `(() => {
			const want = ${JSON.stringify(matchText)};
			const skip = ${JSON.stringify(excludeText || '')};
			const r = [...document.querySelectorAll('.quick-input-list .monaco-list-row')]
				.find(x => { const s = (x.innerText || '').replace(/\\s+/g, ' '); return s.includes(want) && (skip === '' || !s.includes(skip)); });
			if (!r) return null;
			const b = r.getBoundingClientRect();
			return { x: Math.round(b.x + b.width / 2), y: Math.round(b.y + b.height / 2) };
		})()`;
		const rect = await evalJs(rectExpr);
		out.rowRect = rect;
		if (rect) {
			await call('Input.dispatchMouseEvent', { type: 'mousePressed', x: rect.x, y: rect.y, button: 'left', clickCount: 1 });
			await call('Input.dispatchMouseEvent', { type: 'mouseReleased', x: rect.x, y: rect.y, button: 'left', clickCount: 1 });
			await sleep(2000); // let the command run past the palette itself
			let st = null;
			for (let i = 0; i < 12; i++) {
				st = await state();
				if (st.toasts.length > 0) break;
				if (st.open && st.placeholder && st.placeholder.includes('Crusor')) break;
				if (st.open && st.rows.some((r) => r.includes('Search the Skills Hub'))) break;
				await sleep(1500);
			}
			out.result = st;
			out.screenshot = await shot(label + '.png');
		} else {
			out.result = 'COMMAND ROW NOT FOUND';
		}
		await esc();
		return out;
	};

	const report = {};
	report.preState = await state();
	await esc();

	report.skillsHub = await runViaPalette('Crusor: Skills Hub', 'Crusor: Skills Hub', 'Crusor: My Skills', 'skills-hub-pick');
	report.mySkills = await runViaPalette('Crusor: My Skills', 'Crusor: My Skills', '', 'my-skills-result');
	report.postState = await state();

	writeFileSync(join(DIR, 'commands-run.json'), JSON.stringify(report, null, 2));
	console.log(JSON.stringify(report, null, 2));
	ws.close();
})().catch((e) => { console.error('ERR', e); process.exit(1); });
