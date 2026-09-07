"""No phase lexicon: phases are STATE-derived only (hermes shape).

Hermes runs no keyword→phase machinery; steering is state-driven (todo
gates, budget reserves) plus the prompt. The former keyword lexicon here
amputated the browser tools and todo_list mid-turn in the field
(2026-09-07, "Run the build..." step) and was removed in fa5e77e8; the
lexicon's guidance-only remainder is now gone entirely — the owner's
standing rule bans hardcoded agent-behavior lexicons, not just their
enforcement.
"""
from __future__ import annotations

import inspect

from src.runtime.execution_phases import ExecutionPhase, base_phase


def test_base_phase_is_neutral_no_matter_what_words_the_plan_uses():
    for plan in (
        [],
        [{"description": "Run the build to ensure no errors", "status": "in_progress"}],
        [{"description": "Verify four browser routes and screenshots", "status": "in_progress"}],
        [{"description": "Install dependencies and scaffold the project", "status": "in_progress"}],
    ):
        phase = base_phase()
        assert phase.name == "general"
        assert phase.allowed is None
        assert phase.guidance == ""
        assert phase.max_file_mutations_per_turn == 0
        # state is not even an input — the signature is the pin
        assert "state" not in inspect.signature(base_phase).parameters


def test_the_lexicon_is_gone_from_source():
    """The banned machinery must not linger: no keyword word-lists, no env
    knob, no filter helpers, no ghost tool names."""
    from src.runtime import execution_phases as ep

    source = inspect.getsource(ep)
    for banned in (
        "PULSEAI_PHASE_GUARD", "PULSEAI_PHASE_GUIDANCE",
        "filter_tool_names", "phase_allows", "derive_execution_phase",
        "browser_select", "browser_hover", "browser_evaluate",
        "static_verify", "visual_verify",
    ):
        assert banned not in source, banned
    # the keyword cues must not survive as DATA: strip the module docstring
    # (which may quote field history) and assert no membership-test tuples
    # of steering words remain.
    import ast
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree) or ""
    body_source = source.replace(docstring, "")
    for cue in ("build", "screenshot", "scaffold", "typecheck", "deliver"):
        assert f'"{cue}"' not in body_source and f"'{cue}'" not in body_source, cue


def test_state_driven_phases_still_construct_real_allowlists():
    """chat_graph's STATE-driven phases (forced delivery, verification
    reserve) are the only non-None allowed sources; the value type keeps
    supporting them."""
    phase = ExecutionPhase("forced_delivery", frozenset({"write_file"}),
                           max_file_mutations_per_turn=2, guidance="DIRECT DELIVERY")
    assert phase.allowed == frozenset({"write_file"})
    assert base_phase().allowed is None


# ---------------------------------------------------------------------------
# The field regression, through the graph's REAL binding path
# ---------------------------------------------------------------------------

def test_browser_task_with_build_step_binds_browser_and_planning_tools(tmp_path):
    """2026-09-07 field shape: 'browser testing' task, active plan step
    'Run the build to ensure no errors'. The old lexicon stripped the
    browser tools AND todo_list here. Binding must keep them all."""
    from src.graphs.chat_graph import _resolve_bound_tools

    state = {
        "current_task": "test2 folder plz do browser testing",
        "plan": [{"description": "Run the build to ensure no errors", "status": "in_progress"}],
    }
    config = {"configurable": {
        "thread_id": "field-regression",
        "workspace": str(tmp_path),
    }}
    bound = _resolve_bound_tools(state, config)
    names = {t.name for t in bound}
    assert {"browser_navigate", "browser_screenshot", "todo_list", "think"} <= names
    # no execution-time policy may deny them either
    assert config["configurable"]["execution_phase"] == "general"
    assert config["configurable"]["phase_allowed_tools"] is None
    assert config["configurable"]["phase_guidance"] == ""


def test_state_driven_forced_delivery_phase_keeps_its_allowlist(tmp_path):
    """The one legitimate narrow: empty autonomous workspace + a task that
    requires files. It keys on STATE, not step words."""
    from src.graphs.chat_graph import _resolve_bound_tools

    state = {
        "current_task": "build me a landing page app",
        "plan": [],
        "latest_instruction": "build me a landing page app",
    }
    config = {"configurable": {
        "thread_id": "autonomous-regression",
        "workspace": str(tmp_path),          # effectively empty
        "approval_policy": "workspace_session",  # autonomous surface
    }}
    bound = _resolve_bound_tools(state, config)
    names = {t.name for t in bound}
    phase_name = config["configurable"]["execution_phase"]
    assert phase_name in {"forced_delivery", "general"}
    if phase_name == "forced_delivery":
        assert names <= {"write_file", "edit_file", "copy_file"}
        assert config["configurable"]["phase_allowed_tools"] is not None


# ---------------------------------------------------------------------------
# Hermes registry binding (agent_init._load_tools): full registry every turn,
# availability check_fn, operator/state narrows only — NO task-text matching
# ---------------------------------------------------------------------------

