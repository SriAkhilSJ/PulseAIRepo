"""Continuous-parent tool disclosure through the real binding and dispatch seams."""
from __future__ import annotations

import json
from typing import Annotated
from langgraph.graph.message import add_messages

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from src.context.safety_guard import SafetyGuard
from src.graphs import chat_graph as cg
from src.tools.progressive_tools import activated_tools


@pytest.fixture(autouse=True)
def continuous(monkeypatch):
    monkeypatch.setenv("AGENT_CONTINUOUS_EXECUTION", "1")
    monkeypatch.delenv("CRUSORAI_PROGRESSIVE_TOOLS", raising=False)
    monkeypatch.delenv("CRUSORAI_MAX_TOOLS", raising=False)


def bind(tmp_path, state=None, **cfg):
    config = {"configurable": {"workspace": str(tmp_path), "thread_id": "progressive-test", **cfg}}
    state = state or {"current_task": "make and verify a project", "messages": [HumanMessage(content="Build it")]}
    bound = cg._resolve_bound_tools(state, config)
    return state, config, bound


def invoke(node, state, config, name, args, id="call1"):
    call = {"id": id, "name": name, "args": args, "type": "tool_call"}
    pending = {**state, "messages": [*(state.get("messages") or []), AIMessage(content="", tool_calls=[call])],
               "progressive_tool_surface": config["configurable"].get("progressive_tool_surface")}
    # Deliberately drop the binding-time config to model LangGraph node isolation.
    dispatch_config = {"configurable": {"thread_id": "progressive-test", "workspace": config["configurable"]["workspace"]}}
    return node(pending, dispatch_config)["messages"]


def test_real_discovery_dispatch_activation_and_phase_gate(tmp_path):
    state, config, bound = bind(tmp_path)
    names = {t.name for t in bound}
    catalog = config["configurable"]["progressive_tool_surface"]["catalog"]
    assert {"write_file", "browser_navigate", "todo_list", "discover_tools"} <= names
    assert "generate_image" not in names
    assert "generate_image" in {entry["name"] for entry in catalog}
    node = cg.SafeToolNode(cg.tools, SafetyGuard())

    # A guessed non-bound call is denied even with a fresh node config.
    denied = invoke(node, state, config, "generate_image", {"prompt": "test", "file_path": "x.png"})
    assert "PHASE POLICY DENIED" in str(denied[0].content)
    assert not (tmp_path / "x.png").exists()

    receipt = invoke(node, state, config, "discover_tools", {"names": ["generate_image", "missing_tool"]})[0]
    data = json.loads(receipt.content)
    assert data["activated"] == ["generate_image"]
    assert data["unavailable"] == ["missing_tool"]
    state["messages"] += [AIMessage(content="", tool_calls=[{"id": "call1", "name": "discover_tools", "args": {"names": ["generate_image", "missing_tool"]}}]), receipt]
    _, config2, after = bind(tmp_path, state)
    assert "generate_image" in {t.name for t in after}
    assert "generate_image" in config2["configurable"]["phase_allowed_tools"]
    assert "missing_tool" not in {t.name for t in after}


def test_eligibility_rechecked_and_new_user_turn_resets(tmp_path, monkeypatch):
    state, config, _ = bind(tmp_path)
    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    receipt = invoke(node, state, config, "discover_tools", {"names": ["browser_scroll"]})[0]
    state["messages"] += [receipt]
    # The next user turn does not inherit old activations.
    state["messages"].append(HumanMessage(content="A different request"))
    _, _, bound = bind(tmp_path, state)
    assert "browser_scroll" not in {t.name for t in bound}
    assert activated_tools(state["messages"]) == set()


def test_no_activation_from_failure_or_non_receipt():
    messages = [HumanMessage(content="x"), ToolMessage(name="discover_tools", tool_call_id="x", status="error", content='{"activated":["generate_image"]}')]
    assert activated_tools(messages) == set()
    assert activated_tools([HumanMessage(content='{"activated":["generate_image"]}')]) == set()


