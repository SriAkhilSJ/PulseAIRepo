# src/tools/web_tools.py
"""
Web Tools
=========

Open-web tools for documentation, API references, and error lookup.
Now using duckduckgo-search (ddgs) for better performance and snippets.
"""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from ddgs import DDGS
from langchain_core.tools import tool


_USER_AGENT = (
    "Mozilla/5.0 (compatible; PulseCodeAI/1.0; "
    "+https://example.local/pulsecodeai)"
)


# ---------------------------------------------------------------------
# D10 (§39): readable-text extraction — stdlib HTMLParser, no new deps
# ---------------------------------------------------------------------
# The legacy regex stripper leaked nav bars, cookie banners, JSON-LD blobs,
# comments and footer junk into the agent's 12K context budget, destroyed
# <pre> code formatting, and let an UNCLOSED <script> swallow everything
# after it. The parser below is the primary path; the legacy regex survives
# only as the degenerate-output fallback (never regress to zero output).

# Elements whose CONTENT is always junk (dropped with the element).
_DROP_CONTENT = {
    "script", "style", "noscript", "template", "svg", "iframe",
    "form", "select", "button", "head",
}
# Containers dropped only when their class/id smells like boilerplate —
# a plain <header> may hold the article title; a .site-header never does.
_JUNK_RE = re.compile(
    r"nav|menu|footer|header|sidebar|cookie|banner|promo|advert"
    r"|subscribe|newsletter|share|social|breadcrumb|related|comment",
    re.IGNORECASE,
)
_JUNK_CONTAINERS = {"nav", "footer", "aside", "header"}
# Block-level closes that end a line of readable text.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote",
    "figure", "figcaption", "dt", "dd",
}


