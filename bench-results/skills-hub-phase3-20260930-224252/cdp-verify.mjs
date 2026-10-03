// Phase-3 verification: drive palette + agent panel via CDP, capture rows/chip/screenshots.
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
	let id = 1;
	const pending = new Map();
	ws.addEventListener('message', (e) => {
		const m = JSON.parse(String(e.data));
		if (m.id && pending.has(m.id)) {
			const s = pending.get(m.id); pending.delete(m.id);
			m.error ? s.rej(new Error(JSON.stringify(m.error))) : s.res(m.result || {});
		}
	});
	await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', () => rej(new Error('ws err')), { once: true }); });
	const call = (method, params = {}) => new Promise((res, rej) => { const i = id++; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
	const evalJs = async (expression) => {
		const out = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
		if (out.exceptionDetails) { throw new Error(String(out.exceptionDetails.exception?.description || JSON.stringify(out.exceptionDetails))); }
		return out.result?.value;
	};
	const key = (type, opts) => call('Input.dispatchKeyEvent', { type, ...opts });
	const tap = async (base) => { await key('rawKeyDown', base); await key('keyUp', base); };
	const shot = async (name) => {
		const s = await call('Page.captureScreenshot', { format: 'png' });
		writeFileSync(join(DIR, name), Buffer.from(s.data, 'base64'));
		return name;
	};
	const report = { url: t.url };

	// --- 1. command palette: open, filter "Crusor", read rendered rows ---
	await tap({ windowsVirtualKeyCode: 80, code: 'KeyP', key: 'P', modifiers: 10 }); // Ctrl+Shift+P
	await sleep(800);
	if (await evalJs(`!document.querySelector('.quick-input-widget')?.classList.contains('hidden')`)) {
		await call('Input.insertText', { text: 'Crusor' });
		await sleep(700);
		report.paletteRows = await evalJs(`[...document.querySelectorAll('.quick-input-list .monaco-list-row')]
			.map(r => (r.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).join(' — '))
			.slice(0, 25)`);
		report.paletteShot = await shot('palette-rows.png');
		await tap({ windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' });
	} else {
		await tap({ windowsVirtualKeyCode: 112, code: 'F1', key: 'F1' }); // fallback: F1
		await sleep(800);
		if (await evalJs(`!document.querySelector('.quick-input-widget')?.classList.contains('hidden')`)) {
			await call('Input.insertText', { text: 'Crusor' });
			await sleep(700);
			report.paletteRows = await evalJs(`[...document.querySelectorAll('.quick-input-list .monaco-list-row')]
				.map(r => (r.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).join(' — '))
				.slice(0, 25)`);
			report.paletteShot = await shot('palette-rows.png');
			await tap({ windowsVirtualKeyCode: 27, code: 'Escape', key: 'Escape' });
		} else {
			report.paletteRows = 'PALETTE DID NOT OPEN';
		}
	}
	await sleep(400);

	// --- 2. open the Crusor AI agent panel from the activity bar ---
	report.activityCandidates = await evalJs(`[...document.querySelectorAll('.activitybar [aria-label]')]
		.map(e => e.getAttribute('aria-label'))
		.filter(a => /crusor|agent|ai/i.test(a || ''))`);
	const clickRes = await evalJs(`(() => {
		const el = [...document.querySelectorAll('.activitybar [aria-label]')]
			.find(e => /crusor/i.test(e.getAttribute('aria-label') || ''));
		if (!el) { return 'NO ACTIVITY ITEM'; }
		el.click(); return 'clicked: ' + el.getAttribute('aria-label');
	})()`);
	report.panelOpen = clickRes;

	// --- 3. wait for the engine chip, then capture it ---
	let chip = null;
	for (let i = 0; i < 20; i++) {
		await sleep(1500);
		chip = await evalJs(`(() => {
			const b = document.querySelector('.crusorai-engine-build');
			const s = document.querySelector('.crusorai-engine-status');
			const host = b?.parentElement || s;
			const txt = (host?.innerText || '').replace(/\\s+/g, ' ').trim();
			return {
				text: txt || null,
				build: b?.textContent?.trim() || null,
				stale: /STALE/.test(txt),
				title: host?.title || null,
				agentHeader: !!document.querySelector('.crusorai-agent-header'),
				crusorEls: document.querySelectorAll('[class*=crusorai]').length,
			};
		})()`);
		if (chip?.text && /ready|error|engine/i.test(chip.text)) { break; }
	}
	report.chip = chip;
	report.chipShot = await shot('engine-chip.png');

	writeFileSync(join(DIR, 'cdp-verify.json'), JSON.stringify(report, null, 2));
	console.log(JSON.stringify(report, null, 2));
	ws.close();
})().catch((e) => { console.error('ERR', e); process.exit(1); });
