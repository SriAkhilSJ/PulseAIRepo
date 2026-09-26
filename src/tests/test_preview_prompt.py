"""Crusor Preview — the scoped turn text.

This is the module where the feature either works or quietly does nothing. A preview turn is an
ordinary bridge ``prompt`` frame, so the ONLY thing that makes the agent edit the clicked element
instead of repainting the page is the text: it has to name the element, give the agent something
grep-able to search for, state the scope, and stay inside the prompt budget. Each test below pins
one of those, because each of them has a plausible-looking failure mode:

* dropping the fingerprint leaves a selector that no source file contains (``:nth-of-type`` in a
  DOM tree is runtime state; it is not text in a ``.tsx`` file);
* dropping the instruction paraphrase rule makes the agent "improve" instead of "do as asked";
* dropping truncation turns a 30-click session into a request the provider refuses;
* dropping the batch receipt breaks the renderer card, which then shows a bare grey prompt.
"""
from __future__ import annotations

import json

import pytest

from src.preview.prompt import (
    MAX_PROMPT_CHARS,
    PREVIEW_PROMPT_MARKER,
    build_preview_prompt,
    build_prompt_frame,
    describe_element,
    summarize_batch,
)


def element(selector: str = '[data-testid="nav-cta"]', **overrides) -> dict:
	base = {
		"tag": "button",
		"classes": ["btn", "btn-primary"],
		"text": "Get started",
		"selector": selector,
		"xpath": "/html[1]/body[1]/header[1]/div[2]/button[2]",
		"outerHtml": '<button class="btn btn-primary" data-testid="nav-cta">Get started</button>',
		"styles": {"background-color": "rgb(79, 70, 229)", "border-radius": "10px", "font-size": "14.5px"},
		"fingerprint": {
			"tag": "button",
			"classes": ["btn", "btn-primary"],
			"text": "Get started",
			"attrs": [{"name": "data-testid", "value": "nav-cta"}],
		},
		"rect": {"x": 1180, "y": 14, "width": 108, "height": 38},
		"viewport": {"width": 1440, "height": 900, "dpr": 1},
	}
	base.update(overrides)
	return base


def batch(*fixes: dict, **overrides) -> dict:
	payload = {
		"sessionId": "s-1",
		"target": "http://127.0.0.1:5173/",
		"targetLabel": "aurora-landing · dev server",
		"kind": "url",
		"viewport": "desktop",
		"createdAt": "2026-09-22T10:00:00Z",
		"fixes": list(fixes),
	}
	payload.update(overrides)
	return payload


def fix(instruction: str, **element_overrides) -> dict:
	return {
		"id": "fix_1",
		"order": 1,
		"instruction": instruction,
		"label": '<button> "Get started"',
		"element": element(**element_overrides),
	}


def test_prompt_names_the_element_three_ways() -> None:
	text = build_preview_prompt(batch(fix("make it rounded, blue and bigger")))
	assert PREVIEW_PROMPT_MARKER in text
	# 1. human label, 2. CSS selector, 3. grep-able fingerprint — the agent needs all three: the
	# label to know what the user meant, the selector to be unambiguous, the fingerprint to find it.
	assert '<button> "Get started"' in text
	assert 'selector: [data-testid="nav-cta"]' in text
	assert "fingerprint: classes=btn btn-primary" in text
	assert 'text="Get started"' in text
	assert 'attrs=data-testid="nav-cta", type="button"' not in text, "only attrs the DOM actually had"
	assert 'data-testid="nav-cta"' in text


def test_instruction_is_verbatim_and_scope_is_explicit() -> None:
	text = build_preview_prompt(batch(fix("make the CTA blue, not indigo — client asked")))
	assert "instruction: make the CTA blue, not indigo — client asked" in text
	assert "change ONLY the named elements" in text
	assert "grep the classes, the text, the data attributes" in text
	# The close was re-worded after two live runs (2026-09-26, harness runs 7 and 8) spent their whole
	# budget in a self-invented verification ritual: run 7 blocked on `npx serve`, run 8 was refused it,
	# correctly switched to start_terminal, and was still polling when the budget ran out. The old
	# wording ("re-render the preview so the change can be checked") could be read as an instruction to
	# render — i.e. to start something. The prompt now bounds verification explicitly.
	assert text.rstrip().endswith("and the user sees the result in place.")
	assert "Do not start a dev server, watcher, or any other long-running process" in text
	assert "re-read the lines you changed" in text