def test_neutral_surface_not_task_keyword_based(tmp_path):
    sets = []
    for task in ("hi", "verify a browser", "write an app", "写一个网站"):
        _, _, bound = bind(tmp_path, {"current_task": task, "messages": [HumanMessage(content=task)]})
        sets.append({t.name for t in bound})
    assert all(names == sets[0] for names in sets)


def test_kill_switch_and_strict_scope_are_not_bypassed(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_PROGRESSIVE_TOOLS", "off")
    _, config, full = bind(tmp_path)
    assert "discover_tools" not in {t.name for t in full}
    assert "generate_image" in {t.name for t in full}
    assert config["configurable"]["phase_allowed_tools"] is None
    monkeypatch.delenv("CRUSORAI_PROGRESSIVE_TOOLS")
    _, config, child = bind(tmp_path, scope_capabilities_strict=True, scope_capabilities=["read_file"])
    assert "discover_tools" not in {t.name for t in child}
    assert config["configurable"]["progressive_tool_surface"]["allowed"] == [t.name for t in child]


def test_offline_schema_measurement(tmp_path, monkeypatch):
    _, _, reduced = bind(tmp_path)
    monkeypatch.setenv("CRUSORAI_PROGRESSIVE_TOOLS", "off")
    _, _, full = bind(tmp_path)
    size = lambda tools: len(json.dumps([convert_to_openai_tool(t) for t in tools], ensure_ascii=False))
    assert len(reduced) < len(full)
    assert size(reduced) < size(full) * .7


def test_explicit_cap_and_child_thread_are_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUSORAI_MAX_TOOLS", "3")
    _, config, bound = bind(tmp_path)
    assert len(bound) <= 3
    assert "discover_tools" not in {t.name for t in bound}
    assert config["configurable"]["progressive_tool_surface"]["allowed"] == [t.name for t in bound]
    monkeypatch.delenv("CRUSORAI_MAX_TOOLS")
    _, config, bound = bind(tmp_path, thread_id="sub-abc")
    assert "discover_tools" not in {t.name for t in bound}
    assert config["configurable"].get("progressive_tool_surface") is None


def test_snapshot_accounts_for_tool_call_arguments():
    from src.llm.factory import build_request_snapshot
    class Binding:
        kwargs = {"tools": []}
    msg = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"content": "x" * 3000}, "id": "c"}])
    snapshot = build_request_snapshot([msg], Binding())
    assert snapshot["message_chars"] == 0
    assert snapshot["tool_call_metadata_chars"] > 3000
    assert snapshot["serialized_messages_chars"] >= snapshot["tool_call_metadata_chars"]
    assert snapshot["snapshot_json_chars"] > snapshot["serialized_messages_chars"]


def test_discovery_survives_real_sqlite_checkpoint_and_resume(tmp_path):
    import sqlite3
    from typing import Annotated
    from typing_extensions import TypedDict
    from langgraph.graph import START, END, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.checkpoint.sqlite import SqliteSaver

    class State(TypedDict, total=False):
        messages: Annotated[list, add_messages]
        progressive_tool_surface: dict | None
        after_resume: list[str]
        current_task: str

    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    def model(state, config):
        cg._resolve_bound_tools(state, config)
        return {"progressive_tool_surface": config["configurable"].get("progressive_tool_surface"),
                "messages": [AIMessage(content="", tool_calls=[{"name": "discover_tools", "args": {"names": ["generate_image"]}, "id": "c"}])]}
    def rebind(state, config):
        return {"after_resume": [t.name for t in cg._resolve_bound_tools(state, config)]}
    graph = StateGraph(State)
    graph.add_node("model", model)
    graph.add_node("tool", node)
    graph.add_node("rebind", rebind)
    graph.add_edge(START, "model")
    graph.add_edge("model", "tool")
    graph.add_edge("tool", "rebind")
    graph.add_edge("rebind", END)
    config = {"configurable": {"thread_id": "sqlite-discovery", "workspace": str(tmp_path)}}
    with sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False) as db:
        compiled = graph.compile(checkpointer=SqliteSaver(db), interrupt_before=["rebind"])
        compiled.invoke({"current_task": "draw a picture", "messages": [HumanMessage(content="draw")]}, config)
        saved = compiled.get_state(config)
        assert saved.next == ("rebind",)
        assert json.loads(saved.values["messages"][-1].content)["activated"] == ["generate_image"]
        resumed = compiled.invoke(None, config)
        assert "generate_image" in resumed["after_resume"]


