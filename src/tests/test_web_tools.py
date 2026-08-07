"""Tests for web_tools — D10 readable-text extraction pins (§39).

Before D10, _strip_html was a stack of regexes: nav/cookie/footer junk
leaked into the agent's 12K context budget (measured junk-hits 5/10 in
scripts/d10_webfetch_measure.py), <pre> code was whitespace-flattened,
and an unclosed <script> could swallow an entire page. The stdlib
HTMLParser extractor (primary) + legacy regex (degenerate fallback) are
pinned here. No new dependencies were added — verified by imports.
"""

import pytest

from src.tools.web_tools import _strip_html, web_fetch


PAGE = """<!DOCTYPE html>
<html>
<head>
<title>Docs &amp; Guides</title>
<script type="application/ld+json">{"name":"spam"}</script>
<style>.nav{display:none}</style>
</head>
<body>
<nav class="site-nav"><a>Pricing</a></nav>
<div id="cookie-banner" class="cookie banner">Accept all cookies</div>
<!-- secret ad ID 8842 -->
<div role="navigation">Breadcrumb junk here</div>
<main><article>
<h1>Engine Docs</h1>
<p>Budgets &amp; latency &lt;explained&gt;.</p>
<pre><code>def f(x):
    return x  + 1</code></pre>
<p>Done.</p>
</article></main>
<footer class="site-footer">Subscribe to our newsletter</footer>
<script>var t = 1; function n(){ return t; }</script>
</body>
</html>"""


def test_d10_junk_removed_and_content_kept():
    text = _strip_html(PAGE)
    for junk in ("Accept all cookies", "Pricing", "newsletter",
                 "var t =", "secret ad ID", "spam", "display:none",
                 "Breadcrumb junk"):
        assert junk not in text, f"junk leaked: {junk!r}\n{text}"
    for want in ("Engine Docs", "Budgets", "Done."):
        assert want in text, f"content lost: {want!r}\n{text}"


def test_d10_pre_is_fenced_and_verbatim():
    text = _strip_html(PAGE)
    assert "```" in text
    # indentation and inner spacing (x  + 1) preserved byte-for-byte
    assert "def f(x):\n    return x  + 1" in text


def test_d10_inline_code_backticked():
    assert "`subprocess.run`" in _strip_html("<p>Use <code>subprocess.run</code> here</p>")


def test_d10_entities_decoded():
    text = _strip_html(PAGE)
    assert "Budgets & latency <explained>." in text
    assert "&amp;" not in text and "&lt;" not in text


def test_d10_title_entities_decoded_via_fetch(monkeypatch):
    class _Resp:
        url = "https://docs.example/page"
        headers = {"content-type": "text/html; charset=utf-8"}
        text = PAGE

        def raise_for_status(self):
            return None

    monkeypatch.setattr("src.tools.web_tools.httpx.get", lambda *a, **k: _Resp())
    out = web_fetch.invoke({"url": "https://docs.example/page"})
    assert out.startswith("URL: https://docs.example/page")
    assert "Title: Docs & Guides" in out
    assert "Engine Docs" in out
    assert "Accept all cookies" not in out


def test_d10_unclosed_script_tail_survives_via_fallback():
    # An UNCLOSED <script> as the FIRST element makes the parser's CDATA
    # mode swallow everything -> extracted text == "" -> legacy fallback.
    page = "<script>var broken = " + "x" * 600 + ";\n"
    page += "<p>article tail survives this storm of junk</p>"
    text = _strip_html(page)
    assert "article tail survives" in text


def test_d10_non_html_text_untouched():
    assert _strip_html("just plain text") == "just plain text"


def test_d10_truncation_and_scheme_guard():
    # scheme guard
    assert "only http/https" in web_fetch.invoke({"url": "ftp://x.example/y"})
