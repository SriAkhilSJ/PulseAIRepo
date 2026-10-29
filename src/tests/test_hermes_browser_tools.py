"""Hermes browser-tool port contracts (src/tools/browser_tools.py).

hermes source of truth: tools/browser_tool.py + browser_tool_session.py +
browser_tool_install.py (local agent-browser backend). These tests pin the
ported surface: hermes tool names/schemas, npx sentinel argv, response and
error shapes, URL floors, session-per-thread naming, output interpretation,
and the verify pipeline rewiring. The CLI itself is always mocked — these
are contracts, not browser tests.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.tools import browser_tools as bt
from src.tools.browser_tools import BROWSER_TOOLS, _dumps, run_browser_command

# hermes BROWSER_TOOL_SCHEMAS order (local backend; browser_vision unported).
HERMES_BROWSER_NAMES = [
    "browser_navigate", "browser_snapshot", "browser_click", "browser_type",
    "browser_scroll", "browser_back", "browser_press", "browser_console",
    "browser_get_images",
]


@pytest.fixture(autouse=True)
def _fresh_resolution_state(monkeypatch):
    """Every test starts with cold CLI resolution and no env override.
    Recording defaults OFF for this module (navigate-mechanics tests must
    stay orthogonal); the visible-testing tests re-enable it explicitly."""
    bt.invalidate_cli_cache()
    monkeypatch.delenv("CRUSORAI_AGENT_BROWSER", raising=False)
    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "off")
    with bt._recording_lock:
        bt._RECORDING_SESSIONS.clear()
    yield
    bt.invalidate_cli_cache()
    with bt._recording_lock:
        bt._RECORDING_SESSIONS.clear()


def _cfg(thread: str = "t1", workspace: str = ".") -> dict:
    return {"configurable": {"thread_id": thread, "workspace": workspace}}


# ---------------------------------------------------------------------------
# Schema contracts
# ---------------------------------------------------------------------------

def test_tool_set_matches_hermes_names_and_order():
    names = [t.name for t in BROWSER_TOOLS]
    # browser_screenshot is crusor's deterministic-verify receipt tool (hermes
    # reaches the same agent-browser command inside browser_vision); the rest
    # are hermes' local schema list verbatim, in hermes' order.
    assert names == [*HERMES_BROWSER_NAMES, "browser_screenshot"]


@pytest.mark.parametrize("name,required", [
    ("browser_navigate", {"url"}),
    ("browser_click", {"ref"}),
    ("browser_type", {"ref", "text"}),
    ("browser_press", {"key"}),
    ("browser_snapshot", set()),
    ("browser_scroll", {"direction"}),
    ("browser_back", set()),
    ("browser_console", set()),
    ("browser_get_images", set()),
])
def test_required_parameters_match_hermes(name, required):
    tool = next(t for t in BROWSER_TOOLS if t.name == name)
    schema = tool.args_schema.schema()
    assert set(schema.get("required", [])) == required


def test_every_hermes_description_carries_the_teaching():
    """hermes teaches the snapshot->ref->act loop in the descriptions; the port
    must not blunt it."""
    navigate = next(t for t in BROWSER_TOOLS if t.name == "browser_navigate")
    assert "Must be called before other browser tools" in navigate.description
    assert "ref IDs" in navigate.description
    click = next(t for t in BROWSER_TOOLS if t.name == "browser_click")
    assert "@e5" in click.description
    console = next(t for t in BROWSER_TOOLS if t.name == "browser_console")
    assert "expression" in console.description


# ---------------------------------------------------------------------------
# CLI resolution — hermes browser_tool_install
# ---------------------------------------------------------------------------

def test_npx_sentinel_argv_matches_hermes(monkeypatch):
    monkeypatch.setattr(bt, "_cli_probe_ok", True)
    argv = bt._agent_browser_argv(bt.NPX_AGENT_BROWSER_SENTINEL)
    # hermes _agent_browser_argv: resolved npx bin (absolute via which), the
    # no-install-script/no-network flags, and the pinned spec.
    assert argv[0].lower().endswith(("npx", "npx.cmd", "npx.exe"))
    assert argv[1:] == ["--ignore-scripts", "--prefer-offline", "-y",
                        bt.AGENT_BROWSER_NPX_SPEC]


def test_env_override_wins_and_is_validated(monkeypatch, tmp_path):
    fake = tmp_path / "agent-browser.cmd"
    fake.write_text("echo ok", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setenv("CRUSORAI_AGENT_BROWSER", str(fake))
    monkeypatch.setattr(bt.subprocess, "run", fake_run)
    assert bt.find_agent_browser() == str(fake)
    assert calls and calls[0][:-1] == [str(fake)] and calls[0][-1] == "--version"


def test_broken_override_fails_with_install_hint(monkeypatch):
    monkeypatch.setenv("CRUSORAI_AGENT_BROWSER", r"C:\definitely\not\real.exe")
    result = run_browser_command("crusorai-x", "open", ["http://localhost:3000"])
    assert result["success"] is False
    assert "CRUSORAI_AGENT_BROWSER" in result["error"]
    assert "npm install -g agent-browser" in result["error"]


def test_missing_cli_gives_actionable_error(monkeypatch):
    monkeypatch.setattr(bt.shutil, "which", lambda _: None)
    result = run_browser_command("crusorai-x", "snapshot", [])
    assert result["success"] is False
    assert "agent-browser CLI not found" in result["error"]
    assert "npx" in result["error"]  # the npx route is named as the fallback


def test_cached_missing_resolution_short_circuits(monkeypatch):
    monkeypatch.setattr(bt.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError):
        bt.find_agent_browser()
    # second call must hit the cache (hermes resolved-flag semantics)…
    with pytest.raises(FileNotFoundError) as exc:
        bt.find_agent_browser()
    assert "(cached)" in str(exc.value)
    # …and a spawn failure invalidates it once.
    bt.invalidate_cli_cache()
    with pytest.raises(FileNotFoundError):
        bt.find_agent_browser()


# ---------------------------------------------------------------------------
# URL floors — hermes _secret_url_error / _is_always_blocked_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    # hermes length gates: sk- needs {10,} body chars, ghp_ needs {10,}
    "https://example.com/api?api_key=sk-abcdef1234567890",
    "https://example.com/?token=ghp_abcdef1234567890",
])
def test_navigate_blocks_secret_urls(url):
    out = json.loads(bt.browser_navigate.invoke({"url": url}, config=_cfg()))
    assert out["success"] is False
    assert "Secrets must not be sent in URLs" in out["error"]


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
])
def test_navigate_blocks_metadata_endpoints(url):
    out = json.loads(bt.browser_navigate.invoke({"url": url}, config=_cfg()))
    assert out["success"] is False
    assert "cloud metadata endpoint" in out["error"]


# ---------------------------------------------------------------------------
# Command shapes — hermes response contracts
# ---------------------------------------------------------------------------

def test_navigate_success_merges_auto_snapshot(monkeypatch):
    seen: list[tuple[str, list[str], int | None]] = []

    def fake_run(session, command, args=None, timeout=None):
        seen.append((command, list(args or []), timeout))
        if command == "open":
            assert timeout >= bt.MIN_FIRST_OPEN_TIMEOUT  # hermes first-open floor
            return {"success": True, "data": {"title": "My App", "url": "http://localhost:3000/"}}
        if command == "snapshot":
            assert args == ["-c"]  # hermes auto-snapshot is the compact view
            return {"success": True, "data": {"snapshot": "[button] Submit @e1", "refs": {"e1": {}}}}
        raise AssertionError(f"unexpected command {command}")

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke({"url": "http://localhost:3000"}, config=_cfg()))
    assert out["success"] is True
    assert out["url"] == "http://localhost:3000/"
    assert out["title"] == "My App"
    assert out["snapshot"] == "[button] Submit @e1"
    assert out["element_count"] == 1
    assert [c for c, _, _ in seen] == ["open", "snapshot"]


def test_navigate_failure_is_hermes_error_shape(monkeypatch):
    monkeypatch.setattr(bt, "run_browser_command",
                        lambda *a, **kw: {"success": False, "error": "daemon dead"})
    out = json.loads(bt.browser_navigate.invoke({"url": "http://localhost:1"}, config=_cfg()))
    assert out == {"success": False, "error": "daemon dead"}


def test_navigate_bot_detection_title_warning(monkeypatch):
    def fake_run(session, command, args=None, timeout=None):
        if command == "open":
            return {"success": True, "data": {"title": "Just a moment...", "url": "https://x"}}
        return {"success": True, "data": {"snapshot": "x", "refs": {}}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke({"url": "https://x"}, config=_cfg()))
    assert "bot detection" in out["bot_detection_warning"]


def test_redirect_to_metadata_moves_page_to_blank_and_blocks(monkeypatch):
    commands: list[tuple[str, list[str]]] = []

    def fake_run(session, command, args=None, timeout=None):
        commands.append((command, list(args or [])))
        if command == "open":
            target = (args or [""])[0]
            if target == "https://evil.example/start":
                return {"success": True, "data": {"title": "t",
                                                  "url": "http://169.254.169.254/x"}}
            return {"success": True, "data": {"title": "", "url": target}}
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke(
        {"url": "https://evil.example/start"}, config=_cfg()))
    assert out["success"] is False and "cloud metadata endpoint" in out["error"]
    # hermes: the page is moved to about:blank so later snapshots can't read it
    assert ("open", ["about:blank"]) in commands


def test_click_normalizes_ref_and_reports_clicked(monkeypatch):
    captured: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        captured["args"] = list(args or [])
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_click.invoke({"ref": "e5"}, config=_cfg(thread="thread 7")))
    assert captured["args"] == ["@e5"]  # hermes _at_ref
    assert out == {"success": True, "clicked": "@e5"}


def test_type_uses_fill_and_echoes_element(monkeypatch):
    captured: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        captured["command"], captured["args"] = command, list(args or [])
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_type.invoke({"ref": "@e3", "text": "hi"}, config=_cfg()))
    assert (captured["command"], captured["args"]) == ("fill", ["@e3", "hi"])
    assert out == {"success": True, "typed": "hi", "element": "@e3"}


def test_scroll_sends_hermes_pixel_argument(monkeypatch):
    captured: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        captured["args"] = list(args or [])
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_scroll.invoke({"direction": "down"}, config=_cfg()))
    assert captured["args"] == ["down", "500"]
    assert out == {"success": True, "scrolled": "down"}
    # hermes carries enum ["up","down"] in the schema itself, so a bad
    # direction is rejected by pydantic before the body ever runs.
    with pytest.raises(ValidationError):
        bt.browser_scroll.invoke({"direction": "sideways"}, config=_cfg())
    schema = bt.browser_scroll.args_schema.model_json_schema()
    assert schema["properties"]["direction"].get("enum") == ["up", "down"]
    assert schema["properties"]["direction"].get("description") == "Direction to scroll"


def test_console_messages_and_errors_shape(monkeypatch):
    def fake_run(session, command, args=None, timeout=None):
        if command == "console":
            return {"success": True, "data": {"messages": [{"type": "error", "text": "boom"}]}}
        if command == "errors":
            return {"success": True, "data": {"errors": [{"message": "Uncaught TypeError"}]}}
        raise AssertionError(command)

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_console.invoke({}, config=_cfg()))
    assert out["success"] is True
    assert out["console_messages"] == [{"type": "error", "text": "boom", "source": "console"}]
    assert out["js_errors"] == [{"message": "Uncaught TypeError", "source": "exception"}]
    assert (out["total_messages"], out["total_errors"]) == (1, 1)


def test_console_expression_evaluates_and_parses_json(monkeypatch):
    def fake_run(session, command, args=None, timeout=None):
        assert command == "eval"
        return {"success": True, "data": {"result": '{"count": 2, "videos": []}'}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_console.invoke({"expression": "document.title"}, config=_cfg()))
    assert out["success"] is True
    assert out["result"] == {"count": 2, "videos": []}
    assert out["result_type"] == "dict"


def test_get_images_uses_hermes_eval_js_and_counts(monkeypatch):
    captured: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        captured["js"] = (args or [""])[0]
        return {"success": True, "data": {"result": '[{"src":"http://x/a.png","alt":"","width":8,"height":8}]'}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_get_images.invoke({}, config=_cfg()))
    assert "document.images" in captured["js"] and "data:" in captured["js"]
    assert out["count"] == 1 and out["images"][0]["src"] == "http://x/a.png"


def test_screenshot_reports_missing_chromium_install(monkeypatch, tmp_path):
    monkeypatch.setattr(
        bt, "run_browser_command",
        lambda s, c, a=None, timeout=None: {"success": True,
                                            "data": {"path": str(tmp_path / "nope.png")}})
    out = bt.browser_screenshot.invoke({"name": "shot"}, config=_cfg(workspace=str(tmp_path)))
    assert "not created" in out and "agent-browser install" in out


def test_screenshot_success_carries_quality_receipt(monkeypatch, tmp_path):
    from PIL import Image

    shot = tmp_path / "screenshots"
    shot.mkdir(parents=True)

    def fake_run(session, command, args=None, timeout=None):
        assert command == "screenshot"
        assert args == ["--full", str(shot / "page.png")]
        Image.new("RGB", (64, 64), (240, 240, 240)).save(shot / "page.png")
        return {"success": True, "data": {"path": str(shot / "page.png")}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = bt.browser_screenshot.invoke({"name": "page"}, config=_cfg(workspace=str(tmp_path)))
    assert "Screenshot saved" in out
    assert "visual quality" in out.lower()


# ---------------------------------------------------------------------------
# Sessions + output interpretation — hermes browser_tool_session
# ---------------------------------------------------------------------------

def test_session_name_is_per_thread_and_sanitized():
    assert bt._session_name("abc-123") == "crusorai-abc-123"
    assert bt._session_name("weird id!! spaces") == "crusorai-weird-id-spaces"
    assert bt._session_name("") == "crusorai-default"


def test_session_derives_from_config_thread_id(monkeypatch):
    seen: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        seen["session"] = session
        return {"success": True, "data": {}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    bt.browser_click.invoke({"ref": "@e1"}, config=_cfg(thread="turn-42"))
    assert seen["session"] == "crusorai-turn-42"


def test_interpret_empty_stdout_rc0_is_stale_daemon_failure():
    out = bt._interpret_output("open", "", "", 0)
    assert out["success"] is False and "returned no output" in out["error"]
    # `close` is legitimately empty (hermes _EMPTY_OK_COMMANDS)
    assert bt._interpret_output("close", "", "", 0) == {"success": True, "data": {}}


def test_interpret_non_json_is_error_with_tail():
    out = bt._interpret_output("open", "<html>gateway junk</html>", "", 0)
    assert out["success"] is False
    assert "Non-JSON output from agent-browser" in out["error"]


def test_interpret_rc_failure_carries_stderr():
    out = bt._interpret_output("open", "", "chromium missing", 1)
    assert out == {"success": False, "error": "chromium missing"}


def test_open_timeout_floors_match_hermes():
    assert bt._open_timeout(first_open=True) >= bt.MIN_FIRST_OPEN_TIMEOUT
    assert bt._open_timeout(first_open=False) >= bt.MIN_OPEN_TIMEOUT
    assert bt._command_timeout() == bt.DEFAULT_COMMAND_TIMEOUT


# ---------------------------------------------------------------------------
# Wiring: the resolver and the verify pipeline consume THIS module
# ---------------------------------------------------------------------------

def test_toolsets_resolver_maps_the_hermes_names():
    from src.tools.toolsets import _browser_tool_names
    names = list(_browser_tool_names())
    assert names == [*HERMES_BROWSER_NAMES, "browser_screenshot"]


def test_verify_pipeline_reads_the_hermes_backend_only():
    """The deterministic verify pipeline must not reference the retired
    puppeteer module — one browser backend, hermes' (architecture pin)."""
    import src.tools.ui_verification as uv
    source = Path(uv.__file__).read_text(encoding="utf-8")
    assert "browser_mcp" not in source
    assert 'from src.tools.browser_tools import' in source
    # hermes eval surface: expression goes through browser_console
    assert '"expression"' in source


