"""Crusor Preview — the cross-language contract, and the headless half of the browser code.

The preview flow crosses three languages and two window boundaries, and every seam is a string:

    workbench (TypeScript) --'crusor-preview-workbench'--> preview window (JS)
    preview window --'crusor-preview-host'--> overlay (JS, inside the AGENT'S OWN PAGE)
    overlay --'crusor-preview-overlay'--> preview window --'crusor-preview-window'--> workbench

None of those messages can be type-checked across the boundary, and the overlay cannot import
anything at all: it is injected into a page the user may have written with any framework. A typo
in one literal is a feature that silently does nothing — a hover that never paints, a Review button
that never hands the batch over. So the literals are pinned here against the TypeScript contract,
in both directions, and the pure halves are executed through node.

Also pinned, because it is a product decision and not a style preference: the chrome uses real SVG
sprites (never emoji), and its colors come from derived tokens (never a palette written by hand
into the CSS).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.preview.prompt import build_preview_prompt

ROOT = Path(__file__).resolve().parents[2]
CRUSORAI = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"
TS_CONTRACT = CRUSORAI / "common" / "crusorAIPreview.ts"
MEDIA = CRUSORAI / "browser" / "media" / "crusor-preview"
OVERLAY = MEDIA / "overlay" / "crusor-preview-overlay.js"
WINDOW_JS = MEDIA / "preview.js"
WINDOW_HTML = MEDIA / "index.html"
WINDOW_CSS = MEDIA / "preview.css"

TS_SERVICE = CRUSORAI / "browser" / "crusorAIPreviewService.ts"

NODE = shutil.which("node")

EMOJI = re.compile(
	"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2B00-\u2BFF\uFE0F]"
)


def read(path: Path) -> str:
	assert path.is_file(), f"missing file: {path}"
	return path.read_text(encoding="utf-8")


def ts_object(name: str) -> dict[str, str]:
	"""Parse `export const Name = { Key: 'value', ... } as const;` out of the TypeScript contract."""
	source = read(TS_CONTRACT)
	block = source.split(f"export const {name} = {{", 1)[1].split("} as const;", 1)[0]
	return dict(re.findall(r"(\w+):\s*'([^']+)'", block))


def test_typescript_contract_owns_the_message_names() -> None:
	sources = ts_object("CrusorPreviewSource")
	assert sources == {
		"Overlay": "crusor-preview-overlay",
		"OverlayHost": "crusor-preview-host",
		"Workbench": "crusor-preview-workbench",
		"Window": "crusor-preview-window",
	}
	assert set(ts_object("CrusorPreviewOverlayCommand")) == {
		"Configure", "Inspect", "Pins", "ClearPins", "Flash", "ClosePanel",
	}
	assert set(ts_object("CrusorPreviewOverlayEvent")) == {"Ready", "Inspect", "Selected", "Fix", "PinClick"}
	assert set(ts_object("CrusorPreviewWindowCommand")) == {
		"Configure", "Theme", "SetTarget", "Inspect", "AgentApplied", "Toast",
	}
	assert set(ts_object("CrusorPreviewWindowEvent")) == {
		"Ready", "Navigate", "ThemeApplied", "Inspect", "ElementSelected", "FixAdded",
		"OverlayReady", "ReviewOpen", "ReviewClose", "ReviewSubmit", "OpenSource", "CloseRequest", "Viewport",
	}


def test_overlay_and_window_speak_the_same_protocol() -> None:
	sources = ts_object("CrusorPreviewSource")
	overlay = read(OVERLAY)
	window = read(WINDOW_JS)

	# The overlay is injected into a page we do not own, so it identifies itself by literal.
	assert f"'{sources['Overlay']}'" in overlay, "the overlay must identify its own messages"
	assert f"'{sources['OverlayHost']}'" in overlay, "the overlay must only obey its host"
	assert "postMessage" in overlay and "addEventListener('message'" in overlay

	# The preview window both obeys the workbench and commands the overlay.
	assert f"'{sources['OverlayHost']}'" in window
	assert f"'{sources['Overlay']}'" in window
	assert f"'{sources['Workbench']}'" in window
	assert f"'{sources['Window']}'" in window


def test_overlay_command_set_matches_the_contract() -> None:
	commands = set(re.findall(r"case '([a-z-]+)':", read(OVERLAY).split("Overlay.prototype.command", 1)[1]))
	assert commands == set(ts_object("CrusorPreviewOverlayCommand").values()), (
		"every command the window may send must be a case in the overlay's switch, and nothing else"
	)


def test_overlay_event_set_matches_the_contract() -> None:
	emitted = set(re.findall(r"\.emit\('([a-zA-Z-]+)'", read(OVERLAY)))
	emitted.discard("ready")
	assert emitted | {"ready"} == set(ts_object("CrusorPreviewOverlayEvent").values()), emitted


def test_window_events_and_commands_match_the_contract() -> None:
	window = read(WINDOW_JS)
	posted = set(re.findall(r"postToHost\('([a-zA-Z-]+)'", window))
	# ready, plus everything the workbench must hear about.
	assert posted <= set(ts_object("CrusorPreviewWindowEvent").values()), posted - set(ts_object("CrusorPreviewWindowEvent").values())
	assert {"review-submit", "open-source", "close-request", "fix-added"} <= posted

	handled = set(re.findall(r"case '([a-z-]+)':", window.split("data.source === 'crusor-preview-workbench'", 1)[1]))
	assert handled == set(ts_object("CrusorPreviewWindowCommand").values()), (
		"the window must handle exactly the commands the workbench may send"
	)


def test_viewport_presets_match_the_type_union() -> None:
	source = read(TS_CONTRACT)
	preset_table = read(WINDOW_JS).split("var VIEWPORTS = {", 1)[1].split("\n\t};", 1)[0]
	presets = set(re.findall(r"(\w+):\s*\{", preset_table))
	assert presets == {"responsive", "desktop", "tablet", "phone"}, presets
	for preset in presets:
		assert f"'{preset}'" in source, f"viewport {preset} missing from the TypeScript contract"
	assert 'CrusorPreviewViewport =' in source


def test_the_chrome_is_svg_only() -> None:
	"""Product requirement: real SVG icons, never emoji glyphs standing in for them."""
	for path in (WINDOW_HTML, WINDOW_CSS, WINDOW_JS, OVERLAY):
		text = read(path)
		found = EMOJI.findall(text)
		assert not found, f"{path.name} contains emoji/non-icon glyphs: {found[:5]}"

	html = read(WINDOW_HTML)
	sprite_ids = set(re.findall(r'<symbol id="([^"]+)"', html))
	used = set(re.findall(r'<use href="#([^"]+)"', html)) | set(re.findall(r"'#([\w-]+)'", read(WINDOW_JS)))
	missing = {symbol for symbol in used if symbol.startswith(("cp-i-", "wb-i-"))} - sprite_ids
	assert not missing, f"icons referenced but not defined in the sprite: {missing}"
	assert len(sprite_ids) >= 12, "the toolbar needs a real icon set"


def test_colors_come_from_derived_tokens_not_a_hand_written_palette() -> None:
	css = read(WINDOW_CSS)
	head, _, body = css.partition(":root {")
	root_block = body.split("}", 1)[0]
	assert "--cp-accent: var(--crusorai-accent" in root_block
	assert "--cp-text: var(--crusorai-preview-text" in root_block
	# Seeds are allowed as var() fallbacks; outside the token block the only literals left are the
	# neutral canvas values a preview frame needs (a white page, a black scrim).
	outside = body.split("}", 1)[1]
	literals = set(re.findall(r"#[0-9a-fA-F]{3,8}\b", outside))
	assert literals <= {"#fff", "#000"}, f"hardcoded color outside the token block: {literals}"
	assert "var(--cp-" in outside, "the chrome must paint from its tokens"


def test_overlay_enforces_contrast_and_never_rewrites_the_page() -> None:
	overlay = read(OVERLAY)
	# The wireframe is the feature; on a white page a mid-grey accent vanishes without this math.
	for fn in ("contrastRatio", "ensureContrast", "backdropOf", "semanticColor", "wireColor"):
		assert re.search(rf"function {fn}\b|prototype\.{fn} = function", overlay), fn
	assert "WCAG" in overlay
	# It must not fight the page it is injected into for layout or styling.
	assert "<style>" in overlay or "textContent = STYLE" in overlay
	assert "document.write" not in overlay
	assert "attachShadow" in overlay, "host UI lives in a shadow root so page CSS cannot restyle it"
	assert "all:initial" in overlay


def test_overlay_paints_a_full_wireframe_not_a_single_box() -> None:
	overlay = read(OVERLAY)
	# Step 5 of the flow: the hovered element is FULLY wired — box + corner brackets + edge guides.
	assert "cp-hover-box" in overlay and "cp-corner" in overlay and "cp-guide" in overlay
	assert "paintCorners" in overlay
	# Step 6: click opens a panel anchored on the element, and step 7 accumulates fixes.
	assert "cp-panel" in overlay and "placePanel" in overlay
	assert "submitFix" in overlay and "cp-pin" in overlay


@pytest.mark.skipif(NODE is None, reason="node is required for the headless half of this contract")
def test_node_accepts_both_shipped_scripts() -> None:
	# The overlay is injected as classic script and the window chrome loads with `defer`: neither goes
	# through a bundler, so a syntax error is a blank preview window in production and nothing else.
	for path in (OVERLAY, WINDOW_JS):
		result = subprocess.run(
			[NODE, "--check", str(path)], capture_output=True, text=True,
			encoding="utf-8", errors="replace", timeout=60,
		)
		assert result.returncode == 0, f"{path.name}: {result.stderr}"


@pytest.mark.skipif(NODE is None, reason="node is required for the headless half of this contract")
def test_overlay_pure_helpers_behave_without_a_dom() -> None:
	# Loaded in a bare sandbox: the overlay must tolerate a document-less host (it is also required by
	# tooling), and its class filter must reject framework-mangled names that would make selectors brittle.
	harness = """
	const fs = require('fs'), vm = require('vm');
	const source = fs.readFileSync(process.argv[1], 'utf8');
	const sandbox = { console, module: { exports: {} }, setTimeout, clearTimeout, requestAnimationFrame(){} };
	sandbox.globalThis = sandbox;
	vm.createContext(sandbox);
	vm.runInContext(source, sandbox);
	const api = sandbox.__crusorPreviewOverlay;
	const out = {
		version: api.version,
		meaningful: [api.isMeaningfulClass('card'), api.isMeaningfulClass('css-1x2y3z'), api.isMeaningfulClass('hover:bg-blue-500')],
		hasDescribe: typeof api.describe === 'function',
		hasSelector: typeof api.buildSelector === 'function',
	};
	process.stdout.write(JSON.stringify(out));
	"""
	result = subprocess.run(
		[NODE, "--input-type=commonjs", "-e", harness, str(OVERLAY)],
		capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
	)
	assert result.returncode == 0, result.stderr
	payload = json.loads(result.stdout)
	assert payload["version"] == 1
	assert payload["meaningful"] == [True, False, False], "CSS-in-JS and utility-variant names are not selectors"
	assert payload["hasDescribe"] and payload["hasSelector"]


@pytest.mark.skipif(NODE is None, reason="node is required for the headless half of this contract")
def test_typescript_helpers_run_and_agree_with_the_python_prompt() -> None:
	"""The scoped prompt exists twice — engine-side (canonical) and renderer-side (so the composer can
	show the exact text before dispatch). They must agree on the fields that make the turn work."""
	batch = {
		"sessionId": "s-1",
		"target": "http://127.0.0.1:5173/",
		"targetLabel": "aurora-landing · dev server",
		"kind": "url",
		"viewport": "desktop",
		"fixes": [{
			"id": "fix_1", "order": 1, "instruction": "make it rounded, blue and bigger",
			"label": '<button> "Get started"',
			"element": {
				"selector": '[data-testid="nav-cta"]', "tag": "button", "classes": ["btn", "btn-primary"],
				"text": "Get started", "outerHtml": '<button class="btn btn-primary">Get started</button>',
				"styles": {"border-radius": "10px"},
				"fingerprint": {
					"tag": "button", "classes": ["btn"], "text": "Get started",
					"attrs": [{"name": "data-testid", "value": "nav-cta"}],
					"source": {"file": "src/components/Nav.tsx", "line": 18},
				},
				"rect": {"x": 1180, "y": 14, "width": 108, "height": 38},
				"viewport": {"width": 1440, "height": 900},
			},
		}],
	}
	harness = """
	import { pathToFileURL } from 'node:url';
	// A bare filesystem path is not a legal ESM specifier (it works on POSIX by accident and fails on
	// Windows with ERR_UNSUPPORTED_ESM_URL_SCHEME), so the path is converted rather than interpolated.
	const mod = await import(pathToFileURL(process.argv[1]).href);
	const batch = JSON.parse(process.argv[2]);
	const evidence = [
		{ kind: 'file', path: 'src/components/Hero.tsx' },
		{ kind: 'command', text: 'npm run dev\\n  ➜  Local: http://localhost:5173/' },
	];
	process.stdout.write(JSON.stringify({
		prompt: mod.buildPreviewPrompt(batch),
		availability: mod.detectPreviewAvailability(evidence),
		idle: mod.detectPreviewAvailability([{ kind: 'command', text: 'pytest -q' }]),
		describe: mod.describeFixElement(batch.fixes[0]),
		summary: mod.summarizeBatch(batch),
		empty: mod.isBatchEmpty({ target: 'x', fixes: [] }),
	}));
	"""
	result = subprocess.run(
		[NODE, "--experimental-strip-types", "--input-type=module", "-e",
		 harness.replace("process.argv[1]", json.dumps(str(TS_CONTRACT))).replace("process.argv[2]", json.dumps(json.dumps(batch)))],
		capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
	)
	assert result.returncode == 0, result.stderr
	payload = json.loads(result.stdout)

	python_prompt = build_preview_prompt(batch)
	ts_prompt = payload["prompt"]
	for field in (
		"<!-- crusor-preview:fix-batch count=1 -->",
		'make it rounded, blue and bigger',
		'selector: [data-testid="nav-cta"]',
		"change ONLY the named elements",
		'source: src/components/Nav.tsx → line 18',
		# Run 8: the turn must not become a self-invented verification ritual. The sentence exists in
		# both copies, and the TS copy is what the composer shows before dispatch, so drift would show
		# the user a prompt the engine does not send.
		'Do not start a dev server, watcher, or any other long-running process',
		"box: 108×38 at (1180,14)",
	):
		assert field in ts_prompt, f"missing from the TypeScript prompt: {field}"
		assert field in python_prompt, f"missing from the Python prompt: {field}"

	assert payload["availability"]["reason"] == "dev-server"
	# The live target wins over the file: a running dev server is what the user should be looking at.
	assert payload["availability"]["url"] == "http://localhost:5173/"
	assert payload["availability"]["label"] == "dev server · 5173"
	assert payload["idle"]["available"] is False, "a non-server command must not offer a preview"
	assert payload["describe"] == '<button> "Get started"'
	assert payload["summary"] == "1 preview fix · aurora-landing · dev server"
	assert payload["empty"] is True

@pytest.mark.skipif(NODE is None, reason="node is required for the headless half of this contract")
def test_the_preview_window_query_is_a_list_of_pairs() -> None:
	"""The window URL is assembled from pairs and percent-encoded, and nothing pinned the value until
	now: `typecheck-client` caught the annotation (pairs assigned to `string[]`, which type-erases into
	a working URL and therefore never failed at runtime) but the encoding and the trimmed origin were
	only ever verified by hand."""
	harness = """
	import { pathToFileURL } from 'node:url';
	const mod = await import(pathToFileURL(process.argv[1]).href);
	const query = mod.previewWindowQuery(
		{ origin: 'http://127.0.0.1:8931/', secret: 's3cr3t/+&=' },
		{ target: 'http://localhost:5173/', mode: 'inspect' },
	);
	const parsed = new URLSearchParams(query);
	process.stdout.write(JSON.stringify({
		query,
		endpoint: parsed.get('endpoint'),
		secret: parsed.get('secret'),
		target: parsed.get('target'),
		mode: parsed.get('mode'),
		missing: parsed.get('dropped'),
	}));
	"""
	result = subprocess.run(
		[NODE, "--experimental-strip-types", "--input-type=module", "-e",
		 harness.replace("process.argv[1]", json.dumps(str(TS_CONTRACT)))],
		capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
	)
	assert result.returncode == 0, result.stderr
	payload = json.loads(result.stdout)

	assert payload["endpoint"] == "http://127.0.0.1:8931", "the trailing slash is trimmed before encoding"
	assert payload["secret"] == "s3cr3t/+&=", "reserved characters must survive the round trip"
	assert payload["target"] == "http://localhost:5173/"
	assert payload["mode"] == "inspect"
	assert payload["missing"] is None, "an absent key must not be emitted"
	# Keys are the literal `key=value` pairs, in order — a character-destructured bug turns this into `e=`/`n=`.
	assert payload["query"].startswith("endpoint=http%3A%2F%2F127.0.0.1%3A8931&secret=s3cr3t%2F%2B%26%3D&")
	assert "endpoint=" in payload["query"] and "n=d" not in payload["query"]


def test_the_batch_frame_names_its_workspace_in_both_languages() -> None:
	"""``prompt`` is a workspace-required bridge method, and the check runs per frame.

	The engine answers a workspace-less prompt with
	``workspace required: open a project folder before starting a Crusor session``. The workbench's
	own composer always sends one (``crusorAIRendererService.ts``: ``workspace: this.workspacePath``);
	the preview batch frame did not, so *Send to Crusor* would have failed on every use — a dead step 9
	that no other test in this suite could see, because the frame is assembled in TypeScript and the
	failure only happens inside a running engine. It was found by driving a real batch through a real
	bridge (``scripts/preview_batch_turn.py``).

	Both halves are pinned here: the Python builder refuses without a workspace, and the TypeScript
	service sends one — a source-level pin, because that file has no unit-test harness of its own.
	"""
	service = read(TS_SERVICE)
	# Isolate the frame literal inside sendBatchToAgent, so an unrelated `workspace` elsewhere in the
	# file cannot satisfy this.
	body = service.split("async sendBatchToAgent(", 1)[1].split("this.engine.send(", 1)[0]
	assert re.search(r"type:\s*'prompt'", body), "sendBatchToAgent no longer builds a prompt frame"
	assert re.search(r"^\s*workspace,\s*$", body, re.MULTILINE), (
		"the preview prompt frame must carry `workspace` — the bridge refuses a prompt without it"
	)
	assert "workspacePath" in body, "…and it must come from the service's P0 workspace resolution"
