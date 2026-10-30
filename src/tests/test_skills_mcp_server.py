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

def test_resources_list_stays_small(server):
    """A 240-entry listing is ~26k tokens for any host that reads it eagerly."""
    payload = json.dumps(call(server, "resources/list")["result"])
    entries = payload.count('"uri"')
    assert entries <= 12, f"{entries} resources listed"
    assert len(payload) < 4000, f"resources/list is {len(payload)} bytes"


def test_every_book_is_addressable_by_uri(server):
    """Books are resolved through the template, not enumerated in the listing."""
    unreadable = []
    for book in server.index.books.values():
        try:
            contents = call(server, "resources/read", {"uri": book.uri})["result"]["contents"]
        except AssertionError:  # pragma: no cover
            unreadable.append(book.name)
            continue
        if not contents or book.body[:80] not in contents[0]["text"]:
            unreadable.append(book.name)
    assert not unreadable, f"{len(unreadable)} books unreachable by uri: {unreadable[:5]}"
    templates = call(server, "resources/templates/list")["result"]["resourceTemplates"]
    assert any(t["uriTemplate"].endswith("{domain}/{shelf}/{book}") for t in templates)
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


# -- fault injection --------------------------------------------------------

def test_unreadable_book_is_skipped_and_the_rest_still_serve():
    index = SkillIndex.build_from([
        {"name": "good-architect", "path": "demo/good-architect", "instruction": "# Good",
         "description": "d", "triggers": ["good"]},
        {"name": "broken-architect", "path": "demo/broken-architect", "instruction": "",
         "description": "d", "triggers": ["broken"]},
        {"path": "demo/no-name", "instruction": "# x"},
    ])
    server = SkillMCPServer(index=index)
    catalog = json.loads(call(server, "resources/read", {"uri": "skill://catalog"})
                         ["result"]["contents"][0]["text"])
    assert catalog["total"] == 1
    assert len(catalog["skipped"]) == 2
    text, is_error = tool(server, "skill_view", {"names": "good-architect"})
    assert not is_error and "**good-architect**" in text


def test_missing_library_reports_library_unavailable(monkeypatch):
    import src.mcp_skills.server as server_mod

    def boom(refresh: bool = False):
        raise RuntimeError("skills/ is gone")

    monkeypatch.setattr(server_mod, "get_index", boom)
    server = SkillMCPServer()
    response = call(server, "tools/call", {"name": "skills_list", "arguments": {}})
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["code"] == "LIBRARY_UNAVAILABLE"
    assert "skills/" in payload["message"]


def test_unknown_tool_is_a_code_not_a_crash(server):
    payload, is_error = tool(server, "no_such_tool")
    assert is_error and payload["code"] == "UNKNOWN_TOOL"
    assert "skills_list" in payload["tools"]


def test_health_resource_reports_metrics(server):
    tool(server, "skills_list")
    tool(server, "skill_view", {"names": "no-such-book"})  # provokes an error count
    health = json.loads(call(server, "resources/read", {"uri": "skill://health"})
                        ["result"]["contents"][0]["text"])
    assert health["server"]["name"] == "crusor-skills"
    assert health["metrics"]["requests"] >= 2
    assert health["metrics"]["errors"].get("UNKNOWN_BOOK", 0) >= 1


# -- freshness --------------------------------------------------------------

def test_editing_a_book_on_disk_makes_the_index_stale():
    index = SkillIndex.build()
    assert not index.is_stale()
    target = next(iter(index.snapshot))
    original = pathlib.Path(target).stat().st_mtime
    try:
        future = original + 120
        import os

        os.utime(target, (future, future))
        assert index.is_stale()
    finally:
        import os

        os.utime(target, (original, original))
    assert not index.is_stale()


def test_server_refreshes_without_a_restart():
    server = SkillMCPServer(refresh_seconds=0)
    before = len(server.index.books)
    server.maybe_refresh()
    assert len(server.index.books) == before


# -- client wiring (P4) -----------------------------------------------------

def test_server_is_discoverable_through_the_repository_client(tmp_path):
    """The real discovery path: .crusorai/mcp.json -> load -> list_tools -> call."""
    from src.tools.mcp_client import call_mcp_tool, discover_mcp_tools

    script = REPO_ROOT / "scripts" / "skills_mcp_server.py"
    config_dir = tmp_path / ".crusorai"
    config_dir.mkdir()
    (config_dir / "mcp.json").write_text(json.dumps({
        # canonical config shape: command is one string, args carry the rest
        "servers": {"skills": {"command": sys.executable, "args": [str(script)], "enabled": True}}
    }), encoding="utf-8")

    tools = discover_mcp_tools(str(tmp_path))
    names = {t["name"] for t in tools}
    assert {"mcp_skills_skills_list", "mcp_skills_skill_view"} <= names
    assert all(t["guarded"] for t in tools)

    out = call_mcp_tool(str(tmp_path), "skills", "skills_list", {})
    assert "website-architect/" in out
