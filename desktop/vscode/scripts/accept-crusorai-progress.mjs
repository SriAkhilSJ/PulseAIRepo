/**
 * Deterministic, provider-free acceptance for live engineering progress.
 *
 * Launches the real Electron workbench against the real Python bridge with
 * CRUSORAI_ORCHESTRATOR_MOCK=1. The engineering turn then runs the real
 * orchestrator (mock model), the real event bus, the real bridge projection
 * and the real Agentic UI -- no paid provider call.
 *
 * Proves:
 *  - the activity card changes stage while the turn is still running;
 *  - the plan card appears mid-run with real DAG steps;
 *  - the terminal activity card settles on "Delivered";
 *  - both cards survive a workbench reload (journal replay).
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
const root = path.join(process.env.TEMP ?? process.env.LOCALAPPDATA, 'opencode', `crusor-progress-${Date.now()}`);
const workspace = path.join(root, 'workspace');
const userData = path.join(root, 'user-data');
const appData = path.join(root, 'appdata');
const home = path.join(root, 'home');
const evidence = path.join(repo, 'bench-results', 'phase-3.3-canonical-runtime', 'logs', 'electron-progress');
const prompt = 'Create notes.md with a short greeting for the project.';
const failedPrompt = 'Create notes.md/greeting.py with a short greeting for the project.';
const cancelledPrompt = 'Create notes2.md with a short greeting for the project.';

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
fs.rmSync(evidence, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
for (const dir of [workspace, userData, appData, home, evidence]) { fs.mkdirSync(dir, { recursive: true }); }
fs.writeFileSync(path.join(workspace, 'README.md'), '# disposable progress acceptance workspace\n', 'utf8');

const logFile = path.join(evidence, 'electron.log');
const out = fs.openSync(logFile, 'w');
const env = { ...process.env };
for (const key of ['ELECTRON_RUN_AS_NODE', 'VSCODE_ESM_ENTRYPOINT', 'VSCODE_IPC_HOOK', 'VSCODE_PID']) { delete env[key]; }
Object.assign(env, {
	VSCODE_DEV: '1', CRUSORAI_DEV: '1',
	// Deterministic engineering engine: the real orchestrator, scheduler,
	// approval gateway and bridge run with the mock model adapter (no provider
	// call). Approval policy "ask" gives a stable wait for the Stop path.
	CRUSORAI_ORCHESTRATOR_MOCK: '1',
	CRUSORAI_TEST_MODE: '1',
	CRUSORAI_BRIDGE_APPROVAL_POLICY: 'ask',
	CRUSORAI_ENGINE_ROOT: repo,
	CRUSORAI_APP_DATA_ROOT: appData,
	CRUSORAI_PREVIEW_AUTOSTART: '0',
	CRUSORAI_AUTOTITLE: '0',
	CRUSORAI_MEMORY: 'off',
	HOME: home, USERPROFILE: home,
	CRUSORAI_TURN_STALL_TIMEOUT_S: '300',
});

const launchApp = (port = 9222) => spawn(exe, ['.', workspace, `--remote-debugging-port=${port}`, '--no-sandbox',
	'--disable-gpu', '--disable-workspace-trust', `--user-data-dir=${userData}`, '--enable-logging',
], { env, stdio: ['ignore', out, out] });
let proc = launchApp(9222);

const report = { timestamp: new Date().toISOString(), checks: {}, screenshots: [], stages: [], limitations: [] };
let browser;
let page;
const shot = async name => {
	const file = path.join(evidence, name);
	for (let attempt = 0; attempt < 2; attempt++) {
		try {
			await page.screenshot({ path: file, timeout: 30_000 });
			report.screenshots.push(file);
			return;
		} catch (error) {
			// Screenshots are evidence, never an assertion: a busy renderer must
			// not turn a passing functional check into a failed acceptance.
			if (attempt === 1) { report.limitations.push(`screenshot ${name}: ${String(error).slice(0, 160)}`); }
			else { await page.waitForTimeout(2000); }
		}
	}
};
const check = (name, value, detail = '') => {
	report.checks[name] = { pass: Boolean(value), detail };
	if (!value) { report.limitations.push(`${name}: ${detail}`); }
};

const openAgent = async () => {
	const input = page.locator('.crusorai-composer-input').first();
	for (let attempt = 0; attempt < 5; attempt++) {
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

const connectPage = async (port = 9222) => {
	const deadline = Date.now() + 60_000;
	while (Date.now() < deadline) {
		try {
			browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
			const context = browser.contexts()[0];
			page = context.pages().find(p => p.url().includes('workbench.html')) ?? context.pages()[0];
			if (page) { return; }
		} catch { /* app still booting */ }
		await new Promise(r => setTimeout(r, 1000));
	}
	throw new Error('workbench page did not appear');
};

