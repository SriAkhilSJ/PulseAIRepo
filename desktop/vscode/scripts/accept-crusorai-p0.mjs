/**
 * P0 acceptance: natural-language contract extraction + honest failure states.
 *
 * Deterministic and provider-free: the real Electron workbench, the real bridge,
 * the real canonical runtime and the real orchestrator contract gate run with
 * CRUSORAI_ORCHESTRATOR_MOCK=1 (the model adapter is the mock; nothing else is).
 *
 * Proves, in the actual UI:
 *  1. "Implement a divide(a, b) function ..." passes the contract gate (a plan
 *     card exists, the "no public symbol" rejection is absent);
 *  2. a genuinely ambiguous request still fails at the gate;
 *  3. that failure renders as a FAILED turn (receipt + error row), not as the
 *     assistant's answer, and never as "Outcome not recorded";
 *  4. after a workbench reload the failed turn restores as failed and the
 *     successful turn does not acquire a failure row.
 */
import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const vscode = path.resolve(here, '..');
const repo = path.resolve(vscode, '..', '..');
const exe = path.join(vscode, '.build', 'electron', 'CrusorAI.exe');
const root = path.join(process.env.TEMP ?? process.env.LOCALAPPDATA, 'opencode', `crusor-p0-${Date.now()}`);
const workspace = path.join(root, 'workspace');
const userData = path.join(root, 'user-data');
const appData = path.join(root, 'appdata');
const home = path.join(root, 'home');
const evidence = path.join(repo, 'bench-results', 'phase-3.3-canonical-runtime', 'logs', 'electron-p0');

const naturalPrompt = 'Implement a divide(a, b) function in src/mini_math/ops.py. '
	+ 'Division by zero must raise ZeroDivisionError. Preserve the existing functions.';
