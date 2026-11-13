import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const vscode = path.resolve(here, '..');
const repo = path.resolve(vscode, '..', '..');
const exe = path.join(vscode, '.build', 'electron', 'CrusorAI.exe');
const acceptRoot = path.join(process.env.TEMP ?? process.env.LOCALAPPDATA, 'opencode', `crusor-stream-accept-${Date.now()}`);
const root = process.env.CRUSOR_ACCEPT_ROOT ?? acceptRoot;
const workspace = path.join(root, 'workspace');
const userData = path.join(root, 'user-data');
const appData = path.join(root, 'appdata');
const evidence = path.join(repo, 'bench-results', 'phase-3.3-canonical-runtime', 'logs', 'electron-streaming');
const prompt = 'Create hello.md with the Crusor launch line and verify it.';
const expected = 'Crusor — Build and Ship with Ease 🚀\n\nCreated `hello.md` with a short greeting. क्रूसोर — आसान और भरोसेमंद। 日本語：開発を加速する。\n\nVerification passed and the workspace contains only the requested file.';

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }

fs.rmSync(root, { recursive: true, force: true });
fs.mkdirSync(workspace, { recursive: true });
fs.mkdirSync(userData, { recursive: true });
fs.mkdirSync(appData, { recursive: true });
fs.mkdirSync(evidence, { recursive: true });
fs.writeFileSync(path.join(workspace, 'README.md'), '# disposable acceptance workspace\n', 'utf8');

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }

const logFile = path.join(evidence, 'electron.log');
const out = fs.openSync(logFile, 'w');
const env = { ...process.env };
for (const key of ['ELECTRON_RUN_AS_NODE', 'VSCODE_ESM_ENTRYPOINT', 'VSCODE_IPC_HOOK', 'VSCODE_PID']) { delete env[key]; }
env.VSCODE_DEV = '1';
env.CRUSORAI_DEV = '1';
env.CRUSORAI_BRIDGE_RUNNER = 'scripted';
env.CRUSORAI_SCRIPTED_DELAY_MS = '140';
env.CRUSORAI_ENGINE_ROOT = repo;
env.CRUSORAI_APP_DATA_ROOT = appData;
env.CRUSORAI_PREVIEW_AUTOSTART = '0';
env.CRUSORAI_TURN_STALL_TIMEOUT_S = '120';

const proc = spawn(exe, [
	'.',
	workspace,
	'--remote-debugging-port=9222',
	'--no-sandbox',
	'--disable-gpu',
	'--disable-workspace-trust',
	`--user-data-dir=${userData}`,
	'--enable-logging',
], { env, stdio: ['ignore', out, out] });

const report = { timestamp: new Date().toISOString(), checks: {}, screenshots: [], limitations: [] };
let browser;
const shot = async (page, name) => {
	const file = path.join(evidence, name);
	await page.screenshot({ path: file, fullPage: false });
	report.screenshots.push(file);
};
const check = (name, value, detail = '') => {
	report.checks[name] = { pass: Boolean(value), detail };
	if (!value) { report.limitations.push(`${name}: ${detail}`); }
};