const waitAgentReady = async (timeoutMs = 180_000) => {
	await page.waitForSelector('.monaco-workbench', { timeout: 60_000 });
	const deadline = Date.now() + timeoutMs;
	let lastStatus = '';
	while (Date.now() < deadline) {
		try { await openAgent(); } catch { /* retry the focus command */ }
		lastStatus = await page.evaluate(() =>
			document.querySelector('.crusorai-engine-status')?.textContent ?? '');
		if (/Crusor ready/.test(lastStatus)) { return; }
		await page.waitForTimeout(2000);
	}
	throw new Error(`Agent engine did not become ready (last status: ${JSON.stringify(lastStatus)})`);
};

const relaunchApp = async () => {
	try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* already gone */ }
	try { await browser?.close(); } catch { /* already closed */ }
	browser = undefined;
	page = undefined;
	await new Promise(resolve => setTimeout(resolve, 4000));
	proc = launchApp(9222);
	await connectPage(9222);
	await waitAgentReady(180_000);
};

const reloadAndOpen = async () => {
	if (!page || page.isClosed()) {
		// The workbench window can close during a renderer reload in this
		// build; a clean relaunch with the same profile is the stronger
		// hydration check and must restore the same per-turn cards.
		await relaunchApp();
		return;
	}
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });
	await page.waitForTimeout(6000);
	await waitAgentReady();
	await page.waitForTimeout(4000);
};

const turnOwnership = () => page.evaluate(() => {
	const statusOf = step => {
		const cls = step.className;
		if (cls.includes('is-completed')) { return 'completed'; }
		if (cls.includes('is-failed')) { return 'failed'; }
		if (cls.includes('is-blocked')) { return 'blocked'; }
		if (cls.includes('is-cancelled')) { return 'cancelled'; }
		if (cls.includes('is-in_progress')) { return 'in_progress'; }
		return 'pending';
	};
	return [...document.querySelectorAll('.crusorai-assistant-message[data-turn-id]')].map(section => {
		const cards = [...section.querySelectorAll('.crusorai-agent-card')];
		return {
			turnId: section.dataset.turnId ?? '',
			cardIds: cards.map(card => card.dataset.cardId ?? ''),
			plans: [...section.querySelectorAll('.crusorai-agent-card.is-plan')].map(card => ({
				cardId: card.dataset.cardId ?? '',
				steps: [...card.querySelectorAll('.crusorai-agent-card-step')].map(statusOf),
			})),
		};
	}).filter(turn => turn.turnId);
});

const activityTitle = async () => page.evaluate(() => {
	const card = document.querySelector('.crusorai-agent-card.is-activity');
	return card ? (card.querySelector('.crusorai-agent-card-title')?.textContent ?? card.innerText ?? '') : '';
});
const planCounts = () => page.evaluate(() => {
	// The CURRENT turn's plan is the last card in the stack: earlier turns'
	// journaled cards can still be loaded beside it.
	const cards = [...document.querySelectorAll('.crusorai-agent-card.is-plan')];
	const card = cards[cards.length - 1];
	const steps = card ? [...card.querySelectorAll('.crusorai-agent-card-step')] : [];
	const count = cls => steps.filter(step => step.classList.contains(cls)).length;
	return {
		total: steps.length,
		completed: count('is-completed'),
		failed: count('is-failed'),
		blocked: count('is-blocked'),
		cancelled: count('is-cancelled'),
		in_progress: count('is-in_progress'),
	};
});
const allPlanCounts = () => page.evaluate(() => {
	const steps = [...document.querySelectorAll('.crusorai-agent-card.is-plan .crusorai-agent-card-step')];
	const count = cls => steps.filter(step => step.classList.contains(cls)).length;
	return {
		total: steps.length,
		completed: count('is-completed'),
		failed: count('is-failed'),
		blocked: count('is-blocked'),
		cancelled: count('is-cancelled'),
		in_progress: count('is-in_progress'),
	};
});