class _ReadableTextExtractor(HTMLParser):
    """HTML-to-readable-text for LLM context.

    - drops junk content (scripts, styles, forms, <head>...) entirely;
    - drops boilerplate containers (nav/footer/aside/header) when their
      class/id matches the junk pattern;
    - converts <pre> to fenced code blocks, <code> to backticks — docs
      pages carry code, and fences are what the model reads best;
    - comments never survive (handle_comment is a no-op by default);
    - whitespace: block closes emit newlines; runs of spaces/tabs collapse;
      inside <pre> data stays VERBATIM (indentation is information).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0       # inside drop-content element
        self._junk_depth = 0       # inside boilerplate container
        self._pre_depth = 0        # inside <pre> (verbatim)
        self._code_depth = 0       # inside inline <code> (not in <pre>)

    # -- state helpers ---------------------------------------------------

    def _suppressed(self) -> bool:
        return self._skip_depth > 0 or self._junk_depth > 0

    # -- element handling -------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _DROP_CONTENT:
            self._skip_depth += 1
            return
        if self._suppressed():
            return
        if tag in _JUNK_CONTAINERS:
            attr_text = " ".join(f"{k}={v}" for k, v in attrs if v)
            if _JUNK_RE.search(attr_text):
                self._junk_depth += 1
                return
        # role/aria boilerplate on ANY element (div role="navigation" etc.)
        attr_text = " ".join(f"{k}={v}" for k, v in attrs if v)
        if _JUNK_RE.search(attr_text) and tag in {"div", "section", "span"}:
            self._junk_depth += 1
            return
        if tag == "pre":
            self._chunks.append("\n```\n")
            self._pre_depth += 1
        elif tag == "code" and self._pre_depth == 0:
            self._chunks.append("`")
            self._code_depth += 1
        elif tag == "br":
            self._chunks.append("\n")
        elif tag == "li":
            self._chunks.append("\n- ")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br" and not self._suppressed():
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in _JUNK_CONTAINERS and self._junk_depth > 0:
            self._junk_depth -= 1
            return
        if tag in {"div", "section", "span"} and self._junk_depth > 0:
            self._junk_depth -= 1
            return
        if self._suppressed():
            return
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self._chunks.append("\n```\n")
        elif tag == "code" and self._code_depth > 0:
            self._chunks.append("`")
            self._code_depth -= 1
        elif tag in _BLOCK_TAGS or tag == "body":
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._suppressed():
            return
        if self._pre_depth > 0:
            self._chunks.append(data)  # verbatim: indentation is information
        else:
            self._chunks.append(data)

    def text(self) -> str:
        out = "".join(self._chunks)
        # Whitespace normalization OUTSIDE fenced pre blocks.
        parts = out.split("\n```\n")
        for i in range(0, len(parts), 2):  # even indexes = outside fences
            part = re.sub(r"[ \t]+", " ", parts[i])
            part = re.sub(r" *\n *", "\n", part)
            parts[i] = part
        out = "\n```\n".join(parts)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip()


def _strip_html(markup: str) -> str:
    """Convert HTML into readable text for the agent's context budget.

    Primary: _ReadableTextExtractor (stdlib html.parser). Fallback: the
    legacy regex strip — used only when the parser produced (nearly)
    nothing from substantial markup (degenerate pages, e.g. an unclosed
    <script> swallowing the document in CDATA mode).
    """
    try:
        parser = _ReadableTextExtractor()
        parser.feed(markup)
        parser.close()
        text = parser.text()
    except Exception:
        text = ""
    legacy_min = 25
    if len(text) >= legacy_min or len(markup) < 500:
        return text
    return _strip_html_legacy(markup)


def _strip_html_legacy(markup: str) -> str:
    """Pre-D10 regex strip; fallback path only (see _strip_html)."""
    markup = re.sub(r"<script[\s\S]*?</script>", " ", markup, flags=re.IGNORECASE)
    markup = re.sub(r"<style[\s\S]*?</style>", " ", markup, flags=re.IGNORECASE)
    markup = re.sub(r"</(p|div|li|h[1-6]|tr|br)>\s*", "\n", markup, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", markup)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for documentation, APIs, error messages, or external facts.

    Use this when the answer depends on current external documentation or when
    an error/library/API is unfamiliar. After finding a promising result, use
    web_fetch to read the full page.
    """
    max_results = max(1, min(max_results, 10))

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as error:
        return f"web_search error for query {query!r}: {error}"

    if not results:
        return f"No web search results found for: {query}"

    lines = [f"Search results for: {query}"]
    for index, result in enumerate(results, start=1):
        # result typically contains 'title', 'href', 'body'
        title = result.get('title', 'Untitled')
        url = result.get('href', 'No URL')
        snippet = result.get('body', '')
        
        lines.append(f"{index}. {title}")
        lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   Snippet: {snippet}")

    return "\n".join(lines)


@tool
def web_fetch(url: str, max_chars: int = 12_000) -> str:
    """
    Fetch and summarize the readable text from a web page.

    Use this after web_search when a result looks useful. It returns the page
    title/URL plus cleaned text, truncated to max_chars to protect context.
    """
    max_chars = max(1_000, min(max_chars, 30_000))

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"web_fetch error: only http/https URLs are supported: {url}"

    try:
        response = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=25,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as error:
        return f"web_fetch error for URL {url!r}: {error}"

    content_type = response.headers.get("content-type", "")
    text = response.text

    if "html" in content_type.lower() or "<html" in text[:500].lower():
        title_match = re.search(r"<title[^>]*>([\s\S]*?)</title>", text, re.IGNORECASE)
        title = _strip_html(title_match.group(1)) if title_match else "Untitled"
        readable = _strip_html(text)
    else:
        title = "Plain text"
        readable = text.strip()

    if len(readable) > max_chars:
        readable = readable[:max_chars] + "\n... (truncated) ..."

    return (
        f"URL: {response.url}\n"
        f"Title: {title}\n"
        f"Content-Type: {content_type}\n\n"
        f"{readable}"
    )
