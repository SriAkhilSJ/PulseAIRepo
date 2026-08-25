"""Contracts for the headless runtime repairs found after Test 5 attempt 6."""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.lazy_memory import LazyMemoryManager
from src.llm.factory import build_request_snapshot
from src.prompts.claude_persona import AUTONOMOUS_SYSTEM_PERSONA, system_persona


def test_lazy_memory_does_not_construct_until_first_method_call():
    calls = []

    class Memory:
        def retrieve_relevant_memories(self, query, top_k=2):
            return [{"query": query}]

    manager = LazyMemoryManager(lambda: calls.append("constructed") or Memory())
    assert calls == []
    assert manager.initialized is False
    assert manager.retrieve_relevant_memories("task") == [{"query": "task"}]
    assert calls == ["constructed"]
    assert manager.initialized is True


def test_lazy_memory_failure_is_sticky_and_degrades_to_empty():
    calls = []

    def fail():
        calls.append("attempt")
        raise RuntimeError("offline")

    manager = LazyMemoryManager(fail)
    assert manager.retrieve_relevant_memories("one") == []
    assert manager.retrieve_relevant_memories("two") == []
    assert calls == ["attempt"]
    assert manager.disabled is True


def test_autonomous_persona_is_short_and_has_no_meta_tool_directives():
    persona = system_persona(autonomous=True)
    assert persona == AUTONOMOUS_SYSTEM_PERSONA
    assert len(persona) < 2_000
    lowered = persona.lower()
    assert "think()" not in lowered
    assert "execute_code" not in lowered
    assert "delegate" not in lowered
    assert "ask_user" not in lowered
    assert "write_file" in lowered


def test_request_snapshot_preserves_complete_payload_and_is_deterministic():
    class Binding:
        kwargs = {
            "tools": [{
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write one file",
                    "parameters": {"type": "object"},
                },
            }]
        }

    messages = [SystemMessage(content="act"), HumanMessage(content="build it")]
    first = build_request_snapshot(messages, Binding())
    second = build_request_snapshot(messages, Binding())

    assert first == second
    assert first["tool_names"] == ["write_file"]
    assert first["tool_schema_chars"] > 0
    assert [item["content"] for item in first["messages"]] == ["act", "build it"]
    assert len(first["sha256"]) == 64


def test_empty_autonomous_delivery_exposes_only_write_file(tmp_path, monkeypatch):
    # Import after the lazy-memory contract above: importing chat_graph must not
    # construct the embedding backend or perform network I/O.
    from src.graphs import chat_graph

    if isinstance(chat_graph.memory_manager, LazyMemoryManager):
        assert chat_graph.memory_manager.initialized is False

    config = {
        "configurable": {
            "approval_policy": "workspace_session",
            "workspace": str(tmp_path),
        }
    }
    state = {
        "current_task": "Build a React web app and create the requested files",
        "plan": [],
        "execution_trace": [],
        "iteration_used": 0,
    }
    names = [tool.name for tool in chat_graph._resolve_bound_tools(state, config)]
    assert names == ["write_file"]
    assert config["configurable"]["execution_phase"] == "forced_delivery"


def test_ai_node_builds_expected_first_sarvam_request_without_provider_call(tmp_path, monkeypatch):
    import platform
    from langchain_core.messages import AIMessage
    from src.graphs import chat_graph

    captured = {}

    class FakeBoundLLM:
        model = "sarvam-test"

        def bind_tools(self, tools, **kwargs):
            captured["tools"] = [tool.name for tool in tools]
            return self

        def bind(self, **kwargs):
            captured.setdefault("binds", []).append(kwargs)
            return self

        def invoke(self, messages):
            captured["messages"] = list(messages)
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": "write_file",
                    "args": {"path": "index.html", "content": "<!doctype html>"},
                    "id": "call-1",
                    "type": "tool_call",
                }],
            )

    monkeypatch.setattr(chat_graph, "get_llm", lambda **kwargs: FakeBoundLLM())
    monkeypatch.setattr(chat_graph, "memory_manager", None)
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    task = "Build and create a complete interactive web app"
    config = {
        "configurable": {
            "thread_id": "autonomous-ai-node-contract",
            "approval_policy": "workspace_session",
            "workspace": str(tmp_path),
            "provider": "custom",
            "model": "sarvam-test",
        }
    }
    state = {
        "messages": [HumanMessage(content=task)],
        "latest_instruction": task,
        "current_task": task,
        "workspace": str(tmp_path),
        "plan": [],
        "steps_completed": [],
        "failed_steps": [],
        "execution_trace": [],
        "iteration_used": 0,
        "grace_done": 0,
        "turn_token_usage": {},
        "token_usage": {},
        "execution_mode": "agent",
    }

    result = chat_graph.ai_node(state, config)

    assert captured["tools"] == ["write_file"]
    assert {"max_tokens": 4096} in captured["binds"]
    assert [message.type for message in captured["messages"]] == [
        "system", "system", "system", "human"
    ]
    assert "Windows cmd.exe" in captured["messages"][-2].content
    assert captured["messages"][-1].content == task
    assert result["iteration_used"] == 1


