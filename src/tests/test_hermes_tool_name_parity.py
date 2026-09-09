"""Hermes tool-NAME parity pins (owner, 2026-09-09: "tool name used in Pulse
— is same <Prompt Engineering>?").

The prompt engineering must teach hermes' own tool names. The field run
@7a7111b9 proved the cost of the old inventions: models trained on hermes
emit `terminal` (pulse had bound it only as an alias after the 2026-09-05
unknown-name rejection), and pulse's guidance RENAME_MAP was actively
REWRITING hermes' verbatim prompt text (search_files→search_code,
web_extract→web_fetch, terminal→run_terminal).

Primary names (this file pins them):
    search_files  (hermes tools/file_tools.py:1279)   legacy alias: search_code
    web_extract   (hermes tools/web_tools.py:475)     legacy alias: web_fetch
    terminal      (hermes tools/terminal_tool.py)     legacy alias: run_terminal

Deferred (NOT pinned — different args surface, separate ports):
    process_manage, patch, delegate_task, browser_screenshots,
    read_terminal/close_terminal (desktop-GUI pane tools in hermes).

All pure: temp workspaces, no LLM, no provider keys.
"""

import json
import urllib.request


# ── Registry: hermes names bound, legacy aliases bound too ─────────────────


def _tool_names():
    from src.graphs.chat_graph import tools
    return {t.name for t in tools}


def test_hermes_primary_names_are_bound():
    names = _tool_names()
    assert "search_files" in names
    assert "web_extract" in names
    assert "terminal" in names


def test_legacy_pulse_names_still_execute_via_aliases():
    names = _tool_names()
    assert "search_code" in names
    assert "web_fetch" in names
    assert "run_terminal" in names


def test_bound_hermes_names_subset_of_hermes_registry():
    """Every hermes-primary name pulse binds must be a real hermes tool name —
    the parity direction is hermes→pulse, never pulse-invented."""
    hermes_names = {
        # /tmp/hermes tools/ registry register(name=...) + BROWSER_TOOL_SCHEMAS
        "annotate_preview", "apply_layout", "browser_cdp", "browser_dialog",
        "browser_exec", "browser_navigate", "browser_click", "browser_type",
        "browser_press", "browser_scroll", "browser_back", "browser_snapshot",
        "browser_screenshots", "browser_console", "browser_get_images",
        "browser_vision", "browser_recordings", "clarify", "close_terminal",
        "computer_use", "cronjob_manage", "delegate_task", "desktop_preview",
        "desktop_project", "execute_code", "image_generate", "memory",
        "patch", "process_manage", "read_file", "read_terminal",
        "search_files", "session_search", "setup_mcp", "skills_list",
        "terminal", "text_to_speech", "todo_list", "vision_analyze",
        "web_extract", "web_search", "write_file",
    }
    hermes_bound = {"search_files", "web_extract", "terminal"}
    assert hermes_bound <= hermes_names


# ── The primary tools execute with hermes' argument names ──────────────────


def test_search_files_runs_with_hermes_pattern_arg(tmp_path):
    from src.tools.file_tools import search_files

    (tmp_path / "mod.py").write_text("def run_pulse():\n    return 42\n")
    out = search_files.func(
        "run_pulse", ".", {"configurable": {"workspace": str(tmp_path)}}
    )
    assert "mod.py:1: def run_pulse():" in out

    # legacy pulse scalar arg still accepted
    out2 = search_files.func(
        "", ".", {"configurable": {"workspace": str(tmp_path)}}, query="run_pulse"
    )
    assert "mod.py:1:" in out2


def test_web_extract_contract_shape_matches_hermes():
    """hermes WEB_EXTRACT_SCHEMA: urls list (maxItems 5) + char_limit."""
    from src.tools.web_tools import web_extract

    props = web_extract.args
    assert "urls" in props and "char_limit" in props
    # legacy scalar accepted too
    assert "url" in props


def test_web_extract_fetches_a_list(tmp_path):
    from src.tools.web_tools import web_extract

    html_path = tmp_path / "page.html"
    html_path.write_text(
        "<html><head><title>Pulse</title></head><body>hello parity</body></html>"
    )
    url = html_path.as_uri()  # file:// — rejected as non-http; error per URL
    out = web_extract.func([url, "not-a-scheme:x"], char_limit=5_000)
    # per-URL error lines, not a crash — hermes' per-URL resilience shape
    assert "web_extract error" in out


def test_web_fetch_alias_still_fetches_one_url():
    from src.tools.web_tools import web_fetch

    assert web_fetch.args and list(web_fetch.args)[0] == "url"


def test_terminal_is_primary_and_run_terminal_delegates(tmp_path):
    from src.tools.terminal_tools import terminal, run_terminal

    cfg = {"configurable": {"workspace": str(tmp_path)}}
    assert "Exit code: 0" in terminal.func("echo primary", cfg)
    assert "Exit code: 0" in run_terminal.func("echo alias", cfg)
    # invalid timeout names the PRIMARY tool now; an above-cap timeout is
    # promoted to a tracked background process (hermes :966-971), not refused
    out = terminal.func("echo x", cfg, 0)
    assert out.startswith("⛔ terminal rejected")


# ── Prompt engineering teaches hermes' names, verbatim ─────────────────────


def test_guidance_rename_map_is_empty():
    """The old map rewrote hermes' verbatim text to pulse inventions. Names
    are hermes' own now — nothing may be reworded."""
    from src.prompts.hermes.guidance import RENAME_MAP

    assert RENAME_MAP == {}


def test_guidance_body_teaches_hermes_names():
    from src.prompts.hermes.guidance import execution_guidance_text

    body = execution_guidance_text({
        "read_file", "write_file", "search_files", "terminal", "web_search",
    })
    assert "(search_files, web_search, read_file, etc.)" in body
    assert "search_code" not in body
    assert "run_terminal" not in body


def test_persona_tool_reference_lines_teach_hermes_names():
    import inspect

    from src.prompts import claude_persona

    src = inspect.getsource(claude_persona)
    assert "`search_files(pattern, path)`" in src
    assert "`terminal(command)`" in src
    assert "`web_extract(urls)`" in src
    assert "search_code" not in src
    assert "web_fetch" not in src


def test_environment_terminal_teaching_names_only_terminal():
    from src.prompts.hermes import environment as env

    src = env._WINDOWS_BASH_TERMINAL_TEACHING
    assert "`terminal` tool" in src
    assert "run_terminal" not in src


def test_sandbox_scripts_can_call_hermes_named_tools(tmp_path):
    """execute_code's script namespace exposes the hermes primaries."""
    from src.tools.code_exec_tool import _InnerCallDispatcher

    cfg = {"configurable": {"workspace": str(tmp_path)}}
    ns = _InnerCallDispatcher(cfg).namespace()
    for name in ("search_files", "terminal", "web_extract"):
        assert name in ns, f"{name} missing from the PTC script namespace"