def test_stricter_phase_overrides_prior_activation(tmp_path):
    (tmp_path / "server.py").write_text("print('hi')", encoding="utf-8")
    receipt = ToolMessage(name="discover_tools", tool_call_id="c", content='{"activated":["browser_scroll"]}')
    task = "Build a complete web application.\nDeliver exactly these files at the workspace root:\n- server.py\n- index.html"
    state = {"workspace": str(tmp_path), "current_task": task,
             "latest_instruction": task, "iteration_used": 8,
             "steps_completed": ["Wrote file: server.py"],
             "execution_trace": [{"tool": "write_file", "status": "success"}],
             "messages": [HumanMessage(content="create"), receipt]}
    _, config, bound = bind(tmp_path, state, approval_policy="workspace_session")
    assert config["configurable"]["execution_phase"] == "missing_delivery"
    assert config["configurable"]["progressive_tool_surface"]["allowed"] == [t.name for t in bound]
    assert "browser_scroll" not in {t.name for t in bound}
    assert "discover_tools" not in {t.name for t in bound}
    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    denied = invoke(node, state, config, "browser_scroll", {"direction": "down"})
    assert "PHASE POLICY DENIED" in denied[0].content


def test_activation_does_not_override_permission_deny(tmp_path, monkeypatch):
    settings = tmp_path / ".crusorai" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permission": {"generate_image": "deny"}}))
    monkeypatch.setenv("CRUSORAI_AUTO_APPROVE_WRITES", "1")
    state, config, _ = bind(tmp_path)
    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    receipt = invoke(node, state, config, "discover_tools", {"names": ["generate_image"]})[0]
    assert json.loads(receipt.content)["activated"] == ["generate_image"]
    state["messages"] += [receipt]
    _, config2, bound = bind(tmp_path, state)
    assert "generate_image" in {t.name for t in bound}
    executed = []
    monkeypatch.setattr(node, "_execute_durable", lambda calls, config: executed.extend(calls) or [])
    result = invoke(node, state, config2, "generate_image", {"prompt": "picture", "file_path": "x.png"}, "denied")
    assert not executed
    assert "BLOCKED" in str(result[0].content)


def test_actual_ai_node_keeps_activation_when_context_is_compacted(tmp_path, monkeypatch):
    from langchain_core.messages import SystemMessage
    class FakeLLM:
        model = "m"
        def __init__(self):
            self.binds = []
            self.calls = 0
        def bind_tools(self, tools):
            self.binds.append([t.name for t in tools])
            return self
        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", id="a1", tool_calls=[{"id": "d1", "name": "discover_tools", "args": {"names": ["generate_image"]}}])
            return AIMessage(content="continuing", id="a2")
    class CompactEngine:
        def build_ai_messages(self, state, system_message):
            # Model context may prune the discovery pair; graph state remains durable.
            return [SystemMessage(content="summary")]
    llm = FakeLLM()
    monkeypatch.setattr(cg, "get_llm", lambda **kwargs: llm)
    monkeypatch.setattr(cg, "get_context_engine", lambda config: CompactEngine())
    config = {"configurable": {"thread_id": "progressive-ai", "workspace": str(tmp_path), "provider": "fake", "model": "m"}}
    state = {"current_task": "draw something", "messages": [HumanMessage(content="draw something")]}
    first = cg.ai_node(state, config)
    assert first["progressive_tool_surface"] and "discover_tools" in llm.binds[0]
    state = {**state, **first, "messages": state["messages"] + first["messages"]}
    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    receipt = node(state, {"configurable": {"thread_id": "progressive-ai", "workspace": str(tmp_path)}})["messages"]
    state["messages"] += receipt
    assert json.loads(receipt[0].content)["activated"] == ["generate_image"]
    second = cg.ai_node(state, config)
    assert "generate_image" in llm.binds[-1]
    assert "generate_image" in second["progressive_tool_surface"]["allowed"]