try {
	await connectPage();
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });
	await openAgent();
	await page.waitForTimeout(4500);
	await waitAgentReady();
	await shot('01-agent-ready.png');

	await page.locator('.crusorai-composer-input').fill(prompt);
	// Observe the DOM from BEFORE the submit: the mock engineering turn can
	// finish in a few seconds, so polling would miss the stage transitions.
	await page.evaluate(() => {
		const state = {
			titles: [], runningTitles: [], planSeenRunning: false, stopSeen: false,
			completedWhileRunning: false, activeWhileRunning: false, maxCompletedSteps: 0,
		};
		const w = window;
		w.__crusorProgress = state;
		const record = () => {
			const stop = !!document.querySelector('.crusorai-send-stop');
			if (stop) { state.stopSeen = true; }
			const card = document.querySelector('.crusorai-agent-card.is-activity');
			const title = card?.querySelector('.crusorai-agent-card-title')?.textContent?.trim();
			if (title) {
				if (state.titles[state.titles.length - 1] !== title) { state.titles.push(title); }
				if (stop && !state.runningTitles.includes(title)) { state.runningTitles.push(title); }
			}
			const planCard = document.querySelector('.crusorai-agent-card.is-plan');
			if (planCard) {
				if (stop) { state.planSeenRunning = true; }
				const steps = [...planCard.querySelectorAll('.crusorai-agent-card-step')];
				const completed = steps.filter(step => step.classList.contains('is-completed')).length;
				const active = steps.filter(step => step.classList.contains('is-in_progress')).length;
				state.maxCompletedSteps = Math.max(state.maxCompletedSteps, completed);
				if (stop && completed > 0) { state.completedWhileRunning = true; }
				if (stop && active > 0) { state.activeWhileRunning = true; }
			}
		};
		record();
		new MutationObserver(record).observe(document.body, {
			subtree: true, childList: true, characterData: true, attributes: true,
		});
	});
	await page.locator('.crusorai-composer-input').press('Enter');

	await page.waitForSelector('.crusorai-agent-card.is-activity', { timeout: 30_000 });
	await shot('02-first-stage.png');

	// Approval policy is "ask": approve the real mutation so the run completes.
	await page.waitForSelector('[data-approve-once]', { timeout: 120_000 });
	await page.locator('[data-approve-once]').first().click({ timeout: 15_000 });

	await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 300_000 });
	await page.waitForTimeout(1500);

	const sampled = await page.evaluate(() => window.__crusorProgress ?? { titles: [], runningTitles: [] });
	report.stages = sampled.titles;
	report.runningStages = sampled.runningTitles;
	await shot('03-progress-stages.png');

	check('activity card updates live before completion',
		sampled.stopSeen && sampled.runningTitles.length >= 3,
		`running=${JSON.stringify(sampled.runningTitles)} all=${JSON.stringify(sampled.titles)}`);
	check('progress stages are human labels, not raw stage ids',
		sampled.titles.some(t => /Understanding request|Planning changes|Implementing changes|Running tests|Checking|Validating|Discovering/.test(t)),
		JSON.stringify(sampled.titles));
	check('plan card appears mid-run', sampled.planSeenRunning === true,
		`running=${JSON.stringify(sampled.runningTitles)}`);
	check('plan steps show an executing state', sampled.activeWhileRunning === true,
		JSON.stringify(sampled));
	check('plan steps complete while the turn is still running', sampled.completedWhileRunning === true,
		JSON.stringify(sampled));

	// Approval is handled before the wait above (policy "ask").
	await shot('04-complete.png');

	const cards = await page.locator('.crusorai-agent-card').allInnerTexts();
	const joined = cards.join('\n');
	check('activity settles on Delivered', (await activityTitle()).trim() === 'Delivered',
		await activityTitle());
	const finalPlan = await page.evaluate(() => {
		const card = document.querySelector('.crusorai-agent-card.is-plan');
		if (!card) { return null; }
		const steps = [...card.querySelectorAll('.crusorai-agent-card-step')];
		return {
			total: steps.length,
			completed: steps.filter(step => step.classList.contains('is-completed')).length,
			failed: steps.filter(step => step.classList.contains('is-failed')).length,
		};
	});
	check('final plan records real completion',
		Boolean(finalPlan) && finalPlan.total > 0 && finalPlan.completed === finalPlan.total,
		JSON.stringify(finalPlan));
	check('plan card rendered', cards.some(c => /steps|task_|Plan/i.test(c)), joined.slice(0, 400));
	const assistantText = await page.locator('.crusorai-assistant-message').last().innerText();
	check('delivery summary remains in the assistant response',
		/Engineering Execution Report|Verdict|COMPLETED/i.test(assistantText), assistantText.slice(0, 300));
	check('engineering completed', /COMPLETED/i.test(assistantText), assistantText.slice(0, 300));
	const hiddenCards = await page.evaluate(() => ({
		verification: document.querySelectorAll('.crusorai-agent-card.is-verification').length,
		delivery: document.querySelectorAll('.crusorai-agent-card.is-delivery').length,
		cost: document.querySelectorAll('.crusorai-agent-card.is-cost').length,
	}));
	check('no dedicated verification card',
		hiddenCards.verification === 0, JSON.stringify(hiddenCards));
	check('no dedicated delivery card',
		hiddenCards.delivery === 0, JSON.stringify(hiddenCards));
	check('no dedicated cost card',
		hiddenCards.cost === 0, JSON.stringify(hiddenCards));
	const liveOrder = await page.evaluate(() => {
		const section = [...document.querySelectorAll('.crusorai-assistant-message')].pop();
		if (!section) { return null; }
		return [...section.querySelectorAll('[data-component="text-part"], .crusorai-agent-card')]
			.map(node => node.classList.contains('crusorai-agent-card')
				? `card:${node.dataset.cardType}`
				: 'text');
	});
	const firstCard = liveOrder ? liveOrder.findIndex(item => item.startsWith('card:')) : -1;
	const lastText = liveOrder ? liveOrder.lastIndexOf('text') : -1;
	check('final assistant response follows the execution cards',
		liveOrder !== null && firstCard >= 0 && lastText > firstCard
		&& liveOrder[liveOrder.length - 1] === 'text', JSON.stringify(liveOrder));
	check('requested file exists', fs.existsSync(path.join(workspace, 'notes.md')));

	const ledgerFile = path.join(appData, 'finops', 'provider_invocations.jsonl');
	const invocations = fs.existsSync(ledgerFile)
		? fs.readFileSync(ledgerFile, 'utf8').split(/\r?\n/).filter(Boolean).length
		: 0;
	check('no paid provider invocation', invocations === 0, `rows=${invocations}`);

	// ---- Failed + blocked -------------------------------------------------
	// A target nested under the existing notes.md file fails in the real
	// mutation path (filesystem error, not cancellation): the first DAG node
	// fails and the halted pipeline blocks the remaining node.
	await page.locator('.crusorai-composer-input').fill(failedPrompt);
	await page.locator('.crusorai-composer-input').press('Enter');
	// The mutation may ask for approval before it hits the filesystem error;
	// if it fails earlier, no dock appears and the plan is still the proof.
	try {
		await page.waitForSelector('[data-approve-once]', { timeout: 20_000 });
		await page.locator('[data-approve-once]').first().click({ timeout: 10_000 });
	} catch { /* failed before any approval request */ }
	await page.waitForFunction(() => {
		const cards = [...document.querySelectorAll('.crusorai-agent-card.is-plan')];
		return cards.some(card => card.querySelector('.crusorai-agent-card-step.is-failed'));
	}, null, { timeout: 180_000 });
	await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 120_000 });
	await page.waitForTimeout(800);
	await shot('05-failed-blocked.png');
	const failedPlan = await planCounts();
	check('failed task displays as failed', failedPlan.failed >= 1, JSON.stringify(failedPlan));
	check('blocked task displays as blocked', failedPlan.blocked >= 1, JSON.stringify(failedPlan));
	check('failed run claims no completion',
		failedPlan.completed === 0 && failedPlan.total > 0, JSON.stringify(failedPlan));

	// ---- Cancelled --------------------------------------------------------
	// The approval wait is a real, stable pause: Stop abandons it, and the
	// interrupted + unrun nodes are recorded cancelled.
	await page.locator('.crusorai-composer-input').fill(cancelledPrompt);
	await page.locator('.crusorai-composer-input').press('Enter');
	await page.waitForSelector('[data-approve-once]', { timeout: 120_000 });
	await page.locator('.crusorai-send-stop').click();
	await page.waitForFunction(() => {
		const cards = [...document.querySelectorAll('.crusorai-agent-card.is-plan')];
		return cards.some(card => card.querySelector('.crusorai-agent-card-step.is-cancelled'));
	}, null, { timeout: 60_000 });
	await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 60_000 });
	await page.waitForTimeout(800);
	await shot('06-cancelled.png');
	const cancelledPlan = await planCounts();
	check('cancelled tasks display as cancelled',
		cancelledPlan.cancelled >= 1 && cancelledPlan.completed === 0 && cancelledPlan.failed === 0,
		JSON.stringify(cancelledPlan));

	// Reload: the journaled progress cards must come back with the transcript,
	// each attached to the turn that produced it.
	await reloadAndOpen();
	await shot('05-after-reload.png');

	const restoredCards = await page.locator('.crusorai-agent-card').allInnerTexts();
	const restored = restoredCards.join('\n');
	check('activity card restored after reload', /Delivered|Understanding request|Implementing|Planning/i.test(restored), restored.slice(0, 300));
	check('plan card restored after reload', await page.locator('.crusorai-agent-card.is-plan').count() > 0, restored.slice(0, 300));
	const restoredOutcomes = await allPlanCounts();
	check('completed state survives reload', restoredOutcomes.completed >= 1, JSON.stringify(restoredOutcomes));
	check('failed state survives reload', restoredOutcomes.failed >= 1, JSON.stringify(restoredOutcomes));
	check('blocked state survives reload', restoredOutcomes.blocked >= 1, JSON.stringify(restoredOutcomes));
	check('cancelled state survives reload', restoredOutcomes.cancelled >= 1, JSON.stringify(restoredOutcomes));
	const restoredText = await page.locator('.crusorai-assistant-message').allInnerTexts();
	check('conversation restored after reload', restoredText.some(t => /Engineering Execution Report|notes\.md/i.test(t)), JSON.stringify(restoredText).slice(0, 300));

	// Per-turn ownership in the restored transcript.
	const ownership = await turnOwnership();
	report.turns = ownership;
	check('three restored turns carry distinct ids',
		ownership.length === 3 && new Set(ownership.map(turn => turn.turnId)).size === 3,
		JSON.stringify(ownership.map(turn => turn.turnId)));
	check('every card belongs to its own turn',
		ownership.every(turn => turn.cardIds.every(id => id.startsWith(`${turn.turnId}:`))),
		JSON.stringify(ownership.map(turn => ({ turnId: turn.turnId, cardIds: turn.cardIds }))));
	check('each turn owns exactly one plan card',
		ownership.length === 3 && ownership.every(turn => turn.plans.length === 1),
		JSON.stringify(ownership.map(turn => turn.plans.length)));
	const planStatuses = ownership.map(turn => turn.plans[0]?.steps ?? []);
	check('turn 1 plan shows completion',
		(planStatuses[0]?.length ?? 0) > 0 && planStatuses[0].every(status => status === 'completed'),
		JSON.stringify(planStatuses[0]));
	check('turn 2 plan shows failed and blocked',
		(planStatuses[1]?.includes('failed') ?? false) && (planStatuses[1]?.includes('blocked') ?? false),
		JSON.stringify(planStatuses[1]));
	check('turn 3 plan shows cancelled',
		(planStatuses[2]?.length ?? 0) > 0 && planStatuses[2].every(status => status === 'cancelled'),
		JSON.stringify(planStatuses[2]));

	const hiddenAfterReload = await page.evaluate(() => ({
		verification: document.querySelectorAll('.crusorai-agent-card.is-verification').length,
		delivery: document.querySelectorAll('.crusorai-agent-card.is-delivery').length,
		cost: document.querySelectorAll('.crusorai-agent-card.is-cost').length,
	}));
	check('historical verification cards stay hidden',
		hiddenAfterReload.verification === 0, JSON.stringify(hiddenAfterReload));
	check('historical delivery cards stay hidden',
		hiddenAfterReload.delivery === 0, JSON.stringify(hiddenAfterReload));
	check('historical cost cards stay hidden',
		hiddenAfterReload.cost === 0, JSON.stringify(hiddenAfterReload));
	const restoredOrder = await page.evaluate(() =>
		[...document.querySelectorAll('.crusorai-assistant-message[data-turn-id]')].map(section => ({
			turnId: section.dataset.turnId ?? '',
			order: [...section.querySelectorAll('[data-component="text-part"], .crusorai-agent-card')]
				.map(node => node.classList.contains('crusorai-agent-card')
					? `card:${node.dataset.cardType}`
					: 'text'),
		})));
	check('each restored turn keeps its final answer after its cards',
		restoredOrder.length === 3 && restoredOrder.every(turn => {
			const first = turn.order.findIndex(item => item.startsWith('card:'));
			const last = turn.order.lastIndexOf('text');
			return first >= 0 && last > first && turn.order[turn.order.length - 1] === 'text';
		}), JSON.stringify(restoredOrder));

	// Repeated hydration is idempotent: same turns, same cards, no duplicates.
	await reloadAndOpen();
	const ownershipAgain = await turnOwnership();
	check('repeated hydration keeps one card per turn',
		JSON.stringify(ownershipAgain) === JSON.stringify(ownership),
		JSON.stringify(ownershipAgain));

	// Full application restart (not just a reload) with the same profile.
	await relaunchApp();
	await page.waitForFunction(
		() => document.querySelectorAll('.crusorai-assistant-message[data-turn-id]').length >= 3,
		null, { timeout: 90_000 },
	);
	await page.waitForTimeout(3000);
	await shot('07-restarted.png');
	const ownershipRestart = await turnOwnership();
	report.restartedTurns = ownershipRestart;
	check('three turns restore after application restart', ownershipRestart.length === 3,
		JSON.stringify(ownershipRestart.map(turn => turn.turnId)));
	check('restart keeps every card in its own turn',
		JSON.stringify(ownershipRestart) === JSON.stringify(ownership),
		JSON.stringify(ownershipRestart));

	fs.writeFileSync(path.join(evidence, 'progress-result.json'), JSON.stringify({ ...report, cards }, null, 2));
	report.verdict = Object.values(report.checks).every(c => c.pass) ? 'PASS' : 'PARTIAL';
} catch (error) {
	report.error = String(error?.stack ?? error);
	report.verdict = 'FAIL';
	try { if (page) { await shot('99-failure.png'); } } catch { /* ignore */ }
} finally {
	fs.writeFileSync(path.join(evidence, 'acceptance.json'), JSON.stringify(report, null, 2));
	try { if (browser) { await browser.close(); } } catch { /* ignore */ }
	try { proc.kill(); } catch { /* ignore */ }
	fs.closeSync(out);
}

console.log(JSON.stringify({ verdict: report.verdict, checks: report.checks, stages: report.stages, error: report.error }, null, 2));
process.exit(report.verdict === 'PASS' ? 0 : 1);
