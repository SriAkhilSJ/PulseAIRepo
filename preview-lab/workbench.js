/* Preview lab harness — the MOCK workbench side of the flow.
 *
 * Owns STEP 1 (the Agent UI shows "preview is available"), STEP 2 (a window appears) and
 * STEP 9 (the reviewed batch lands on the Agent). Everything it talks to on the other side of the
 * iframe boundary is the real product code:
 *   - media/crusor-preview/{index.html,preview.css,preview.js}  (the preview window)
 *   - media/crusor-preview/overlay/crusor-preview-overlay.js    (injected by the proxy)
 *   - src/preview/server.py                                     (proxy + injection)
 *   - src/preview/prompt.py                                     (the scoped turn text)
 * Only the model turn is mocked (preview-lab/mock_agent.py).
 */
(function () {
	"use strict";

	var doc = document;
	var agentPanel = doc.getElementById("wb-agent");
	var transcript = doc.getElementById("wb-transcript");
	var input = doc.getElementById("wb-input");
	var sendBtn = doc.getElementById("wb-send");
	var attachments = doc.getElementById("wb-attachments");
	var openPreviewBtn = doc.getElementById("wb-open-preview");
	var previewCtaText = doc.getElementById("wb-preview-cta-text");
	var previewCard = doc.getElementById("wb-preview-card");
	var previewCardSub = doc.getElementById("wb-preview-card-sub");
	var previewCardOpen = doc.getElementById("wb-preview-card-open");
	var pwin = doc.getElementById("wb-pwin");
	var pwinFrame = doc.getElementById("wb-pwin-frame");
	var pwinClose = doc.getElementById("wb-pwin-close");
	var resetBtn = doc.getElementById("wb-reset");
	var toastEl = doc.getElementById("wb-toast");
	var statusLeft = doc.getElementById("wb-status-left");
	var devUrlEl = doc.getElementById("wb-dev-url");
	var tabName = doc.getElementById("wb-tab-name");
	var sourceHint = doc.getElementById("wb-source-hint");
	var codeEl = doc.querySelector("#wb-code code");

	var lab = { proxy: "", demoApp: "", session: "lab-session", secret: "", token: "", previewUrl: "", batch: null };

	/* ── theme: the derived palette, pushed to the preview window exactly like the IDE does ── */
	function derivedTheme() {
		var style = getComputedStyle(doc.documentElement);
		var names = {
			accent: "--crusorai-accent",
			agent: "--crusorai-agent",
			verified: "--crusorai-verified",
			approval: "--crusorai-approval",
			failed: "--crusorai-failed",
		};
		var theme = {};
		Object.keys(names).forEach(function (key) {
			var value = style.getPropertyValue(names[key]).trim();
			if (value) { theme[key] = value; }
		});
		// Preview-window surfaces, derived from the same CrusorAI Dark seeds.
		theme.bg = style.getPropertyValue("--bg").trim();
		theme.surface = style.getPropertyValue("--surface").trim();
		theme.surfaceRaised = style.getPropertyValue("--surface-2").trim();
		theme.surfaceStrong = style.getPropertyValue("--surface-3").trim();
		theme.stage = "#050505";
		theme.text = style.getPropertyValue("--text").trim();
		theme.textWeak = style.getPropertyValue("--text-weak").trim();
		theme.textMicro = style.getPropertyValue("--text-faint").trim();
		theme.border = style.getPropertyValue("--border-strong").trim();
		theme.borderWeak = style.getPropertyValue("--border").trim();
		theme.onAccent = style.getPropertyValue("--on-accent").trim();
		theme.fontUi = style.getPropertyValue("--font-ui").trim();
		theme.fontMono = style.getPropertyValue("--font-mono").trim();
		theme.radius = style.getPropertyValue("--radius").trim();
		return theme;
	}

	function postToPreview(command, payload) {
		var frame = pwinFrame.contentWindow;
		if (!frame || pwin.hidden) { return; }
		var message = { source: "crusor-preview-workbench", command: command };
		Object.keys(payload || {}).forEach(function (key) { message[key] = payload[key]; });
		frame.postMessage(message, "*");
	}

	/* ── chrome helpers ────────────────────────────────────────────────────────────────── */
	function toast(message, tone) {
		toastEl.textContent = message;
		toastEl.setAttribute("data-tone", tone || "verified");
		toastEl.hidden = false;
		clearTimeout(toast._t);
		toast._t = setTimeout(function () { toastEl.hidden = true; }, 3200);
	}

	function setStatus(text) { statusLeft.textContent = text; }

	function el(tag, className, text) {
		var node = doc.createElement(tag);
		if (className) { node.className = className; }
		if (text !== undefined) { node.textContent = text; }
		return node;
	}

	function svgIcon(id) {
		var wrap = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
		var use = doc.createElementNS("http://www.w3.org/2000/svg", "use");
		use.setAttribute("href", "#" + id);
		wrap.appendChild(use);
		return wrap;
	}

	function toolCard(name, arg, state) {
		var row = el("div", "wb-tool" + (state === "running" ? " is-running" : ""));
		var label = el("span", "wb-tool-name");
		label.appendChild(svgIcon(name === "run" ? "wb-i-terminal" : "wb-i-file"));
		label.appendChild(el("span", null, name));
		row.appendChild(label);
		row.appendChild(el("span", "wb-tool-arg", arg));
		var status = el("span", "wb-tool-status" + (state === "ok" ? " is-ok" : ""));
		status.appendChild(svgIcon("wb-i-check"));
		row.appendChild(status);
		return row;
	}

	function scrollTranscript() { transcript.scrollTop = transcript.scrollHeight; }

	/* ── STEP 1: availability ──────────────────────────────────────────────────────────── */
	function setPreviewAvailable(on, label) {
		openPreviewBtn.setAttribute("data-state", on ? "on" : "off");
		previewCard.setAttribute("data-state", on ? "on" : "off");
		previewCtaText.textContent = on ? "Preview ready" : "Preview";
		openPreviewBtn.disabled = !on;
		previewCardOpen.disabled = !on;
		if (label) { previewCardSub.textContent = label; }
	}

	/* ── STEP 2: the window ────────────────────────────────────────────────────────────── */
	function openPreviewWindow() {
		if (!lab.previewUrl) { toast("No preview target yet", "failed"); return; }
		// Same URL shape the workbench builds: the window registers its own target, so it needs the
		// endpoint origin and the run secret (see crusorAIPreviewService.ts / preview.js).
		var ui = lab.proxy + "/crusor-preview/ui/" +
			"?endpoint=" + encodeURIComponent(lab.proxy) +
			"&secret=" + encodeURIComponent(lab.secret) +
			"&target=" + encodeURIComponent(lab.previewUrl) +
			"&label=" + encodeURIComponent(lab.label || lab.previewUrl) +
			"&kind=url&session=" + encodeURIComponent(lab.session);
		pwin.hidden = false;
		if (pwinFrame.getAttribute("src") !== ui) { pwinFrame.setAttribute("src", ui); }
		setStatus("preview window open · " + (lab.label || lab.previewUrl));
	}

	function closePreviewWindow() {
		pwin.hidden = true;
		setStatus("preview window closed");
	}

	openPreviewBtn.addEventListener("click", openPreviewWindow);
	previewCardOpen.addEventListener("click", openPreviewWindow);
	pwinClose.addEventListener("click", closePreviewWindow);

	/* ── STEP 9: the batch lands on the Agent ──────────────────────────────────────────── */
	function renderAttachments(batch) {
		attachments.textContent = "";
		var head = el("span", "wb-attachments-head");
		head.appendChild(svgIcon("wb-i-target"));
		head.appendChild(el("span", null, batch.fixes.length + (batch.fixes.length === 1 ? " preview fix" : " preview fixes") +
			" · from " + (batch.targetLabel || "the preview")));
		attachments.appendChild(head);
		batch.fixes.forEach(function (fix, index) {
			var row = el("div", "wb-attach");
			row.appendChild(el("span", "wb-attach-num", String(index + 1)));
			var main = el("div", "wb-attach-main");
			main.appendChild(el("span", "wb-attach-el", fix.label + " · " + (fix.element.selector || "no selector")));
			main.appendChild(el("span", "wb-attach-instr", fix.instruction));
			row.appendChild(main);
			attachments.appendChild(row);
		});
		attachments.hidden = false;
	}

	async function attachBatch(batch) {
		lab.batch = batch;
		renderAttachments(batch);
		agentPanel.classList.add("is-focused");
		setStatus("preview batch attached — review the prompt and send");
		// The prompt text is built by the REAL src/preview/prompt.py on the lab server.
		try {
			var response = await fetch("/lab/prompt", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ batch: batch, session_id: lab.session, mode: "agent" }),
			});
			var payload = await response.json();
			if (payload.ok) {
				input.value = payload.text;
				input.dataset.frame = JSON.stringify(payload.frame);
			} else {
				input.value = "(prompt builder failed: " + payload.error + ")";
			}
		} catch (error) {
			input.value = "(could not reach the lab prompt builder: " + error + ")";
		}
		input.focus();
		input.setSelectionRange(input.value.length, input.value.length);
		scrollTranscript();
		toast(batch.fixes.length + (batch.fixes.length === 1 ? " fix" : " fixes") + " attached to the Agent", "agent");
	}

	async function sendToAgent() {
		var text = input.value.trim();
		if (!text) { return; }
		var batch = lab.batch;
		input.value = "";
		attachments.hidden = true;
		agentPanel.classList.remove("is-focused");

		var userMsg = el("article", "wb-msg wb-msg-user");
		userMsg.appendChild(el("p", null, batch
			? "[Crusor Preview] " + batch.fixes.length + " fixes from the preview"
			: text.slice(0, 140)));
		transcript.appendChild(userMsg);

		var agentMsg = el("article", "wb-msg wb-msg-agent");
		transcript.appendChild(agentMsg);
		if (!batch) {
			agentMsg.appendChild(el("p", "wb-msg-copy", "(the lab only mocks preview batches — this turn goes nowhere)"));
			scrollTranscript();
			return;
		}

		setStatus("Crusor is applying " + batch.fixes.length + " fixes…");
		var running = toolCard("write_file", "preview-lab/.runtime/preview-overrides.css", "running");
		agentMsg.appendChild(running);
		scrollTranscript();

		var receipt;
		try {
			var response = await fetch("/lab/agent/apply", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ batch: batch, session_id: lab.session }),
			});
			receipt = await response.json();
		} catch (error) {
			receipt = { ok: false, summary: "mock agent unreachable: " + error, applied: [], unresolved: [], files_changed: [] };
		}

		running.classList.remove("is-running");
		running.querySelector(".wb-tool-status").classList.add("is-ok");

		(receipt.applied || []).forEach(function (fix) {
			agentMsg.appendChild(toolCard("edit", (fix.source || fix.selector) + " — " + fix.detail, "ok"));
		});
		(receipt.unresolved || []).forEach(function (fix) {
			agentMsg.appendChild(toolCard("unresolved", fix.selector + " — " + fix.detail, "idle"));
		});
		agentMsg.appendChild(el("p", "wb-msg-copy",
			(receipt.summary || "no changes") + (receipt.files_changed && receipt.files_changed.length
				? " · changed " + receipt.files_changed.join(", ")
				: "")));
		scrollTranscript();
		setStatus("turn done — " + (receipt.summary || "no changes"));

		// Back to the preview: reload, then flash what changed.
		postToPreview("agent-applied", {
			selector: (receipt.selectors && receipt.selectors[0]) || null,
			summary: "Crusor applied " + (receipt.applied || []).length + " of " + batch.fixes.length + " fixes",
		});
		lab.batch = null;
		toast(receipt.summary || "done", receipt.ok ? "verified" : "failed");
	}

	sendBtn.addEventListener("click", sendToAgent);
	input.addEventListener("keydown", function (event) {
		if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendToAgent(); }
	});

	/* ── open-source: jump the editor at the element's fingerprint ─────────────────────── */
	function openSource(element) {
		var stamped = element && element.fingerprint && element.fingerprint.source;
		var file = stamped && stamped.file ? stamped.file : guessSourceFile(element);
		tabName.textContent = file.split("/").pop();
		sourceHint.hidden = false;
		sourceHint.textContent = stamped && stamped.file
			? "mapped from data-crusor-source" + (stamped.line ? ":" + stamped.line : "")
			: "located by fingerprint (mock)";
		renderCode(file, element);
		setStatus("opened " + file + " — " + (element && element.selector ? element.selector : ""));
		toast("Opened " + file, "accent");
	}

	function guessSourceFile(element) {
		var classes = (element && element.classes) || [];
		var joined = classes.join(" ");
		if (/hero|eyebrow/.test(joined)) { return "src/components/Hero.tsx"; }
		if (/nav|brand/.test(joined)) { return "src/components/Nav.tsx"; }
		if (/card|feature/.test(joined)) { return "src/components/FeatureCard.tsx"; }
		if (/cta/.test(joined)) { return "src/components/CtaBand.tsx"; }
		if (/footer/.test(joined)) { return "src/components/Footer.tsx"; }
		if (/btn/.test(joined)) { return "src/components/Button.tsx"; }
		if (/stat/.test(joined)) { return "src/components/Stats.tsx"; }
		return "src/components/Page.tsx";
	}

	function renderCode(file, element) {
		var label = element ? (element.text || element.classes[0] || element.tag) : "";
		var lines = [
			'<span class="c">// ' + file + '</span>',
			'<span class="k">import</span> { <span class="t">Button</span> } <span class="k">from</span> <span class="s">"./Button"</span>;',
			"",
			'<span class="k">export function</span> <span class="t">' + componentName(file) + '</span>() {',
			"  <span class=\"k\">return</span> (",
			'    <span class="hl">&lt;section className="<span class="s">' + ((element && element.classes || []).join(" ") || "section") + '</span>"&gt;',
			'      &lt;h2 className="<span class="s">' + ((element && element.classes || [])[0] || "title") + '</span>"&gt;' +
				'<span class="s">' + escapeHtml(String(label).slice(0, 48)) + "</span>&lt;/h2&gt;",
			"      &lt;<span class=\"t\">Button</span> variant=<span class=\"s\">\"primary\"</span> /&gt;",
			"    &lt;/section&gt;",
			"  );",
			"}",
			"",
			'<span class="c">// Crusor Preview located this element by its DOM fingerprint:</span>',
			'<span class="c">//   selector  ' + escapeHtml((element && element.selector) || "-") + "</span>",
			'<span class="c">//   text      ' + escapeHtml(String((element && element.text) || "-").slice(0, 40)) + "</span>",
			'<span class="c">//   box       ' + (element && element.rect ? element.rect.width + "×" + element.rect.height : "-") + "</span>",
		];
		codeEl.innerHTML = lines.join("\n");
	}

	function componentName(file) {
		var base = file.split("/").pop().replace(/\.[^.]+$/, "");
		return base.charAt(0).toUpperCase() + base.slice(1);
	}

	function escapeHtml(value) {
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
	}

	/* ── reset ─────────────────────────────────────────────────────────────────────────── */
	resetBtn.addEventListener("click", async function () {
		try { await fetch("/lab/reset", { method: "POST" }); } catch (_) { /* lab offline */ }
		lab.batch = null;
		input.value = "";
		attachments.hidden = true;
		sourceHint.hidden = true;
		tabName.textContent = "Hero.tsx";
		renderCode("src/components/Hero.tsx", null);
		setStatus("demo reset — the mock agent's edits are cleared");
		postToPreview("set-target", { target: lab.previewUrl, label: lab.label, kind: "url" });
		toast("Demo reset", "accent");
	});

	/* ── inbound messages from the preview window ──────────────────────────────────────── */
	window.addEventListener("message", function (event) {
		var data = event && event.data;
		if (!data || data.source !== "crusor-preview-window") { return; }
		switch (data.type) {
			case "ready":
				postToPreview("configure", { theme: derivedTheme(), sessionId: lab.session });
				setStatus("preview window ready");
				break;
			case "navigate":
				setStatus("preview loaded " + (data.label || data.url || ""));
				break;
			case "inspect":
				setStatus(data.on ? "inspect armed — click any element in the preview" : "inspect off");
				break;
			case "element-selected":
				setStatus("selected " + (data.label || "element"));
				break;
			case "fix-added":
				setStatus(data.count + (data.count === 1 ? " fix" : " fixes") + " pending review");
				break;
			case "open-source":
				openSource(data.element);
				break;
			case "review-submit":
				attachBatch(data.batch);
				break;
			case "close-request":
				closePreviewWindow();
				break;
			default:
				break;
		}
	});

	/* ── boot ──────────────────────────────────────────────────────────────────────────── */
	async function boot() {
		renderCode("src/components/Hero.tsx", null);
		setPreviewAvailable(false, "waiting for the agent to build UI");
		setStatus("starting the lab…");
		try {
			var response = await fetch("/lab/state");
			var state = await response.json();
			lab.proxy = state.proxyOrigin;
			lab.demoApp = state.demoAppOrigin;
			lab.session = state.session || lab.session;
			lab.secret = state.secret || "";
			devUrlEl.textContent = state.demoAppOrigin.replace(/^https?:\/\//, "");

			var registered = await fetch(lab.proxy + "/crusor-preview/target", {
				method: "POST",
				headers: { "Content-Type": "application/json", "X-Crusor-Preview-Secret": lab.secret },
				body: JSON.stringify({ url: state.demoAppOrigin + "/", label: "aurora-landing · dev server", session_id: lab.session }),
			});
			var target = await registered.json();
			if (!target.ok) { throw new Error(target.error || "target registration failed"); }
			lab.token = target.token;
			lab.previewUrl = target.previewUrl;
			lab.label = target.label;
			setPreviewAvailable(true, target.label);
			setStatus("preview available — " + target.label);
			// The IDE opens the window when the user clicks; the lab does the same.
		} catch (error) {
			setStatus("lab failed to start: " + error);
			toast("Lab error: " + error, "failed");
		}
	}

	window.__crusorPreviewLab = { lab: lab, openPreviewWindow: openPreviewWindow, boot: boot };
	boot();
})();
