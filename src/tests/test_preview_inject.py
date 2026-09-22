"""Crusor Preview — injection pins.

The overlay only reaches the page the agent built because the proxy rewrites the document on its
way through, so these tests are about the two ways that rewrite can go wrong silently:

* an **idempotency** mistake double-injects and the user sees two wireframes, two labels, and two
  fix panels — the feature looks broken rather than duplicated;
* a **place-holder** mistake drops the `<base href>` that keeps a proxied page's relative assets
  resolving to the dev server. The frame goes blank, which reads as "the preview is broken" and
  not as "one tag is missing".

The comment case is real: our own fixture page documents the injection, and the first version of
``insert_base`` found ``<base href>`` inside that comment and concluded the page already had one.
"""
from __future__ import annotations

from pathlib import Path

from src.preview.inject import (
    INJECT_MARKER,
    has_overlay,
    inject_overlay,
    insert_base,
    is_html,
    relax_csp_meta,
)

DOC = (
	"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\" />\n"
	"<title>t</title>\n<link rel=\"stylesheet\" href=\"styles.css\" />\n</head>\n"
	"<body><h1>hi</h1><script src=\"app.js\"></script></body>\n</html>"
)
OVERLAY = "/crusor-preview/overlay/crusor-preview-overlay.js"


def test_overlay_script_lands_in_head_before_page_assets() -> None:
	out = inject_overlay(DOC, overlay_src=OVERLAY)
	head_end = out.index("</head>")
	assert out.index(f'id="{INJECT_MARKER}"') < head_end
	assert out.index(f'id="{INJECT_MARKER}"') < out.index("styles.css")
	assert "app.js" in out                      # the page's own scripts survive
	assert "defer" in out.split(f'id="{INJECT_MARKER}"')[1][:200]


def test_injection_is_idempotent() -> None:
	once = inject_overlay(DOC, overlay_src=OVERLAY)
	twice = inject_overlay(once, overlay_src=OVERLAY)
	assert once == twice
	assert once.count(f'id="{INJECT_MARKER}"') == 1
	assert has_overlay(once) and not has_overlay(DOC)


def test_config_blob_is_escaped_and_inert() -> None:
	out = inject_overlay(DOC, overlay_src=OVERLAY, config={"target": "</script><script>x()</script>", "kind": "url"})
	assert "</script><script>x()" not in out
	assert "<\\/script>" in out
	assert '"kind":"url"' in out


def test_insert_base_when_absent() -> None:
	out = insert_base(DOC, "/p/tok/")
	assert 'data-crusor-preview-base' in out
	assert out.index("data-crusor-preview-base") < out.index("styles.css")


def test_insert_base_ignores_a_base_mentioned_in_a_comment() -> None:
	# The exact false positive that shipped in the first draft, caught by our own fixture page.
	page = "<head><!-- the proxy injects the overlay and a `<base href>`; nothing here knows --><title>x</title></head>"
	out = insert_base(page, "/p/tok/")
	assert "data-crusor-preview-base" in out, "a documentation comment is not a <base> tag"


def test_insert_base_respects_an_existing_tag() -> None:
	page = '<head><base href="https://cdn.example.com/"><title>x</title></head>'
	out = insert_base(page, "/p/tok/")
	assert out.count("<base") == 1
	assert 'href="https://cdn.example.com/"' in out, "the project's own base wins"


def test_base_survives_a_headless_document() -> None:
	# Fragments and framework templates sometimes arrive without <head>/<html>.
	out = insert_base("<h1>hi</h1>", "/p/tok/")
	assert "data-crusor-preview-base" in out
	assert out.index("data-crusor-preview-base") < out.index("<h1>")


def test_relax_csp_widens_script_src_only() -> None:
	page = (
		'<head><meta http-equiv="Content-Security-Policy" '
		'content="default-src \'self\'; script-src \'self\'; style-src \'unsafe-inline\'"></head>'
	)
	out = relax_csp_meta(page, script_src="http://127.0.0.1:8931")
	assert "script-src 'self' http://127.0.0.1:8931" in out
	assert "style-src 'unsafe-inline'" in out, "unrelated directives are left alone"
	assert "default-src 'self'" in out


def test_relax_csp_never_adds_unsafe_inline() -> None:
	out = relax_csp_meta('<meta http-equiv="Content-Security-Policy" content="script-src \'self\'">',
						 script_src="http://127.0.0.1:8931")
	assert "'unsafe-inline'" not in out


def test_relax_csp_leaves_pages_without_a_policy_alone() -> None:
	page = "<head><title>x</title></head>"
	assert relax_csp_meta(page, script_src="http://127.0.0.1:8931") == page


def test_is_html_believes_the_content_type_first_and_sniffs_when_it_must() -> None:
	assert is_html("text/html; charset=utf-8")
	assert is_html("application/xhtml+xml")
	assert not is_html("application/json")
	assert not is_html("text/css")
	assert is_html(None, b"\n  <!DOCTYPE html>\n<html>")
	assert is_html("application/octet-stream", b"<html lang=en>")
	assert not is_html(None, b"\x89PNG\r\n\x1a\n")


def test_inject_overlay_serves_the_real_desktop_asset_from_disk() -> None:
	"""The overlay the proxy hands out must be the file the workbench ships, or the demo lies."""
	root = Path(__file__).resolve().parents[2]
	overlay = root / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "media" / "crusor-preview" / "overlay" / "crusor-preview-overlay.js"
	assert overlay.is_file(), f"missing overlay asset: {overlay}"
	source = overlay.read_text(encoding="utf-8")
	assert "crusor-preview-overlay" in source
	assert "__crusorPreviewOverlay" in source