def test_source_hint_appears_when_the_project_stamps_source_positions() -> None:
	stamped = element()
	stamped["fingerprint"]["source"] = {"file": "src/components/Nav.tsx", "line": 18, "component": "Nav"}
	text = build_preview_prompt(batch({
		"id": "fix_1", "instruction": "make it blue", "label": "<button>", "element": stamped,
	}))
	assert "source: src/components/Nav.tsx → line 18 → component Nav" in text


def test_geometry_and_styles_are_carried_for_layout_fixes() -> None:
	text = build_preview_prompt(batch(fix("center it and give it more spacing")))
	assert "box: 108×38 at (1180,14) · viewport 1440×900" in text
	assert "styles: background-color: rgb(79, 70, 229); border-radius: 10px; font-size: 14.5px" in text


def test_empty_or_blank_batches_produce_nothing() -> None:
	assert build_preview_prompt(batch()) == ""
	assert build_preview_prompt(batch(fix("   "))) == ""
	assert build_preview_prompt({}) == ""


def test_a_long_session_is_bounded_by_visible_truncation() -> None:
	# 40 fixes of ~1.5k each would blow the provider's budget; the drop must be stated in the prompt.
	fixes = [fix(f"fix number {index} with a fairly long instruction " + "detail " * 60) for index in range(40)]
	text = build_preview_prompt(batch(*fixes))
	assert len(text) <= MAX_PROMPT_CHARS + 400, "stays near the cap"
	assert "further fix" in text and "left out" in text, "the agent (and the user) must see what was dropped"
	assert text.strip().startswith(f"<!-- {PREVIEW_PROMPT_MARKER}")


def test_marker_count_matches_the_fixes_actually_included() -> None:
	fixes = [fix(f"fix {index} " + "detail " * 60) for index in range(30)]
	text = build_preview_prompt(batch(*fixes))
	header_count = int(text.split("count=")[1].split(" ")[0].rstrip("->"))
	included = text.count("\nFix ")
	assert included <= header_count
	assert included >= 1


def test_summary_and_element_labels_read_like_the_ui() -> None:
	assert describe_element(element()) == '<button> "Get started"'
	assert describe_element({"tag": "div", "classes": ["card"], "text": ""}) == "<div> .card"
	assert describe_element({"tag": "span"}) == "<span>"
	assert summarize_batch(batch(fix("a"), fix("b"))) == "2 preview fixes · aurora-landing · dev server"
	assert summarize_batch(batch()) == "0 preview fixes · aurora-landing · dev server"


def test_frame_is_a_plain_protocol_v2_prompt_with_a_receipt() -> None:
	frame = build_prompt_frame(batch(fix("make it blue")), session_id="s-1", workspace="/ws", mode="agent")
	assert frame["type"] == "prompt", "a preview turn is an ordinary prompt: no protocol change"
	assert frame["session_id"] == "s-1"
	assert frame["mode"] == "agent"
	assert frame["text"].startswith(f"<!-- {PREVIEW_PROMPT_MARKER}")
	assert frame["preview_batch"]["count"] == 1
	assert frame["preview_batch"]["target_label"] == "aurora-landing · dev server"
	assert frame["preview_batch"]["kind"] == "url"
	assert "reasoning_effort" not in frame
	assert json.dumps(frame), "the frame must be JSON-serialisable for the bridge"


def test_frame_names_the_workspace_the_bridge_requires() -> None:
	"""`prompt` is in the bridge's `_WORKSPACE_REQUIRED_METHODS`, so a frame without this is refused.

	The parameter is required (not defaulted) because the alternative shipped: a call site omitted it
	and every *Send to Crusor* would have ended in `workspace required: open a project folder…`.
	"""
	frame = build_prompt_frame(batch(fix("a")), session_id="s", workspace="/home/me/project")
	assert frame["workspace"] == "/home/me/project"
	with pytest.raises(TypeError):
		build_prompt_frame(batch(fix("a")), session_id="s")  # type: ignore[call-arg]
	with pytest.raises(ValueError, match="workspace"):
		build_prompt_frame(batch(fix("a")), session_id="s", workspace="   ")


def test_frame_carries_reasoning_effort_when_asked() -> None:
	frame = build_prompt_frame(batch(fix("a")), session_id="s", workspace="/ws", reasoning_effort="high")
	assert frame["reasoning_effort"] == "high"


def test_frame_refuses_an_empty_batch() -> None:
	with pytest.raises(ValueError, match="empty"):
		build_prompt_frame(batch(), session_id="s", workspace="/ws")
