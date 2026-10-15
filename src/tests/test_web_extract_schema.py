"""web_extract must accept the single-`url` call its own signature
advertises. Field 2026-10-15 (founder's full-pipeline run): the model
called web_extract(url='https://en.wikipedia.org/wiki/Bubble_sort')
and pydantic killed it — `urls` was a required field — costing one
extra model round-trip and painting a red error row, before the
retry with urls=[...] succeeded. The function's url-merge logic was
always correct; the schema made it unreachable."""

from unittest.mock import patch

from src.tools.web_tools import web_extract


def _invoke(args):
    return web_extract.invoke(args)


def test_single_url_alias_is_accepted():
    with patch("src.tools.web_tools._fetch_one", return_value="URL: https://x\n\nbody") as fetch:
        out = _invoke({"url": "https://example.com/page"})
    assert "body" in out
    assert fetch.call_args[0][0] == "https://example.com/page"


def test_bare_string_urls_is_one_url():
    with patch("src.tools.web_tools._fetch_one", return_value="URL: https://x\n\nbody") as fetch:
        out = _invoke({"urls": "https://example.com/page"})
    assert "body" in out
    assert fetch.call_args[0][0] == "https://example.com/page"


def test_no_urls_still_honest_error():
    out = _invoke({})
    assert out.startswith("web_extract error: pass at least one URL")


def test_urls_list_unchanged_and_capped():
    with patch("src.tools.web_tools._fetch_one", return_value="B") as fetch:
        out = _invoke({"urls": [f"https://e{i}.com" for i in range(7)]})
    assert fetch.call_count == 5  # hermes maxItems cap preserved
    assert out.count("B") == 5
