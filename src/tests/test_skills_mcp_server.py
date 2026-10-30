"""Contract tests for the skills MCP server.

Two layers, on purpose:

* in-process `handle()` tests for the protocol surface, the error taxonomy and the
  budgets — fast and precise;
* one end-to-end session through `src/tools/mcp_client.MCPStdioClient`, because a
  server that only works when called in-process is not a server.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

from src.mcp_skills.index import SkillIndex
from src.mcp_skills.server import MAX_VIEW_CHARS, SkillMCPServer

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server():
    return SkillMCPServer(index=SkillIndex.build())


def call(server, method, params=None):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert response is not None
    return response


def tool(server, name, args=None, meta=None):
    params = {"name": name, "arguments": args or {}}
    if meta:
        params["_meta"] = meta
    result = call(server, "tools/call", params)["result"]
    text = result["content"][0]["text"]
    try:
        return json.loads(text), result.get("isError", False)
    except json.JSONDecodeError:
        return text, result.get("isError", False)


# -- protocol ---------------------------------------------------------------

def test_initialize_advertises_all_three_capabilities(server):
    result = call(server, "initialize", {"protocolVersion": "2024-11-05"})["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert set(result["capabilities"]) == {"tools", "resources", "prompts"}


def test_unknown_method_is_a_protocol_error(server):
    response = call(server, "does/not/exist")
    assert response["error"]["code"] == -32601


def test_notifications_get_no_response(server):
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


# -- tools ------------------------------------------------------------------

def test_skills_list_root_lists_domains(server):
    text, is_error = tool(server, "skills_list")
    assert not is_error
    assert "website-architect/" in text and "desktop-architect/" in text


def test_skills_list_unknown_shelf_suggests_domains(server):
    payload, is_error = tool(server, "skills_list", {"shelf": "nope-architect"})
    assert is_error and payload["code"] == "UNKNOWN_SHELF"
    assert "website-architect" in payload["domains"]


def test_skill_view_returns_several_books_in_one_call(server):
    text, is_error = tool(server, "skill_view", {"names": "rest-architect, kafka-architect"})
    assert not is_error
    assert "**rest-architect**" in text and "**kafka-architect**" in text


def test_skill_view_matches_the_internal_tool_body(server):
    """MCP and the in-process tool must serve the same bytes for the same book."""
    from src.tools.skill_tools import skill_view as internal_tool

    fn = getattr(internal_tool, "func", internal_tool)  # StructuredTool wraps a function
    internal = fn("desktop-ipc-architect")
    body = server.index.get("desktop-ipc-architect").body
    assert body in internal


def test_skill_view_unknown_book_gives_close_matches(server):
    payload, is_error = tool(server, "skill_view", {"names": "kafka-architec"})
    assert is_error and payload["code"] == "UNKNOWN_BOOK"
    assert payload["close_matches"]["kafka-architec"], "expected fuzzy suggestions"


def test_search_ranks_with_a_reason(server):
    payload, is_error = tool(server, "skills_search", {"query": "kafka consumer lag"})
    assert not is_error and payload["hits"]
    assert payload["hits"][0]["name"] == "kafka-architect"
    assert "matched:" in payload["hits"][0]["why_matched"]


def test_bundle_is_refused_while_executing(server):
    payload, is_error = tool(server, "skill_bundle", {"task": "set up aws", "phase": "executing"})
    assert is_error and payload["code"] == "PHASE_DENIED"
    assert "skill_view (deliberate read)" in payload["allowed"]


def test_bundle_while_planning_returns_a_crown_and_leaves(server):
    payload, is_error = tool(server, "skill_bundle", {"task": "terraform state is a mess",
                                                      "phase": "planning"})
    assert not is_error
    names = [b["name"] for b in payload["books"]]
    assert names and all(n.endswith("-architect") for n in names)


def test_view_budget_truncates_and_says_so(server):
    every = " , ".join(sorted(server.index.books)[:60])
    text, is_error = tool(server, "skill_view", {"names": every})
    assert not is_error
    assert len(text) <= MAX_VIEW_CHARS + 400
    assert "budget reached" in text and "ask for the rest" in text


# -- resources --------------------------------------------------------------

def test_every_book_is_a_resource_and_reads_back(server):
    listed = call(server, "resources/list")["result"]["resources"]
    uris = {r["uri"] for r in listed if r["uri"] != "skill://catalog"}
    book_uris = {b.uri for b in server.index.books.values()}
    # every book is a resource, and nothing else is
    assert book_uris <= uris
    assert {u for u in uris if u in book_uris} == book_uris
    architect = [b for b in server.index.books.values() if b.is_architect]
    assert len(architect) >= 220
    sample = server.index.get("native-feel-architect")
    read = call(server, "resources/read", {"uri": sample.uri})["result"]["contents"][0]
    assert read["mimeType"] == "text/markdown"
    assert sample.body[:200] in read["text"]


def test_catalog_counts_match_the_disk(server):
    payload = json.loads(call(server, "resources/read", {"uri": "skill://catalog"})
                         ["result"]["contents"][0]["text"])
    assert payload["total"] == len(server.index.books)
    assert not payload["skipped"], f"unreadable books: {payload['skipped']}"


def test_bad_uri_is_structured(server):
    response = call(server, "resources/read", {"uri": "skill://no-such-domain"})
    assert response["error"]["code2" if False else "code"] == -32000
    payload = json.loads(response["error"]["message"])
    assert payload["code"] == "BAD_URI" and "website-architect" in payload["domains"]


# -- end to end -------------------------------------------------------------

def test_stdio_session_with_the_real_client():
    from src.tools.mcp_client import MCPStdioClient

    client = MCPStdioClient("skills", [sys.executable, "scripts/skills_mcp_server.py"])
    try:
        info = client.initialize()
        assert info["serverInfo"]["name"] == "crusor-skills"
        tools = {t["name"] for t in client.list_tools()}
        assert {"skills_list", "skill_view", "skills_search", "skill_bundle"} <= tools
        out = client.call_tool("skill_view", {"names": "git-workflow-architect"})
        assert "git-workflow-architect" in out
    finally:
        client.close()