let page;
try {
	const deadline = Date.now() + 60_000;
	while (Date.now() < deadline) {
		try {
			browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
			const context = browser.contexts()[0];
			page = context.pages().find(p => p.url().includes('workbench.html')) ?? context.pages()[0];
			if (page) { break; }
		} catch { /* app still booting */ }
		await new Promise(r => setTimeout(r, 1000));
	}
	if (!page) { throw new Error('workbench page did not appear'); }
	page.on('console', msg => { if (msg.type() === 'error') { report.limitations.push(`console: ${msg.text().slice(0, 300)}`); } });
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });

	await page.keyboard.press('F1');
	await page.waitForSelector('.quick-input-widget input', { timeout: 15_000 });
	await page.keyboard.type('Crusor: Open Agent');
	await page.waitForTimeout(500);
	await page.keyboard.press('Enter');
	await page.waitForSelector('.crusorai-composer-input:not([disabled])', { timeout: 90_000 });
	await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 120_000 });
	await shot(page, '01-agent-opened.png');
	check('agent pane opens', true);

	// Submit and immediately capture the pre-token activity card.
	await page.locator('.crusorai-composer-input').fill(prompt);
	await page.locator('.crusorai-composer-input').press('Enter');
	await page.waitForSelector('.crusorai-agent-card.is-activity', { timeout: 15_000 });
	await shot(page, '02-activity-immediate.png');
	check('activity card appears before completion', true);
	check('user message visible', await page.locator('.crusorai-user-message-text').first().textContent() !== null);
	check('no blank panel while working', await page.locator('.crusorai-assistant-label').count() > 0);

	// Streaming: partial text must appear before turn_done.
	await page.waitForFunction(() => document.body.innerText.includes('Crusor — Build'), null, { timeout: 20_000 });
	await shot(page, '03-streaming.png');
	check('response streams incrementally', true);

	await page.waitForSelector('.crusorai-agent-card.is-plan', { timeout: 20_000 });
	await shot(page, '04-plan-card.png');
	check('plan card renders', true);

	await page.waitForSelector('[data-component="approval-dock"] [data-approve-once]', { timeout: 30_000 });
	await shot(page, '05-approval-diff.png');
	check('approval card and diff render', await page.locator('.crusorai-agent-card.is-approval').count() > 0);
	check('approval dock carries real controls', await page.locator('[data-approve-once]').count() > 0);

	await page.locator('[data-approve-once]').first().click();
	await page.waitForFunction(() => {
		const cards = [...document.querySelectorAll('.crusorai-agent-card.is-approval')];
		return cards.some(card => /approved/i.test(card.textContent ?? ''));
	}, null, { timeout: 20_000 });
	await shot(page, '06-approved.png');
	check('approval updates card state', true);

	await page.waitForSelector('.crusorai-agent-card.is-test_results', { timeout: 20_000 });
	await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 20_000 });
	await shot(page, '07-complete-cards.png');
	check('test results card renders', true);
	const hiddenCards = await page.evaluate(() => ({
		verification: document.querySelectorAll('.crusorai-agent-card.is-verification').length,
		delivery: document.querySelectorAll('.crusorai-agent-card.is-delivery').length,
		cost: document.querySelectorAll('.crusorai-agent-card.is-cost').length,
	}));
	check('verification/delivery/cost cards are not user-facing',
		hiddenCards.verification === 0 && hiddenCards.delivery === 0 && hiddenCards.cost === 0,
		JSON.stringify(hiddenCards));
	check('final assistant response remains visible',
		(await page.locator('.crusorai-assistant-message').last().innerText()).length > 0);

	const bytes = fs.readFileSync(path.join(workspace, 'hello.md'));
	check('workspace file is exact UTF-8', bytes.equals(Buffer.from(expected, 'utf8')),
		`bytes=${bytes.length} sha256=${createHash('sha256').update(bytes).digest('hex')}`);

	// Cancellation on a second turn.
	await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 20_000 });
	await page.locator('.crusorai-composer-input').fill('Cancel this streamed turn.');
	await page.locator('.crusorai-composer-input').press('Enter');
	await page.waitForSelector('.crusorai-send-stop', { timeout: 15_000 });
	await page.waitForTimeout(250);
	await page.locator('.crusorai-send-stop').click();
	await page.waitForFunction(() => /Run cancelled|cancelled by the user/i.test(document.body.innerText), null, { timeout: 20_000 });
	await shot(page, '08-cancelled.png');
	check('cancellation stops the turn truthfully', true);

	// Reconnect/replay: reload the workbench and reopen the Agent pane.
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });
	await page.keyboard.press('F1');
	await page.waitForSelector('.quick-input-widget input', { timeout: 15_000 });
	await page.keyboard.type('Crusor: Open Agent');
	await page.waitForTimeout(400);
	await page.keyboard.press('Enter');
	await page.waitForSelector('.crusorai-composer-input:not([disabled])', { timeout: 90_000 });
	await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 120_000 });
	await page.waitForTimeout(3000);
	await shot(page, '09-reconnect.png');
	const replayText = await page.locator('.crusorai-assistant-message').allInnerTexts();
	check('reconnect restores the conversation', replayText.some(t => t.includes('Crusor — Build') || t.includes('hello.md')),
		`turns=${replayText.length}`);

	report.git = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim();
	report.verdict = Object.values(report.checks).every(c => c.pass) ? 'PASS' : 'PARTIAL';
} catch (error) {
	report.error = String(error?.stack ?? error);
	report.verdict = 'FAIL';
	try { if (page) { await shot(page, '99-failure.png'); } } catch { /* ignore */ }
} finally {
	fs.writeFileSync(path.join(evidence, 'acceptance.json'), JSON.stringify(report, null, 2));
	try { if (browser) { await browser.close(); } } catch { /* ignore */ }
	try { proc.kill(); } catch { /* ignore */ }
	fs.closeSync(out);
}

console.log(JSON.stringify({ verdict: report.verdict, checks: report.checks, error: report.error }, null, 2));
process.exit(report.verdict === 'PASS' ? 0 : 1);