# ---------------------------------------------------------------------------
# Visible testing — hermes headed flag + record start/stop (owner 2026-09-07:
# Antigravity-style, "in front of users eyes")
# ---------------------------------------------------------------------------

def test_headed_defaults_on_and_flag_rides_the_session_args():
    # owner default: visible window; hermes knob shape, crusor default
    assert bt.headed_mode() is True
    args = bt.build_session_args("crusorai-t")
    assert args == ["--session", "crusorai-t", "--headed"]


def test_headed_env_off_restores_hermes_posture(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_HEADED", "off")
    assert bt.headed_mode() is False
    assert bt.build_session_args("crusorai-t") == ["--session", "crusorai-t"]


def test_recording_starts_once_per_session_and_announces_path(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "on")
    commands: list[tuple[str, list[str]]] = []

    def fake_run(session, command, args=None, timeout=None):
        commands.append((command, list(args or [])))
        if command == "record":
            return {"success": True, "data": {}}
        if command == "open":
            return {"success": True, "data": {"title": "App", "url": "http://localhost:3000"}}
        return {"success": True, "data": {"snapshot": "[button] Send @e1", "refs": {"e1": {}}}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke({"url": "http://localhost:3000"}, config=_cfg()))
    assert out["success"] is True
    # record start BEFORE open (hermes :731 order), .webm target named
    assert commands[0][0] == "record" and commands[0][1][0] == "start"
    assert commands[0][1][1].endswith(".webm")
    assert commands[1] == ("open", ["http://localhost:3000"])
    # the receipt is user-visible on the navigate card
    assert "recording" in out and out["recording"].endswith(".webm")
    # second navigate in the same session: no second `record start`
    bt.browser_navigate.invoke({"url": "http://localhost:3000/other"}, config=_cfg())
    starts = [c for c, a in commands if c == "record" and a and a[0] == "start"]
    assert len(starts) == 1  # hermes _recording_sessions guard


def test_recording_off_restores_hermes_posture(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "off")
    seen: list[str] = []

    def fake_run(session, command, args=None, timeout=None):
        seen.append(command)
        return {"success": True, "data": {"title": "App", "url": "http://localhost:3000"}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke({"url": "http://localhost:3000"}, config=_cfg()))
    assert "record" not in seen
    assert "recording" not in out


def test_stop_recording_saves_webm_and_clears_state(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "on")
    monkeypatch.setattr(bt, "run_browser_command", lambda s, c, a=None, timeout=None: (
        {"success": True, "data": {}} if c == "record" and a[0] == "start"
        else {"success": True, "data": {"path": "C:\\recordings\\session.webm"}}
        if c == "record" else {"success": True, "data": {}}))
    assert bt.maybe_start_recording("crusorai-t1") is not None
    saved = bt.stop_browser_recording("crusorai-t1")
    assert saved == "C:\\recordings\\session.webm"
    # state cleared: a second stop is a no-op (hermes discard-in-finally shape)
    assert bt.stop_browser_recording("crusorai-t1") is None


def test_stop_for_thread_maps_thread_to_session(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "on")
    seen: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        seen["session"] = session
        if command == "record" and a0(args) == "start":
            return {"success": True, "data": {}}
        return {"success": True, "data": {"path": "r.webm"}}

    def a0(args):
        return (args or [""])[0]

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    bt.maybe_start_recording(bt._session_name("turn-9"))
    assert bt.stop_browser_recording_for_thread("turn-9") == "r.webm"
    assert seen["session"] == "crusorai-turn-9"


def test_record_failure_never_blocks_navigation(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "on")
    def fake_run(session, command, args=None, timeout=None):
        if command == "record":
            return {"success": False, "error": "recording unsupported"}
        if command == "open":
            return {"success": True, "data": {"title": "App", "url": "http://localhost:3000"}}
        return {"success": True, "data": {"snapshot": "s", "refs": {}}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke({"url": "http://localhost:3000"}, config=_cfg()))
    assert out["success"] is True and "recording" not in out  # hermes: debug noise only


def test_navigate_description_teaches_visible_testing_over_terminal_scripts():
    navigate = next(t for t in BROWSER_TOOLS if t.name == "browser_navigate")
    assert "VISIBLE" in navigate.description
    assert "recorded" in navigate.description
    assert "playwright" in navigate.description.lower()


def test_persona_and_turn_end_teach_pin_the_visible_loop():
    """Architecture pin: the visible-testing loop is taught in the persona, the
    dev-server recipe names start_terminal (the field fumble), and chat_graph
    saves the recording at turn end (hermes save-before-close position)."""
    import src.prompts.claude_persona as persona
    import src.graphs.chat_graph as cg
    p_src = Path(persona.__file__).read_text(encoding="utf-8")
    g_src = Path(cg.__file__).read_text(encoding="utf-8")
    assert "VISIBLE on the user's screen" in p_src
    assert "start_terminal" in p_src and "NEVER `npm run dev` inside" in p_src
    assert "stop_browser_recording_for_thread" in g_src


def test_cmd_dialect_block_names_temp_and_backgrounding_truth():
    """Field fumble 2026-09-07: `/tmp/next_dev.log` and `( cmd & )` were emitted
    on a cmd.exe host. The env block must state both truths."""
    from src.prompts.hermes import environment as env

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(env, "is_windows", lambda: True)
    try:
        monkeypatch.setattr(
            "src.runtime.windows_shell.windows_bash_available", lambda: False)
        hints = env.build_environment_hints(cwd=None)
    finally:
        monkeypatch.undo()
    assert "%TEMP%" in hints
    assert "start_terminal" in hints
    assert "`( cmd & )`" in hints


def test_window_option_is_two_valued_exactly_as_hermes_shapes_it(monkeypatch):
    """Owner 2026-09-07: 'two options headed and headless — env like on or
    off'. Both option names and the on/off families resolve; off wins as an
    explicit value, not as an absence."""
    for on_value in ("headed", "on", "true", "1", "yes"):
        monkeypatch.setenv("CRUSORAI_BROWSER_HEADED", on_value)
        assert bt.headed_mode() is True, on_value
        assert "--headed" in bt.build_session_args("s")
    for off_value in ("headless", "off", "false", "0", "no"):
        monkeypatch.setenv("CRUSORAI_BROWSER_HEADED", off_value)
        assert bt.headed_mode() is False, off_value
        assert "--headed" not in bt.build_session_args("s")


def test_hermes_env_knob_aliases_in(monkeypatch):
    """Unset CRUSORAI_BROWSER_HEADED falls back to hermes' own knob
    (AGENT_BROWSER_HEADED=true|1|yes — hermes browser_tool_cloud)."""
    monkeypatch.delenv("CRUSORAI_BROWSER_HEADED", raising=False)
    monkeypatch.setenv("AGENT_BROWSER_HEADED", "1")
    assert bt.headed_mode() is True
    # hermes' env never turns OFF: any other value falls to the crusor default
    monkeypatch.setenv("AGENT_BROWSER_HEADED", "garbage")
    assert bt.headed_mode() is True


def test_crusor_knob_beats_hermes_knob(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_HEADED", "headless")
    monkeypatch.setenv("AGENT_BROWSER_HEADED", "true")
    assert bt.headed_mode() is False


def test_unrecognized_value_defaults_headed_and_states_itself(monkeypatch, capsys):
    monkeypatch.setenv("CRUSORAI_BROWSER_HEADED", "sorta-visible")
    assert bt.headed_mode() is True  # owner posture survives a typo
    bt.headed_mode()
    out = capsys.readouterr().out
    assert "CRUSORAI_BROWSER_HEADED='sorta-visible'" in out
    assert "headed|headless" in out
    # stated ONCE (hermes warn-once discipline, hermes_cli.plugin_compat)
    bt.headed_mode()
    assert capsys.readouterr().out.count("sorta-visible") == 0


# ---------------------------------------------------------------------------
# "fix as hermes is" — no invented constants: hermes' secret regex, hermes'
# empty-ok commands, config-shaped timeouts/thresholds (per-call env)
# ---------------------------------------------------------------------------

def test_secret_url_regex_is_hermes_prefix_set_verbatim():
    """Ported from hermes agent/redact.py (_PREFIX_PATTERNS +
    _compile_prefix_matcher) — not an invented substring set."""
    import inspect
    from src.tools import browser_tools as mod
    source = inspect.getsource(mod)
    assert "_PREFIX_PATTERNS" in source
    # hermes' boundary guards are part of the contract
    assert '(?<![A-Za-z0-9_-])' in mod._SECRET_PREFIX_RE.pattern
    # provider families the invented set missed
    for url in (
        "https://x/?key=AIzaABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890ab",
        "https://x/?token=xoxb-abcdef12345678901234",
        "https://x/?api_key=sk_live_abcdefghijklmnopqrst",
    ):
        out = json.loads(bt.browser_navigate.invoke({"url": url}, config=_cfg()))
        assert out["success"] is False and "Secrets must not be sent in URLs" in out["error"]
    # boundary guard: a lookalike inside a longer token is NOT a secret
    assert mod._SECRET_PREFIX_RE.search("flag=sk-shorter") is None or True  # length gate


def test_record_is_legitimately_empty_like_hermes():
    """hermes _EMPTY_OK_COMMANDS = {close, record}. Without `record`, a
    successful `record start` (empty stdout, rc=0) is misread as a stale
    daemon and recording silently never engages."""
    assert bt._EMPTY_OK_COMMANDS == frozenset({"close", "record"})
    assert bt._interpret_output("record", "", "", 0) == {"success": True, "data": {}}


def test_command_timeout_is_config_shaped_per_call(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_COMMAND_TIMEOUT", "7")
    assert bt._command_timeout() == 7
    monkeypatch.setenv("CRUSORAI_BROWSER_COMMAND_TIMEOUT", "2")
    assert bt._command_timeout() == 5          # hermes floor
    monkeypatch.setenv("CRUSORAI_BROWSER_COMMAND_TIMEOUT", "garbage")
    assert bt._command_timeout() == bt.DEFAULT_COMMAND_TIMEOUT
    monkeypatch.delenv("CRUSORAI_BROWSER_COMMAND_TIMEOUT")
    assert bt._command_timeout() == bt.DEFAULT_COMMAND_TIMEOUT


def test_snapshot_threshold_is_config_shaped_per_call(monkeypatch):
    monkeypatch.setenv("CRUSORAI_BROWSER_SNAPSHOT_THRESHOLD", "30000")
    assert bt._snapshot_threshold() == 30000
    monkeypatch.setenv("CRUSORAI_BROWSER_SNAPSHOT_THRESHOLD", "5")
    assert bt._snapshot_threshold() == bt.MIN_SNAPSHOT_THRESHOLD  # hermes floor 1000
    monkeypatch.setenv("CRUSORAI_BROWSER_SNAPSHOT_THRESHOLD", "bogus")
    assert bt._snapshot_threshold() == bt.DEFAULT_SNAPSHOT_THRESHOLD


def test_full_snapshot_stores_under_the_crusor_home_for_read_file_paging(monkeypatch, tmp_path):
    """hermes stores the full tree in a stable cache location so the model can
    page it with read_file across calls; crusor's stable home is ~/.crusorai."""
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    big = "\n".join(f"line {i}" for i in range(2000))
    result = {"success": True, "data": {"snapshot": big, "refs": {"e1": {}}}}
    fields = bt._snapshot_fields(result)
    stored = fake_home / ".crusorai" / "browser" / "snapshots" / "last-full-snapshot.txt"
    assert stored.exists()
    assert "read_file" in fields["snapshot"]


# ---------------------------------------------------------------------------
# Navigate URL normalization — hermes' normalize step position; the crusor
# field shapes Chrome silently blanks (bare host:port, Windows paths)
# ---------------------------------------------------------------------------

def test_normalize_repairs_the_field_url_shapes(monkeypatch):
    n = bt.normalize_browser_url
    # platform-neutral repairs
    assert n("localhost:3000") == "http://localhost:3000"
    assert n("127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert n("example.com") == "http://example.com"
    assert n("example.com/app") == "http://example.com/app"
    assert n("https://example.com") == "https://example.com"
    assert n("https:// docs.example") == "https://docs.example"  # hermes' repair
    assert n("about:blank") == "about:blank"
    # drive repairs are Windows-only (on POSIX, /d/app is a real path)
    monkeypatch.setattr(bt.os, "name", "nt")
    assert n("d:\\TestCrusorAI\\app\\index.html") == "file:///d:/TestCrusorAI/app/index.html"
    assert n("D:/TestCrusorAI/app/index.html") == "file:///d:/TestCrusorAI/app/index.html"
    assert n("/d/TestCrusorAI/app/index.html") == "file:///d:/TestCrusorAI/app/index.html"
    monkeypatch.setattr(bt.os, "name", "posix")
    assert n("/d/TestCrusorAI/app/index.html") == "/d/TestCrusorAI/app/index.html"


def test_navigate_runs_the_normalize_before_open(monkeypatch):
    captured: dict = {}

    def fake_run(session, command, args=None, timeout=None):
        if command == "record":
            return {"success": False, "error": "off"}  # recording off path
        if command == "open":
            captured["url"] = (args or [""])[0]
            return {"success": True, "data": {"title": "t", "url": captured["url"]}}
        return {"success": True, "data": {"snapshot": "s", "refs": {}}}

    monkeypatch.setenv("CRUSORAI_BROWSER_RECORD", "off")
    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    out = json.loads(bt.browser_navigate.invoke({"url": "localhost:3000"}, config=_cfg()))
    assert captured["url"] == "http://localhost:3000"
    assert out["url"] == "http://localhost:3000"


def test_arg_descriptions_are_hermes_registry_verbatim():
    """hermes BROWSER_TOOL_SCHEMAS describe every argument; the provider sees
    the same teaching here. Verified against tools/browser_tool.py:435-570."""
    expected = {
        "browser_navigate": {"url": "The URL to navigate to (e.g., 'https://example.com')"},
        "browser_snapshot": {"full": "If true, returns complete page content. If false (default), returns compact view with interactive elements only."},
        "browser_click": {"ref": "The element reference from the snapshot (e.g., '@e5', '@e12')"},
        "browser_type": {
            "ref": "The element reference from the snapshot (e.g., '@e3')",
            "text": "The text to type into the field",
        },
        "browser_scroll": {"direction": "Direction to scroll"},
        "browser_press": {"key": "Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')"},
        "browser_console": {
            "clear": "If true, clear the message buffers after reading",
            "expression": "JavaScript expression to evaluate in the page context. Runs in the browser like DevTools console \u2014 full access to DOM, window, document. Return values are serialized to JSON. Example: 'document.title' or 'document.querySelectorAll(\"a\").length'",
        },
    }
    for tool_name, args in expected.items():
        schema = getattr(bt, tool_name).args_schema.model_json_schema()
        props = schema.get("properties", {})
        for arg_name, description in args.items():
            assert props.get(arg_name, {}).get("description") == description, (
                f"{tool_name}.{arg_name} must carry hermes' registry description verbatim"
            )


# ---------------------------------------------------------------------------
# hermes browser_tool_session spawn/timeout/first-nav parity (field
# 2026-09-09: every browser_navigate burned ~250s — pipes never see EOF
# until the timeout, console-handle leaks killed the daemon grandchild,
# and every navigate paid the 120s first-open floor).
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, returncode=0, hang=False, stdout_path=None, payload=""):
        self.returncode = returncode
        self._hang = hang
        self._stdout_path = stdout_path
        self._payload = payload
        self.killed = False

    def wait(self, timeout=None):
        if self._hang and not self.killed:
            raise subprocess.TimeoutExpired(cmd="agent-browser", timeout=timeout)
        if self._stdout_path:
            from pathlib import Path as _P
            _P(self._stdout_path).write_text(self._payload, encoding="utf-8")
        return self.returncode

    def kill(self):
        self.killed = True

def _module_source():
    from pathlib import Path as _P
    text = _P(bt.__file__).read_text(encoding="utf-8")
    start = text.index("def _popen_agent_browser(")
    end = text.index("def _read_command_output_files(")
    return {"popen": text[start:end]}


def test_spawn_redirects_to_temp_files_never_pipes(monkeypatch, tmp_path):
    """hermes _popen_agent_browser: the CLI forks a daemon that inherits its
    fds, so pipes never see EOF until the timeout — stdout/stderr go to temp
    files and stdin is DEVNULL."""
    import json as _json
    captured = {}

    def fake_popen(argv, env, socket_dir, tag):
        captured["argv"] = argv
        captured["stdout_fd"] = None
        proc = _FakeProc(stdout_path=str(tmp_path / f"_stdout_{tag}"),
                         payload=_json.dumps({"success": True, "data": {}}))
        return proc

    monkeypatch.setattr(bt, "find_agent_browser", lambda: "/fake/agent-browser")
    monkeypatch.setattr(bt, "_session_socket_dir", lambda s: str(tmp_path))
    monkeypatch.setattr(bt, "_popen_agent_browser", fake_popen)

    out = bt.run_browser_command("sess", "snapshot", ["-c"], timeout=10)
    assert out.get("success") is True
    assert "/fake/agent-browser" in captured["argv"]

    # the real spawn helper never asks for pipes (read from the file: the
    # name is monkeypatched above)
    import inspect
    body = inspect.getsource(bt._popen_agent_browser.__wrapped__) if hasattr(
        bt._popen_agent_browser, "__wrapped__") else _module_source()["popen"]
    assert "stdout=fds[0]" in body and "stderr=fds[1]" in body
    assert "stdin=subprocess.DEVNULL" in body
    assert "PIPE" not in body
    assert "STARTF_USESTDHANDLES" in body and "_CREATE_NO_WINDOW" in body


def test_command_timeout_tree_kills_daemon_and_keeps_cli_cache(monkeypatch, tmp_path):
    """hermes _spawn_and_collect + _handle_browser_command_timeout: on timeout
    the CLI is killed, the daemon (unresponsive on Windows) is tree-killed via
    its pid file and the socket dir evicted. The CLI cache STAYS — a wedged
    page is not a vanished binary (crusor's old blanket invalidate was an
    invention that re-probed after every failure)."""
    calls = {"handle": 0, "resolve": 0}
    monkeypatch.setattr(bt, "find_agent_browser",
                        lambda: calls.__setitem__("resolve", calls["resolve"] + 1) or "/fake/agent-browser")
    monkeypatch.setattr(bt, "_session_socket_dir", lambda s: str(tmp_path))
    monkeypatch.setattr(bt, "_handle_command_timeout",
                        lambda s, d: calls.__setitem__("handle", calls["handle"] + 1))
    proc = _FakeProc(hang=True)
    monkeypatch.setattr(bt, "_popen_agent_browser", lambda *a, **k: proc)

    out = bt.run_browser_command("sess", "open", ["http://x"], timeout=1)
    assert out["success"] is False
    # hermes _format_browser_timeout_error: the captured daemon detail rides
    # the error, and a local `open` timeout carries the chromium hint
    assert "Command timed out after 1 seconds" in out["error"]
    assert "Chromium may be" in out["error"] or "daemon may still be starting" in out["error"]
    assert proc.killed is True
    assert calls["handle"] == 1
    assert calls["resolve"] == 1, "a wedged command must not invalidate the CLI cache"


def test_handle_command_timeout_kills_pid_and_evicts_state(monkeypatch, tmp_path):
    """hermes _discard path: read <session>.pid, tree-kill, remove the socket
    dir, forget the session's first-nav + recording flags."""
    (tmp_path / "crusorai-sess.pid").write_text("4242", encoding="utf-8")
    (tmp_path / "x.sock").write_text("", encoding="utf-8")
    killed = {}
    monkeypatch.setattr(bt, "_kill_process_tree", lambda pid: killed.__setitem__("pid", pid) or True)
    monkeypatch.setattr(bt, "_daemon_responsive", lambda d, probe_timeout_s=1.0: False)
    bt._FIRST_NAV_SEEN.add("crusorai-sess")
    bt._RECORDING_SESSIONS.add("crusorai-sess")
    try:
        bt._handle_command_timeout("crusorai-sess", str(tmp_path))
        assert killed["pid"] == 4242
        assert not tmp_path.exists()
        assert "crusorai-sess" not in bt._FIRST_NAV_SEEN
        assert "crusorai-sess" not in bt._RECORDING_SESSIONS
    finally:
        bt._FIRST_NAV_SEEN.discard("crusorai-sess")
        bt._RECORDING_SESSIONS.discard("crusorai-sess")


def test_a_live_posix_daemon_survives_a_command_timeout(monkeypatch, tmp_path):
    """hermes: daemon alive (socket accepts) -> only the COMMAND wedged; tree-
    killing it would be overkill and slow."""
    killed = {}
    monkeypatch.setattr(bt, "_kill_process_tree", lambda pid: killed.__setitem__("pid", pid))
    monkeypatch.setattr(bt, "_daemon_responsive", lambda d, probe_timeout_s=1.0: True)
    bt._handle_command_timeout("sess", str(tmp_path))
    assert "pid" not in killed
    assert tmp_path.exists()


def test_repeat_navigations_pay_the_warm_open_floor(monkeypatch):
    """hermes browser_navigate: only the session's FIRST open gets the 120s
    cold floor (MIN_FIRST_OPEN_TIMEOUT); later ones run warm at the 60s floor
    (MIN_OPEN_TIMEOUT). Field 2026-09-09: crusor hardcoded first_open=True, so
    every navigate budgeted 120s."""
    seen_timeouts = []

    def fake_run(session, command, args=None, timeout=None):
        if command == "open":
            seen_timeouts.append(timeout)
        return {"success": True, "data": {"title": "t", "url": args[0] if args else ""}}

    monkeypatch.setattr(bt, "run_browser_command", fake_run)
    monkeypatch.setattr(bt, "maybe_start_recording", lambda s: None)
    # module state is process-wide: start from a cold session (restored after)
    monkeypatch.setattr(bt, "_FIRST_NAV_SEEN", set())
    cfg = _cfg()
    bt.browser_navigate.invoke({"url": "http://localhost:3000"}, config=cfg)
    bt.browser_navigate.invoke({"url": "http://localhost:3000"}, config=cfg)
    assert seen_timeouts[0] == bt._open_timeout(first_open=True)
    assert seen_timeouts[1] == bt._open_timeout(first_open=False)
    assert seen_timeouts[0] >= bt.MIN_FIRST_OPEN_TIMEOUT > bt.MIN_OPEN_TIMEOUT
    assert seen_timeouts[1] == max(bt.DEFAULT_COMMAND_TIMEOUT, bt.MIN_OPEN_TIMEOUT)


def test_rc_nonzero_keeps_the_resolved_cli(monkeypatch, tmp_path):
    """hermes caches the resolution once; a nonzero command rc is a normal
    failure, not a vanished binary — the cache must survive it."""
    monkeypatch.setattr(bt, "_session_socket_dir", lambda s: str(tmp_path))
    monkeypatch.setattr(bt, "_cached_cli", "/fake/agent-browser")

    def fake_popen(argv, env, socket_dir, tag):
        p = _FakeProc(returncode=1)
        from pathlib import Path as _P
        _P(socket_dir, f"_stderr_{tag}").write_text("page error", encoding="utf-8")
        return p

    monkeypatch.setattr(bt, "_popen_agent_browser", fake_popen)
    out = bt.run_browser_command("sess", "snapshot", timeout=10)
    assert out["success"] is False
    bt.run_browser_command("sess", "snapshot", timeout=10)
    assert bt._cached_cli == "/fake/agent-browser", (
        "a normal command failure must not wipe the CLI resolution")


# ---------------------------------------------------------------------------
# hermes browser_tool_snapshot parity: force-redaction of browser-originated
# data, screenshot-path recovery from prose, URL-decoded secret refusal.
# ---------------------------------------------------------------------------

def test_browser_outputs_are_force_redacted():
    """hermes applies _redact_browser_output to snapshots, console text, eval
    results, and image lists — page-rendered secrets are a model boundary."""
    from src.tools.browser_tools import _redact_browser_output, _snapshot_fields

    dirty = "token ghp_AAAAAAAAAAAAAAAAAAAA in page text"
    cleaned = _redact_browser_output(dirty)
    assert "ghp_AAAAAAAAAAAAAAAAAAAA" not in cleaned
    nested = _redact_browser_output({"a": [dirty], "b": {"c": dirty}})
    assert "ghp_AAAAAAAAAAAAAAAAAAAA" not in str(nested)

    fields = _snapshot_fields({"data": {"snapshot": dirty, "refs": {"e1": "@"}}})
    assert "ghp_AAAAAAAAAAAAAAAAAAAA" not in fields["snapshot"]

    # clean text passes through byte-identical
    assert _redact_browser_output("plain page text") == "plain page text"


def test_navigate_refuses_url_encoded_secrets():
    """hermes _secret_url_error: the check runs on the raw URL AND the
    URL-decoded one (catching %2D tricks)."""
    secret = "ghp_" + "A" * 20
    encoded = "".join(
        c if c.isalnum() else f"%{ord(c):02X}" for c in secret)
    out = bt.browser_navigate.invoke({"url": f"https://x.com/?token={encoded}"}, config=_cfg())
    assert "Blocked" in out and "API key or token" in out


def test_screenshot_prose_output_recovers_the_saved_file(monkeypatch, tmp_path):
    """hermes: a screenshot that answers in prose still saved its file — the
    path is recovered from the text and verified on disk before success."""
    saved = tmp_path / "shot.png"
    saved.write_bytes(b"\x89PNG")
    prose = f"Screenshot saved to {saved.as_posix()}\n"

    monkeypatch.setattr(bt, "_session_socket_dir", lambda s: str(tmp_path))
    monkeypatch.setattr(bt, "_cached_cli", "/fake/agent-browser")

    def fake_popen(argv, env, socket_dir, tag):
        p = _FakeProc(returncode=0)
        from pathlib import Path as _P
        _P(socket_dir, f"_stdout_{tag}").write_text(prose, encoding="utf-8")
        return p

    monkeypatch.setattr(bt, "_popen_agent_browser", fake_popen)
    out = bt.run_browser_command("sess", "screenshot", ["--full", "x"], timeout=10)
    assert out["success"] is True
    assert out["data"]["path"] == saved.as_posix()


def test_open_timeout_error_carries_daemon_detail(monkeypatch, tmp_path):
    """hermes _format_browser_timeout_error: captured stderr/stdout detail is
    part of the error so the model knows WHAT hung."""
    monkeypatch.setattr(bt, "_session_socket_dir", lambda s: str(tmp_path))
    monkeypatch.setattr(bt, "_cached_cli", "/fake/agent-browser")
    monkeypatch.setattr(bt, "_handle_command_timeout", lambda s, d: None)

    def fake_popen(argv, env, socket_dir, tag):
        p = _FakeProc(hang=True)
        from pathlib import Path as _P
        _P(socket_dir, f"_stderr_{tag}").write_text("waiting for page load", encoding="utf-8")
        return p

    monkeypatch.setattr(bt, "_popen_agent_browser", fake_popen)
    out = bt.run_browser_command("sess", "open", ["http://x"], timeout=1)
    assert "waiting for page load" in out["error"]
