// Read the engine chip (stamp/STALE/hash) from the live workbench; open panel if needed.
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
	const report = {};

	// Clear a transient palette so it does not cover the chip screenshot.
	const paletteOpen = await evalJs(`!document.querySelector('.quick-input-widget')?.classList.contains('hidden')`);
	if (paletteOpen) {
		await call('Input.dispatchKeyEvent', { type: 'rawKeyDown', windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' });
		await call('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' });
		await sleep(400);
	}
	report.paletteWasOpen = paletteOpen;

	// Open the agent view if the render root is not mounted/visible.
	for (let i = 0; i < 10; i++) {
		const visible = await evalJs(`(() => { const r = document.querySelector('.crusorai-render-root'); return !!r && r.offsetWidth > 0; })()`);
		if (visible) break;
		await evalJs(`(() => { const el = [...document.querySelectorAll('[aria-label^="Open Crusor Agent"]')].find(e => e.offsetWidth > 0); if (el) { el.click(); return true; } return false; })()`);
		await sleep(1500);
	}

	// Poll the chip until the engine status shows up (or give up).
	let chip = null;
	for (let i = 0; i < 20; i++) {
		chip = await evalJs(`(() => {
			const build = document.querySelector('.crusorai-engine-build');
			const status = document.querySelector('.crusorai-engine-status');
			const root = document.querySelector('.crusorai-render-root');
			const host = build?.parentElement || status;
			const text = (host?.innerText || (root?.innerText || '')).replace(/\\s+/g, ' ').trim().slice(0, 300);
			return {
				text: text || null,
				build: build?.textContent?.trim() || null,
				staleBadge: build ? /STALE/.test(build.textContent || '') : null,
				statusText: status?.textContent?.trim() || null,
				hostTitle: host?.title || null,
				rootVisible: !!root && root.offsetWidth > 0,
			};
		})()`);
		if (chip?.text) break;
		await sleep(1500);
	}
	report.chip = chip;

	const shot = await call('Page.captureScreenshot', { format: 'png' });
	writeFileSync(join(DIR, 'engine-chip.png'), Buffer.from(shot.data, 'base64'));
	report.screenshot = 'engine-chip.png';

	writeFileSync(join(DIR, 'chip-read.json'), JSON.stringify(report, null, 2));
	console.log(JSON.stringify(report, null, 2));
	ws.close();
})().catch((e) => { console.error('ERR', e); process.exit(1); });