def test_autonomous_initial_prompt_has_one_user_tail_and_no_style_conflicts(tmp_path, monkeypatch):
    from src.graphs import chat_graph

    monkeypatch.setattr(chat_graph, "memory_manager", None)
    task = "Build and create a complete interactive web app"
    config = {
        "configurable": {
            "thread_id": "autonomous-prompt-contract",
            "approval_policy": "workspace_session",
            "workspace": str(tmp_path),
            "provider": "custom",
            "model": "sarvam-test",
        }
    }
    state = {
        "messages": [HumanMessage(content=task)],
        "latest_instruction": task,
        "current_task": task,
        "workspace": str(tmp_path),
        "plan": [],
        "steps_completed": [],
        "failed_steps": [],
        "execution_trace": [],
        "_autonomous_workspace": True,
    }
    messages = chat_graph.get_context_engine(config).build_ai_messages(
        state=state,
        system_message=chat_graph.autonomous_system_message,
    )
    chat_graph._insert_system_prefix(messages, "DIRECT DELIVERY")

    assert [message.type for message in messages] == ["system", "system", "human"]
    combined = "\n".join(str(message.content) for message in messages[:-1]).lower()
    assert "explain your reasoning before taking action" not in combined
    assert "start with a high-level overview" not in combined
    assert "ask clarifying questions" not in combined
    assert messages[-1].content == task




def test_incomplete_tool_call_is_rejected_then_observed_by_request_two(tmp_path, monkeypatch):
    """A token-limited request-1 call cannot mutate disk and its paired
    error is fed directly to provider request 2 (Hermes parity contract)."""
    from src.graphs import chat_graph

    requests = []

    class TwoRequestLLM:
        model = "fake"

        def bind_tools(self, tools, **kwargs):
            return self

        def bind(self, **kwargs):
            return self

        def invoke(self, messages):
            requests.append(list(messages))
            if len(requests) == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "write_file",
                        "args": {
                            "path": "partial.html",
                            "content": "<style>body{",
                        },
                        "id": "truncated-call",
                        "type": "tool_call",
                    }],
                    response_metadata={"finish_reason": "length"},
                )
            return AIMessage(
                content="continuing with a smaller complete write",
                response_metadata={"finish_reason": "stop"},
            )

    llm = TwoRequestLLM()
    monkeypatch.setattr(chat_graph, "get_llm", lambda **kwargs: llm)
    monkeypatch.setattr(chat_graph, "memory_manager", None)
    config = {
        "configurable": {
            "thread_id": "incomplete-request-two",
            "workspace": str(tmp_path),
            "provider": "custom",
            "model": "fake",
        }
    }
    base_state = {
        "messages": [HumanMessage(content="build")],
        "latest_instruction": "build",
        "current_task": "build a complete web app",
        "workspace": str(tmp_path),
        "plan": [],
        "steps_completed": [],
        "failed_steps": [],
        "execution_trace": [],
        "iteration_used": 0,
        "grace_done": 0,
        "turn_token_usage": {},
        "token_usage": {},
        "execution_mode": "agent",
    }

    request_one = chat_graph.ai_node(base_state, config)
    assistant = request_one["messages"][0]
    assert assistant.additional_kwargs["pulse_incomplete_response"] is True
    assert assistant.additional_kwargs["pulse_incomplete_reason"] == "length"

    tool_state = dict(base_state)
    tool_state["messages"] = [*base_state["messages"], assistant]
    node = chat_graph.SafeToolNode.__new__(chat_graph.SafeToolNode)
    rejected = node(tool_state, config)["messages"]
    assert len(rejected) == 1
    assert isinstance(rejected[0], ToolMessage)
    assert rejected[0].tool_call_id == "truncated-call"
    assert rejected[0].status == "error"
    assert "NOT executed" in rejected[0].content
    assert not (tmp_path / "partial.html").exists()

    second_state = dict(tool_state)
    second_state.update({
        "messages": [*tool_state["messages"], *rejected],
        "execution_trace": [{"tool": "write_file", "status": "error"}],
        "iteration_used": 1,
    })
    request_two = chat_graph.ai_node(second_state, config)

    assert len(requests) == 2
    assert requests[1][-1].type == "tool"
    assert requests[1][-1].tool_call_id == "truncated-call"
    assert "NOT executed" in requests[1][-1].content
    assert request_two["messages"][0].content.startswith("continuing")
    assert request_two["iteration_used"] == 2
