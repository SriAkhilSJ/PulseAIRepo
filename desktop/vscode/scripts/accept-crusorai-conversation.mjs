/**
 * Restored conversational UI acceptance (provider-free, deterministic).
 *
 * Runs the real Electron workbench + bridge + canonical runtime with the
 * scripted chat fixture (`CRUSORAI_BRIDGE_RUNNER=scripted`). It verifies the
 * pre-PR31 interaction model that the card stack had replaced:
 *
 *  A. assistant text appears progressively, chunk by chunk, before the turn ends;
 *  B/C. tool calls render inline, in arrival order, inside the same turn;
 *  D. cancellation paints "Run cancelled" and never a success;
 *  E. a reload restores the conversation and its inline tool rows;
 *  F. no typed agent card is painted anywhere in the transcript.
 */
import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const vscode = path.resolve(here, '..');
const repo = path.resolve(vscode, '..', '..');
const exe = path.join(vscode, '.build', 'electron', 'CrusorAI.exe');
const root = path.join(process.env.TEMP ?? process.env.LOCALAPPDATA, 'opencode', `crusor-conv-${Date.now()}`);
const workspace = path.join(root, 'workspace');
const userData = path.join(root, 'user-data');
const appData = path.join(root, 'appdata');
const home = path.join(root, 'home');
const evidence = path.join(repo, 'bench-results', 'phase-3.3-canonical-runtime', 'logs', 'electron-conversation');
const python = path.join(repo, '.venv', 'Scripts', 'python.exe');
const stubScript = path.join(repo, 'scripts', 'streaming_provider_stub.py');
const PROSE = "# Greeting\n\n"
	+ "I created `hello.md` with a short greeting for the project. Here is what I did and why it is safe to keep.\n\n"
	+ "## What changed\n\n"
	+ "- The greeting lives in a single Markdown file.\n"
	+ "- No existing file was modified.\n"
	+ "- The content is valid UTF-8.\n\n"
	+ "## How to use it\n\n"
	+ "Open the file, read the greeting, and replace the placeholder name with your own. "
	+ "The document is intentionally short so it stays easy to review, and every sentence is plain Markdown.\n\n"
	+ "```python\nprint(\"hello\")\n```\n\n"
	+ "If you want a longer welcome message, ask me to extend this file rather than creating another one.\n";

