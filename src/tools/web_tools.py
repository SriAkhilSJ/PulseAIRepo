# src/tools/web_tools.py
"""
Web Tools
=========

Open-web tools for documentation, API references, and error lookup.

These tools are intentionally lightweight and dependency-free beyond httpx.
They expose:

- web_search: search the web for relevant pages
- web_fetch: fetch and lightly clean a web page
"""

import html
import re
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from langchain_core.tools import tool


_USER_AGENT = (
    "Mozilla/5.0 (compatible; PulseCodeAI/1.0; "
    "+https://example.local/pulsecodeai)"
)


def _strip_html(markup: str) -> str:
    """Convert basic HTML into readable text."""
    # Remove scripts/styles first.
    markup = re.sub(r"<script[\s\S]*?</script>", " ", markup, flags=re.IGNORECASE)
    markup = re.sub(r"<style[\s\S]*?</style>", " ", markup, flags=re.IGNORECASE)

    # Preserve rough paragraph/list boundaries.
    markup = re.sub(r"</(p|div|li|h[1-6]|tr|br)>\s*", "\n", markup, flags=re.IGNORECASE)

    # Drop remaining tags and decode entities.
    text = re.sub(r"<[^>]+>", " ", markup)
    text = html.unescape(text)

    # Normalize whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)

    return text.strip()


def _normalize_result_url(url: str) -> str:
    """Normalize DuckDuckGo redirect/protocol-relative URLs."""
    url = html.unescape(url)

    if url.startswith("//"):
        url = "https:" + url

    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        target = query.get("uddg", [""])[0]
        if target:
            return unquote(target)

    return url


def _extract_duckduckgo_results(markup: str, max_results: int) -> list[dict[str, str]]:
    """Extract search results from DuckDuckGo's HTML endpoint."""
    results: list[dict[str, str]] = []

    # DuckDuckGo HTML result links generally look like:
    # <a rel="nofollow" class="result__a" href="...">Title</a>
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>[\s\S]*?)</a>',
        re.IGNORECASE,
    )

    for match in pattern.finditer(markup):
        url = _normalize_result_url(match.group("url"))
        title = _strip_html(match.group("title"))

        if not title or not url:
            continue

        results.append({"title": title, "url": url})

        if len(results) >= max_results:
            break

    return results


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web for documentation, APIs, error messages, or external facts.

    Use this when the answer depends on current external documentation or when
    an error/library/API is unfamiliar. After finding a promising result, use
    web_fetch to read the full page.
    """
    max_results = max(1, min(max_results, 10))

    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"

    try:
        response = httpx.get(
            search_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as error:
        return f"web_search error for query {query!r}: {error}"

    results = _extract_duckduckgo_results(response.text, max_results=max_results)

    if not results:
        return f"No web search results found for: {query}"

    lines = [f"Search results for: {query}"]
    for index, result in enumerate(results, start=1):
        lines.append(f"{index}. {result['title']}")
        lines.append(f"   URL: {result['url']}")

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