def test_binding_is_the_registry_snapshot_regardless_of_task_wording(tmp_path):
    """hermes binds the same registry for 'hi' and for a build task. Pulse's
    former task-keyword waist (runtime_profile regexes over current_task) is
    retired from binding: any phrasing gets the full surface."""
    from src.graphs.chat_graph import _resolve_bound_tools

    for task in ("hi", "test my app works", "fix the bug", "写一个网站"):
        config = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
        names = {t.name for t in _resolve_bound_tools({"current_task": task}, config)}
        assert "run_terminal" in names, task
        assert "web_search" in names, task
        assert "todo_list" in names, task
        assert "write_file" in names, task
        # no per-task phase/guidance leaked from task WORDS
        assert config["configurable"]["execution_phase"] == "general", task
        assert config["configurable"]["phase_allowed_tools"] is None, task


def test_browser_tools_bound_when_cli_resolves_hidden_when_it_doesnt(tmp_path, monkeypatch):
    """hermes check_fn: a tool whose deps are missing is not registered. The
    CLI resolution is cached — the check costs one fast raise when missing."""
    from src.graphs.chat_graph import _resolve_bound_tools
    import src.tools.browser_tools as bt

    config = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
    monkeypatch.delenv("PULSEAI_AGENT_BROWSER", raising=False)
    names = {t.name for t in _resolve_bound_tools({"current_task": "x"}, config)}
    assert "browser_navigate" in names  # real resolution succeeds in CI (npx sentinel)

    bt.invalidate_cli_cache()
    monkeypatch.setenv("PULSEAI_AGENT_BROWSER", str(tmp_path / "no-such-browser"))
    bt.invalidate_cli_cache()
    names = {t.name for t in _resolve_bound_tools({"current_task": "x"}, config)}
    assert not any(name.startswith("browser_") for name in names)
    assert "run_terminal" in names  # everything else survives
    bt.invalidate_cli_cache()


def test_typecheck_hidden_only_by_workspace_state(tmp_path):
    """check_fn on project state: no tsconfig -> no typecheck_workspace —
    regardless of task words (kept from the hermes availability shape)."""
    from src.graphs.chat_graph import _resolve_bound_tools

    config = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
    names = {t.name for t in _resolve_bound_tools(
        {"current_task": "typecheck everything"}, config)}
    assert "typecheck_workspace" not in names

    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    config2 = {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}}
    names2 = {t.name for t in _resolve_bound_tools(
        {"current_task": "typecheck everything"}, config2)}
    assert "typecheck_workspace" in names2


# ---------------------------------------------------------------------------
# Availability receipt — hermes agent_init._load_tools ("⚠️ Some tools may
# not work due to missing requirements"), once per process, names the fix
# ---------------------------------------------------------------------------

def test_availability_receipt_names_the_install_fix_once(tmp_path, monkeypatch, capsys):
    """Field 2026-09-07 1:34 PM: the browser stack was silently hidden and
    nobody could tell why. The first binding must print WHICH tools are
    unavailable and the install step; later bindings stay quiet (hermes
    prints the load line once)."""
    from src.graphs.chat_graph import _resolve_bound_tools
    import src.graphs.chat_graph as cg
    import src.tools.browser_tools as bt

    monkeypatch.setenv("PULSEAI_AGENT_BROWSER", str(tmp_path / "nope"))
    bt.invalidate_cli_cache()
    cg._TOOL_AVAILABILITY_REPORTED = False
    try:
        names = {t.name for t in _resolve_bound_tools({"current_task": "x"},
                                                      {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}})}
        assert not any(name.startswith("browser_") for name in names)
        out = capsys.readouterr().out
        assert "[tools] binding" in out
        assert "agent-browser" in out and "npm install -g agent-browser" in out
        # second binding: no repeat (hermes load-line discipline)
        _resolve_bound_tools({"current_task": "x"},
                             {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}})
        assert capsys.readouterr().out.count("[tools] binding") == 0
        # available stack binds without the receipt (nothing hidden: the
        # workspace gets a tsconfig so typecheck_workspace binds too)
        bt.invalidate_cli_cache()
        monkeypatch.delenv("PULSEAI_AGENT_BROWSER", raising=False)
        (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        cg._TOOL_AVAILABILITY_REPORTED = False
        names = {t.name for t in _resolve_bound_tools({"current_task": "x"},
                                                      {"configurable": {"thread_id": "t", "workspace": str(tmp_path)}})}
        assert "browser_navigate" in names
        assert capsys.readouterr().out.count("[tools] binding") == 0
    finally:
        bt.invalidate_cli_cache()
        cg._TOOL_AVAILABILITY_REPORTED = False


def test_env_block_states_browser_unavailability_as_host_fact(tmp_path, monkeypatch):
    """hermes paints toolset availability; the model-facing carrier here is
    the env block. The fact fires only when the CLI is actually missing —
    state, never task wording."""
    from src.prompts.hermes.environment import build_environment_hints
    import src.tools.browser_tools as bt

    monkeypatch.setenv("PULSEAI_AGENT_BROWSER", str(tmp_path / "nope"))
    bt.invalidate_cli_cache()
    try:
        hints = build_environment_hints(cwd=None)
        assert "Browser tools: NOT available" in hints
        assert "npm install -g agent-browser" in hints
    finally:
        bt.invalidate_cli_cache()
    # available stack: no availability line at all
    monkeypatch.delenv("PULSEAI_AGENT_BROWSER", raising=False)
    bt.invalidate_cli_cache()
    try:
        hints = build_environment_hints(cwd=None)
        assert "Browser tools: NOT available" not in hints
    finally:
        bt.invalidate_cli_cache()