def test_denied_and_safe_batch_runs_only_safe_call_in_order(tmp_path, monkeypatch):
    settings = tmp_path / ".crusorai" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permission": {"generate_image": "deny"}}))
    monkeypatch.setenv("CRUSORAI_AUTO_APPROVE_WRITES", "1")
    state, config, _ = bind(tmp_path)
    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    receipt = invoke(node, state, config, "discover_tools", {"names": ["generate_image"]})[0]
    state["messages"] += [receipt]
    _, config, _ = bind(tmp_path, state)
    calls = [
        {"name": "generate_image", "args": {"prompt": "p", "file_path": "x.png"}, "id": "denied"},
        {"name": "read_file", "args": {"path": "safe.txt"}, "id": "safe"},
    ]
    executed = []
    def fake_execute(tcs, config):
        executed.extend(tcs)
        return [ToolMessage(name=tc["name"], tool_call_id=tc["id"], content="safe result") for tc in tcs]
    monkeypatch.setattr(node, "_execute_durable", fake_execute)
    state["messages"].append(AIMessage(content="", tool_calls=calls))
    state["progressive_tool_surface"] = config["configurable"]["progressive_tool_surface"]
    result = node(state, {"configurable": {"thread_id": "progressive-test", "workspace": str(tmp_path)}})["messages"]
    assert [tc["id"] for tc in executed] == ["safe"]
    assert [msg.tool_call_id for msg in result] == ["denied", "safe"]
    assert result[0].status == "error" and "BLOCKED" in result[0].content
    assert result[1].content == "safe result"


def test_session_availability_is_rechecked_after_activation(tmp_path, monkeypatch):
    import src.tools.browser_tools as bt
    state, _, _ = bind(tmp_path)
    state["messages"] += [ToolMessage(name="discover_tools", tool_call_id="d", content='{"activated":["browser_scroll"]}')]
    _, _, bound = bind(tmp_path, state)
    assert "browser_scroll" in {t.name for t in bound}
    monkeypatch.setenv("CRUSORAI_AGENT_BROWSER", str(tmp_path / "missing-browser"))
    bt.invalidate_cli_cache()
    try:
        _, config, bound = bind(tmp_path, state)
        assert not any(t.name.startswith("browser_") for t in bound)
        assert "browser_scroll" not in {item["name"] for item in config["configurable"]["progressive_tool_surface"]["catalog"]}
    finally:
        bt.invalidate_cli_cache()


def test_explicit_activation_response_is_compact(tmp_path):
    from src.tools.progressive_tools import discover_tools
    _, config, _ = bind(tmp_path)
    catalog = config["configurable"]["progressive_tool_surface"]["catalog"]
    receipt = discover_tools.invoke({"names": ["generate_image"]}, config={"configurable": {"progressive_tool_catalog": catalog}})
    assert len(receipt) < 500
    assert [entry["name"] for entry in json.loads(receipt)["matches"]] == ["generate_image"]


def test_strict_child_scope_resolver_error_fails_closed(tmp_path, monkeypatch):
    from src.tools import toolsets
    def fail(*args, **kwargs):
        raise RuntimeError("broken scope resolver")
    monkeypatch.setattr(toolsets, "resolve_runtime_tool_names", fail)
    with pytest.raises(RuntimeError, match="strict child tool scope"):
        bind(tmp_path, scope_capabilities_strict=True, scope_capabilities=["workspace_read"])


def test_strict_child_denies_unbound_guessed_call_after_config_reconstruction(tmp_path):
    state, config, bound = bind(tmp_path, scope_capabilities_strict=True, scope_capabilities=["workspace_read"])
    assert "write_file" not in {t.name for t in bound}
    node = cg.SafeToolNode(cg.tools, SafetyGuard())
    result = invoke(node, state, config, "write_file", {"path": "x", "content": "forbidden"})
    assert "PHASE POLICY DENIED" in result[0].content
    assert not (tmp_path / "x").exists()
