# src/tools/web_tools.py
"""
Web Tools
=========

Open-web tools for documentation, API references, and error lookup.
Now using duckduckgo-search (ddgs) for better performance and snippets.
"""

import html
import re
from urllib.parse import urlparse

import httpx
from ddgs import DDGS
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