const ambiguousPrompt = 'Create src/mod.py with a public function that returns int.';

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
fs.rmSync(evidence, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
for (const dir of [workspace, userData, appData, home, evidence]) { fs.mkdirSync(dir, { recursive: true }); }
fs.mkdirSync(path.join(workspace, 'src', 'mini_math'), { recursive: true });
fs.mkdirSync(path.join(workspace, 'tests'), { recursive: true });
fs.writeFileSync(path.join(workspace, 'src', 'mini_math', 'ops.py'),
	'def add(a, b):\n    return a + b\n\n\ndef subtract(a, b):\n    return a - b\n', 'utf8');
fs.writeFileSync(path.join(workspace, 'src', 'mini_math', '__init__.py'),
	'from .ops import add, subtract\n\n__all__ = ["add", "subtract"]\n', 'utf8');
fs.writeFileSync(path.join(workspace, 'tests', 'test_ops.py'),
	'from mini_math.ops import add, subtract\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\ndef test_subtract():\n    assert subtract(5, 3) == 2\n', 'utf8');
fs.writeFileSync(path.join(workspace, 'README.md'), '# mini_math\n\nTiny arithmetic helpers.\n', 'utf8');

const logFile = path.join(evidence, 'electron.log');
const out = fs.openSync(logFile, 'w');
const env = { ...process.env };
for (const key of ['ELECTRON_RUN_AS_NODE', 'VSCODE_ESM_ENTRYPOINT', 'VSCODE_IPC_HOOK', 'VSCODE_PID']) { delete env[key]; }
Object.assign(env, {
	VSCODE_DEV: '1', CRUSORAI_DEV: '1',
	// The real orchestrator, contract gate, scheduler, approval gateway and bridge
	// run with the mock MODEL adapter only -- no paid provider call.
	CRUSORAI_ORCHESTRATOR_MOCK: '1',
	CRUSORAI_BRIDGE_APPROVAL_POLICY: 'ask',
	CRUSORAI_ENGINE_ROOT: repo,
	CRUSORAI_APP_DATA_ROOT: appData,
	CRUSORAI_PREVIEW_AUTOSTART: '0',
	CRUSORAI_AUTOTITLE: '0',
	CRUSORAI_MEMORY: 'off',
	HOME: home, USERPROFILE: home,
	CRUSORAI_TURN_STALL_TIMEOUT_S: '300',
});

let proc;
let browser;
let page;
const report = { timestamp: new Date().toISOString(), checks: {}, screenshots: [], limitations: [] };
const check = (name, value, detail = '') => {
	report.checks[name] = { pass: Boolean(value), detail };
	if (!value) { report.limitations.push(`${name}: ${detail}`); }
};
const shot = async name => {
	const file = path.join(evidence, name);
	for (let attempt = 0; attempt < 2; attempt++) {
		try { await page.screenshot({ path: file, timeout: 30_000 }); report.screenshots.push(file); return; }
		catch (error) {
			if (attempt === 1) { report.limitations.push(`screenshot ${name}: ${String(error).slice(0, 160)}`); }
			else { await page.waitForTimeout(1500); }
		}
	}
};

const launch = () => spawn(exe, ['.', workspace, '--remote-debugging-port=9222', '--no-sandbox',
	'--disable-gpu', '--disable-workspace-trust', `--user-data-dir=${userData}`, '--enable-logging',
], { env, stdio: ['ignore', out, out] });

const connectPage = async () => {
	const deadline = Date.now() + 90_000;
	while (Date.now() < deadline) {
		try {
			browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
			const context = browser.contexts()[0];
			page = context.pages().find(p => p.url().includes('workbench.html')) ?? context.pages()[0];
			if (page) { return; }
		} catch { /* booting */ }
		await new Promise(r => setTimeout(r, 1000));
	}
	throw new Error('workbench page did not appear');
};

const freePort = async () => {
	for (let attempt = 0; attempt < 20; attempt++) {
		try {
			await fetch('http://127.0.0.1:9222/json/version');
			await new Promise(r => setTimeout(r, 300));
		} catch { return; }
	}
};

// A fresh profile can open Copilot's first-run sign-in dialog over the
// workbench (it is hidden by crusorAIHideCopilot only after first run). It is
// not part of this test; dismiss it so the Agent pane can be opened.
const dismissFirstRun = async () => {
	try {
		const continueWithout = page.getByText('Continue without Signing In', { exact: false }).first();
		if (await continueWithout.count() && await continueWithout.isVisible().catch(() => false)) {
			await continueWithout.click({ timeout: 5_000 }).catch(() => {});
			await page.waitForTimeout(1200);
		}
		const close = page.locator('.monaco-dialog-box .codicon-close').first();
		if (await close.count() && await close.isVisible().catch(() => false)) {
			await close.click({ timeout: 5_000 }).catch(() => {});
			await page.waitForTimeout(800);
		}
	} catch { /* best effort */ }
};

const openAgent = async () => {
	const input = page.locator('.crusorai-composer-input').first();
	for (let attempt = 0; attempt < 6; attempt++) {
		await dismissFirstRun();
		if (await input.count() && await input.isVisible()) { return; }
		await page.keyboard.press(attempt === 0 ? 'Control+L' : 'F1');
		if (attempt > 0) {
			await page.waitForSelector('.quick-input-widget input', { timeout: 15_000 });
			await page.keyboard.type('Crusor: Open Agent');
			await page.waitForTimeout(500);
			await page.keyboard.press('Enter');
		}
		try { await page.waitForSelector('.crusorai-composer-input', { state: 'visible', timeout: 12_000 }); return; } catch { /* retry */ }
	}
	throw new Error('Agent pane did not open');
};

const waitReady = async (timeoutMs = 180_000) => {
	await page.waitForSelector('.monaco-workbench', { timeout: 60_000 });
	const deadline = Date.now() + timeoutMs;
	let last = '';
	while (Date.now() < deadline) {
		try { await openAgent(); } catch { /* retry */ }
		last = await page.evaluate(() => document.querySelector('.crusorai-engine-status')?.textContent ?? '');
		if (/Crusor ready/.test(last)) { return; }
		await page.waitForTimeout(2000);
	}
	throw new Error(`engine not ready: ${JSON.stringify(last)}`);
};

const waitTurnEnd = async (timeoutMs) => {
	const start = Date.now();
	let sawRunning = false;
	while (Date.now() - start < timeoutMs) {
		const running = await page.evaluate(() => !!document.querySelector('.crusorai-send-stop'));
		if (running) {
			sawRunning = true;
			const approve = page.locator('[data-approve-once]').first();
			if (await approve.count() && await approve.isVisible().catch(() => false)) {
				await approve.click({ timeout: 10_000 }).catch(() => {});
				await page.waitForTimeout(1200);
			}
		} else if (sawRunning) {
			await page.waitForTimeout(2500);
			if (!await page.evaluate(() => !!document.querySelector('.crusorai-send-stop'))) {
				return { ended: true, durationMs: Date.now() - start };
			}
		}
		await page.waitForTimeout(800);
	}
	return { ended: false, durationMs: Date.now() - start };
};

const send = async (prompt) => {
	await page.locator('.crusorai-composer-input').fill(prompt);
	await page.waitForTimeout(300);
	await page.locator('.crusorai-composer-input').press('Enter');
	try {
		await page.waitForFunction(() => !!document.querySelector('.crusorai-send-stop'), null, { timeout: 60_000 });
	} catch { /* a fast gate failure may finish before this polls */ }
	const end = await waitTurnEnd(8 * 60_000);
	await page.waitForTimeout(2000);
	return end;
};

const turnState = () => page.evaluate(() => {
	// Receipts and error rows are appended to the transcript LANE after their
	// turn's section (they are not children of it), so the lane is walked in
	// document order: a new assistant section starts a turn, a user bubble ends
	// the current one, and a receipt/error row attaches to whatever is open.
	const lane = document.querySelector('.crusorai-transcript-lane');
	const strip = document.querySelector('.crusorai-plan-strip');
	const planStrip = {
		present: !!strip,
		steps: strip ? [...strip.querySelectorAll('li')].map(li => `${li.className}:${(li.textContent ?? '').trim()}`) : [],
	};
	const turns = [];
	const orphans = { receipts: [], errors: [] };
	if (!lane) { return { turns, orphans, planStrip }; }
	let current = null;
	const push = (list, entry) => {
		if (current) { current[list].push(entry); } else { orphans[list].push(entry); }
	};
	for (const child of [...lane.children]) {
		if (child.matches('.crusorai-assistant-message[data-turn-id]')) {
			current = {
				turnId: child.dataset.turnId ?? '',
				text: (child.innerText ?? '').trim(),
				textParts: [...child.querySelectorAll('.crusorai-text-part')]
					.map(node => (node.textContent ?? '').trim()).filter(Boolean),
				planCards: child.querySelectorAll('.crusorai-agent-card.is-plan').length,
				receipts: [], errors: [],
			};
			turns.push(current);
			continue;
		}
		if (child.classList.contains('crusorai-user-message')) { current = null; continue; }
		if (child.classList.contains('crusorai-turn-receipt')) {
			push('receipts', { className: child.className, label: (child.textContent ?? '').trim() });
			continue;
		}
		if (child.classList.contains('crusorai-error-row')) {
			push('errors', (child.textContent ?? '').trim());
		}
	}
	return { turns, orphans, planStrip };
});

const allReceipts = state => [
	...state.turns.flatMap(turn => turn.receipts),
	...state.orphans.receipts,
];
const allErrors = state => [
	...state.turns.flatMap(turn => turn.errors),
	...state.orphans.errors,
];
const hasReceipt = (state, kind) => allReceipts(state).some(entry => entry.className.includes(`is-${kind}`));

try {
	await freePort();
	proc = launch();
	await connectPage();
	await waitReady();
	await shot('01-agent-ready.png');

	// --- turn 1: a known-good engineering turn must render as completed ------
	report.turnSuccessEnd = await send('Create notes.md with a short greeting for the project.');
	await shot('02-successful-turn.png');
	let state = await turnState();
	const success = state.turns[state.turns.length - 1];
	check('successful turn reaches planning',
		state.planStrip.present && state.planStrip.steps.length > 0,
		JSON.stringify({ planStrip: state.planStrip, text: (success?.text ?? '').slice(0, 220) }));
	check('successful turn produces assistant output', (success?.textParts.length ?? 0) > 0,
		JSON.stringify(success?.textParts.slice(0, 1)));
	check('successful turn has no failure receipt', !hasReceipt(state, 'failed'),
		JSON.stringify(allReceipts(state)));
	check('successful turn is not labelled unknown', !hasReceipt(state, 'unknown'),
		JSON.stringify(allReceipts(state)));

	// --- turn 2: natural-language callable must pass the contract gate -------
	report.turnNaturalEnd = await send(naturalPrompt);
	await shot('03-natural-language-turn.png');
	state = await turnState();
	const natural = state.turns[state.turns.length - 1];
	// The plan strip is populated only by a `plan_updated` frame, which the
	// orchestrator emits only after the contract gate admits the request. It
	// lives outside the turn section, so it is readable even when a mock
	// implementation fails later in the same turn.
	check('natural-language request reaches planning',
		state.planStrip.present && state.planStrip.steps.length > 0,
		JSON.stringify(state.planStrip));
	check('natural-language request is not rejected as ambiguous',
		!/no public symbol/i.test(JSON.stringify(state)), JSON.stringify(allErrors(state)));
	check('natural-language turn is not labelled unknown', !hasReceipt(state, 'unknown'),
		JSON.stringify(allReceipts(state)));
	void natural;

	// --- turn 3: genuine ambiguity must still fail, and look failed ----------
	const failedBefore = allReceipts(state).filter(entry => entry.className.includes('is-failed')).length;
	report.turnAmbiguousEnd = await send(ambiguousPrompt);
	await shot('04-ambiguous-turn.png');
	state = await turnState();
	const failedAfter = allReceipts(state).filter(entry => entry.className.includes('is-failed')).length;
	check('genuine ambiguity still fails at the gate',
		allErrors(state).some(text => /public symbol/i.test(text)), JSON.stringify(allErrors(state)));
	check('failed turn renders a failed receipt', failedAfter === failedBefore + 1,
		JSON.stringify({ failedBefore, failedAfter, receipts: allReceipts(state) }));
	check('failed turn shows the backend failure in the error row',
		allErrors(state).some(text => /public symbol/i.test(text)), JSON.stringify(allErrors(state)));
	check('failed turn is not painted as assistant prose',
		state.turns.every(turn => !turn.text.includes('public symbol')), JSON.stringify(state.turns.map(turn => turn.text.slice(0, 120))));
	check('failed turn is not labelled unknown', !hasReceipt(state, 'unknown'),
		JSON.stringify(allReceipts(state)));

	// --- reload: the durable outcome must survive ----------------------------
	const relaunch = async () => {
		try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* gone */ }
		try { await browser?.close(); } catch { /* closed */ }
		browser = undefined; page = undefined;
		await new Promise(r => setTimeout(r, 4000));
		proc = launch();
		await connectPage();
		await waitReady();
	};
	if (!page || page.isClosed()) {
		await relaunch();
	} else {
		try {
			await page.reload({ waitUntil: 'domcontentloaded' });
			await page.waitForSelector('.monaco-workbench', { timeout: 60_000 });
			await page.waitForTimeout(5000);
			await openAgent();
			await page.waitForTimeout(3000);
			await waitReady();
		} catch {
			// The workbench window can close during a renderer reload in this
			// build; a relaunch with the same profile is the stronger check.
			await relaunch();
		}
	}
	await page.waitForFunction(
		() => document.querySelectorAll('.crusorai-assistant-message[data-turn-id]').length >= 3,
		null, { timeout: 90_000 },
	);
	await page.waitForTimeout(3000);
	await shot('05-after-reload.png');
	const restored = await turnState();
	const first = restored.turns[0];
	const last = restored.turns[restored.turns.length - 1];
	check('three turns restored', restored.turns.length === 3, String(restored.turns.length));
	check('successful turn restores without a failure row',
		!!first && !first.receipts.some(entry => entry.className.includes('is-failed')),
		JSON.stringify(first?.receipts));
	check('failed turn restores as failed',
		!!last && last.receipts.some(entry => entry.className.includes('is-failed')),
		JSON.stringify(last?.receipts));
	check('failed turn does not restore as unknown',
		!!last && !last.receipts.some(entry => entry.className.includes('is-unknown') || entry.className.includes('is-incomplete')),
		JSON.stringify(last?.receipts));

	report.verdict = Object.values(report.checks).every(entry => entry.pass) ? 'PASS' : 'FAIL';
} catch (error) {
	report.error = String(error).slice(0, 1500);
	report.verdict = 'FAIL';
	try { await shot('99-failure.png'); } catch { /* page may be gone */ }
} finally {
	fs.writeFileSync(path.join(evidence, 'acceptance.json'), JSON.stringify(report, null, 2));
	try { await browser?.close(); } catch { /* closed */ }
	try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* gone */ }
	console.log(JSON.stringify(report, null, 2));
}