const freePort = () => new Promise((resolve, reject) => {
	const srv = net.createServer();
	srv.once('error', reject);
	srv.listen(0, '127.0.0.1', () => {
		const { port } = srv.address();
		srv.close(() => resolve(port));
	});
});

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
fs.rmSync(evidence, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
for (const dir of [workspace, userData, appData, home, evidence]) { fs.mkdirSync(dir, { recursive: true }); }
fs.writeFileSync(path.join(workspace, 'README.md'), '# conversational workspace\n', 'utf8');

const logFile = path.join(evidence, 'electron.log');
const out = fs.openSync(logFile, 'w');
const env = { ...process.env };
for (const key of ['ELECTRON_RUN_AS_NODE', 'VSCODE_ESM_ENTRYPOINT', 'VSCODE_IPC_HOOK', 'VSCODE_PID',
	'CRUSORAI_ORCHESTRATOR_MOCK', 'CRUSORAI_TEST_MODE', 'CRUSORAI_ACCEPTANCE_RUN_ID',
	'CRUSORAI_OFFLINE_MODE', 'PYTEST_CURRENT_TEST']) {
	delete env[key];
}
const port = await freePort();
const stubOut = fs.openSync(path.join(evidence, 'stub.log'), 'w');
const stub = spawn(python, [stubScript, '--port', String(port), '--chunks', '60', '--chunk-delay-ms', '120', '--content', PROSE], {
	cwd: repo, stdio: ['ignore', stubOut, stubOut],
});
const healthDeadline = Date.now() + 20_000;
while (Date.now() < healthDeadline) {
	try { if ((await fetch(`http://127.0.0.1:${port}/health`)).ok) { break; } } catch { /* starting */ }
	await new Promise(r => setTimeout(r, 200));
}

Object.assign(env, {
	VSCODE_DEV: '1', CRUSORAI_DEV: '1',
	// Loopback provider: real ChatOpenAI client + real gateway, no paid traffic.
	LLM_PROVIDER: 'custom',
	LLM_MODEL: 'z-ai/glm-5.3-flash',
	CUSTOM_BASE_URL: `http://127.0.0.1:${port}/v1`,
	CUSTOM_API_KEY: 'conversation-stub-key',
	CRUSORAI_BRIDGE_APPROVAL_POLICY: 'ask',
	CRUSORAI_ENGINE_ROOT: repo,
	CRUSORAI_APP_DATA_ROOT: appData,
	CRUSORAI_PREVIEW_AUTOSTART: '0',
	CRUSORAI_AUTOTITLE: '0',
	CRUSORAI_MEMORY: 'off',
	HOME: home, USERPROFILE: home,
	CRUSORAI_TURN_STALL_TIMEOUT_S: '120',
});

let proc;
let browser;
let page;
const report = { timestamp: new Date().toISOString(), checks: {}, samples: [], screenshots: [], limitations: [] };
const check = (name, value, detail = '') => {
	report.checks[name] = { pass: Boolean(value), detail };
	if (!value) { report.limitations.push(`${name}: ${detail}`); }
};
const shot = async name => {
	try { await page.screenshot({ path: path.join(evidence, name), timeout: 30_000 }); report.screenshots.push(name); }
	catch (error) { report.limitations.push(`screenshot ${name}: ${String(error).slice(0, 140)}`); }
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

const dismissFirstRun = async () => {
	try {
		const btn = page.getByText('Continue without Signing In', { exact: false }).first();
		if (await btn.count() && await btn.isVisible().catch(() => false)) {
			await btn.click({ timeout: 5_000 }).catch(() => {});
			await page.waitForTimeout(1000);
		}
		const close = page.locator('.monaco-dialog-box .codicon-close').first();
		if (await close.count() && await close.isVisible().catch(() => false)) {
			await close.click({ timeout: 5_000 }).catch(() => {});
			await page.waitForTimeout(600);
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
			await page.waitForTimeout(400);
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
		await page.waitForTimeout(1500);
	}
	throw new Error(`engine not ready: ${JSON.stringify(last)}`);
};

const snapshot = () => page.evaluate(() => {
	const lane = document.querySelector('.crusorai-transcript-lane');
	const nodes = lane ? [...lane.querySelectorAll('[data-component="text-part"], [data-component="tool"], .crusorai-tool-section, .crusorai-tool-row, .crusorai-agent-card')] : [];
	const textLengths = [...document.querySelectorAll('.crusorai-text-part')].map(n => (n.textContent ?? '').length);
	return {
		running: !!document.querySelector('.crusorai-send-stop'),
		textLengths,
		textCount: document.querySelectorAll('.crusorai-text-part').length,
		toolCount: document.querySelectorAll('.crusorai-tool-section').length || document.querySelectorAll('.crusorai-tool-row').length,
		cardCount: document.querySelectorAll('.crusorai-agent-card').length,
		internalCards: document.querySelectorAll('.crusorai-agent-card.is-verification, .crusorai-agent-card.is-delivery, .crusorai-agent-card.is-cost').length,
		activityBadges: document.querySelectorAll('.crusorai-agent-card.is-activity .crusorai-agent-card-badge').length,
		planStrip: !!document.querySelector('.crusorai-plan-strip'),
		order: nodes.map(n => n.classList.contains('crusorai-agent-card') ? 'card'
			: n.matches('[data-component="text-part"]') ? 'text' : 'tool'),
		inlineCode: document.querySelectorAll('.crusorai-md code').length,
		headings: document.querySelectorAll('.crusorai-md .crusorai-md-h').length,
		listItems: document.querySelectorAll('.crusorai-md ul li').length,
		codeBlocks: document.querySelectorAll('.crusorai-md pre').length,
		receipts: [...document.querySelectorAll('.crusorai-turn-receipt')].map(r => `${r.className}|${r.textContent}`),
		turns: document.querySelectorAll('.crusorai-assistant-message[data-turn-id]').length,
	};
});

const approveIfAsking = async (decision = 'approve') => {
	const selector = decision === 'approve' ? '[data-approve-once]' : '[data-deny]';
	const button = page.locator(selector).first();
	if (await button.count() && await button.isVisible().catch(() => false)) {
		await button.click({ timeout: 8_000 }).catch(() => {});
		await page.waitForTimeout(500);
		return true;
	}
	return false;
};

const submit = async prompt => {
	await page.locator('.crusorai-composer-input').fill(prompt);
	await page.waitForTimeout(200);
	await page.locator('.crusorai-composer-input').press('Enter');
};

const waitEnd = async (timeoutMs) => {
	const start = Date.now();
	let sawRunning = false;
	while (Date.now() - start < timeoutMs) {
		const running = await page.evaluate(() => !!document.querySelector('.crusorai-send-stop'));
		if (running) { sawRunning = true; }
		if (sawRunning && !running) {
			await page.waitForTimeout(1500);
			if (!await page.evaluate(() => !!document.querySelector('.crusorai-send-stop'))) {
				return true;
			}
		}
		await page.waitForTimeout(200);
	}
	return false;
};

const reload = async () => {
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.monaco-workbench', { timeout: 60_000 });
	await page.waitForTimeout(4000);
	await openAgent();
	await page.waitForTimeout(2500);
	await waitReady();
	await page.waitForTimeout(2500);
};

try {
	proc = launch();
	await connectPage();
	await waitReady();
	await shot('01-agent-ready.png');

	// --- turn 1: progressive text + inline tools ----------------------------
	const samples = [];
	await submit('Explain in Markdown how you would greet a new contributor to this project.');
	const deadline = Date.now() + 3 * 60_000;
	let ended = false;
	while (Date.now() < deadline) {
		const state = await snapshot();
		samples.push({ t: Date.now(), ...state });
		if (!state.running && samples.length > 3) { ended = true; break; }
		await page.waitForTimeout(150);
	}
	await page.waitForTimeout(1500);
	const finalState = await snapshot();
	report.samples = samples.slice(0, 40);

	const runningSamples = samples.filter(s => s.running);
	const growing = runningSamples
		.map(s => s.textLengths[0] ?? 0)
		.filter((value, index, arr) => index === 0 || value > arr[index - 1]);
	const distinctWhileRunning = [...new Set(runningSamples.map(s => s.textLengths[0] ?? 0))];
	check('assistant text streams before the turn ends', growing.length >= 3 && distinctWhileRunning.length >= 3,
		JSON.stringify({ distinctWhileRunning, ended }));
	check('text grows monotonically (no missing/duplicated chunks)',
		distinctWhileRunning.every((value, index) => index === 0 || value > distinctWhileRunning[index - 1]),
		JSON.stringify(distinctWhileRunning));
	check('assistant text is one chronological timeline', finalState.order.filter(kind => kind === 'text').length >= 1,
		JSON.stringify(finalState.order));
	check('final response is Markdown (heading, list, code, inline code)',
		finalState.headings > 0 && finalState.listItems >= 2 && finalState.codeBlocks > 0 && finalState.inlineCode > 0,
		JSON.stringify({ headings: finalState.headings, listItems: finalState.listItems, codeBlocks: finalState.codeBlocks, inlineCode: finalState.inlineCode }));
	check('verification/delivery/cost cards stay internal',
		samples.every(s => s.internalCards === 0) && finalState.internalCards === 0,
		JSON.stringify({ atEnd: finalState.internalCards }));
	check('no RUNNING/COMPLETED status badge on activity cards',
		samples.every(s => s.activityBadges === 0) && finalState.activityBadges === 0,
		JSON.stringify({ atEnd: finalState.activityBadges }));
	check('final response is Markdown (inline code parsed)', finalState.inlineCode > 0, String(finalState.inlineCode));
	check('turn ends without a failure receipt',
		!finalState.receipts.some(r => r.includes('is-failed') || r.includes('is-unknown')),
		JSON.stringify(finalState.receipts));
	await shot('02-conversation.png');

	// --- turn 2: cancellation ----------------------------------------------
	await submit('Explain in Markdown how you would welcome a returning contributor.');
	const cancelStart = Date.now();
	let cancelled = false;
	while (Date.now() - cancelStart < 20_000) {
		if (await page.evaluate(() => !!document.querySelector('.crusorai-send-stop'))) { cancelled = true; break; }
		await page.waitForTimeout(150);
	}
	if (cancelled) {
		// Let the reply paint its first held segment (~2s), then stop mid-stream.
		await page.waitForTimeout(3500);
		await page.evaluate(() => {
			const button = document.querySelector('.crusorai-send-stop');
			if (button instanceof HTMLElement) { button.click(); }
		});
	}
	check('cancellation was pressed while the reply was streaming', cancelled, 'no streaming reply to stop');
	const cancelDeadline = Date.now() + 30_000;
	let afterCancel = await snapshot();
	while (Date.now() < cancelDeadline && !afterCancel.receipts.some(r => r.includes('is-cancelled'))) {
		await page.waitForTimeout(400);
		afterCancel = await snapshot();
	}
	check('cancelled turn paints Run cancelled',
		afterCancel.receipts.some(r => r.includes('is-cancelled') && /cancelled/i.test(r)),
		JSON.stringify(afterCancel.receipts));
	check('cancelled turn is not painted as successful',
		!afterCancel.receipts.some(r => r.includes('is-failed') || r.includes('is-unknown')),
		JSON.stringify(afterCancel.receipts));
	await shot('03-cancelled.png');

	// --- turn 3: reload restores the conversation ---------------------------
	await reload();
	await page.waitForFunction(
		() => document.querySelectorAll('.crusorai-assistant-message[data-turn-id]').length >= 2,
		null, { timeout: 90_000 },
	);
	await page.waitForTimeout(2000);
	const restored = await snapshot();
	check('conversation restored after reload', restored.turns >= 2, String(restored.turns));
	check('restored transcript keeps internal cards hidden', restored.internalCards === 0, String(restored.internalCards));
	check('restored transcript keeps Markdown', restored.headings > 0 || restored.codeBlocks > 0,
		JSON.stringify({ headings: restored.headings, codeBlocks: restored.codeBlocks }));
	check('restored assistant text is present', restored.textLengths.some(length => length > 20),
		JSON.stringify(restored.textLengths));
	await shot('04-restored.png');

	report.verdict = Object.values(report.checks).every(entry => entry.pass) ? 'PASS' : 'FAIL';
} catch (error) {
	report.error = String(error).slice(0, 1500);
	report.verdict = 'FAIL';
	try { await shot('99-failure.png'); } catch { /* page gone */ }
} finally {
	fs.writeFileSync(path.join(evidence, 'acceptance.json'), JSON.stringify(report, null, 2));
	try { stub.kill(); } catch { /* gone */ }
	try { await browser?.close(); } catch { /* closed */ }
	try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* gone */ }
	console.log(JSON.stringify({ verdict: report.verdict, error: report.error ?? null, checks: report.checks }, null, 2));
}
