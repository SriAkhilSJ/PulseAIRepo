"""
D10 measurement — old regex "_strip_html" vs the stdlib readable-text extractor
===============================================================================

Debt D10: web_fetch's readability pass was a handful of regexes — nav bars,
cookie banners, footers, JSON-LD blobs and inline JS leaked into the agent's
12K context budget; HTML comments survived; <pre> code formatting was
destroyed by whitespace normalization; and an UNCLOSED <script> swallowed
everything after it.

This harness converts one gnarly fixture page with BOTH implementations
(old recovered from git HEAD the day of the fix) and prints the junk audit.

Run:  python scripts/d10_webfetch_measure.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.web_tools import _strip_html as new_strip

GNARLY_PAGE = """<!DOCTYPE html>
<html>
<head>
<title>PulseAI Docs — Context Engine</title>
<script type="application/ld+json">{"@context":"https://schema.org","name":"spam"}</script>
<style>.nav{display:none}.cookie{position:fixed}</style>
</head>
<body>
<nav class="site-nav menu"><a>Home</a> <a>Pricing</a> <a>Blog</a></nav>
<div id="cookie-banner" class="cookie banner">We value your privacy — Accept all cookies</div>
<!-- internal TODO: remove this comment, AD ID 8842 -->
<main>
<article>
<h1>Context Engine</h1>
<p>The engine builds layered prompts under a &lt;token budget&gt;.</p>
<pre><code>def build_prompt(layers):
    return "\\n".join(layers)</code></pre>
<p>Latency&nbsp;matters &amp; so does cache stability.</p>
</article>
</main>
<aside class="sidebar promo">Buy now! Advertisement: 50% off hosting.</aside>
<footer class="site-footer">Subscribe to our newsletter. (c) 2026 Example Inc.</footer>
<script>var tracker = window.location; function noop(){ return 1 < 2 && 2 > 1; } tracker();</script>
</body>
</html>
"""

JUNK = ["Accept all cookies", "Buy now", "Advertisement", "newsletter",
        "var tracker", "function noop", "AD ID 8842", "schema.org",
        "display:none", "Pricing"]
WANT = ["Context Engine", "token budget", "def build_prompt",
        "Latency", "cache stability"]


def _audit(text: str, tag: str) -> None:
    junk_hits = [j for j in JUNK if j in text]
    want_missing = [w for w in WANT if w not in text]
    fenced = "```" in text
    print(f"[{tag}] len={len(text)}  junk-hits={len(junk_hits)}/{len(JUNK)} {junk_hits}")
    print(f"      missing-wanted={want_missing}  code fenced={fenced}")


def main() -> None:
    old_path = "/tmp/old_web_tools.py"
    if os.path.exists(old_path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("old_web_tools", old_path)
        old_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old_mod)
        _audit(old_mod._strip_html(GNARLY_PAGE), "OLD regex")
    _audit(new_strip(GNARLY_PAGE), "NEW parser")
    print()
    print("NEW output:")
    print(new_strip(GNARLY_PAGE))


if __name__ == "__main__":
    main()
