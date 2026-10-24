"""Agent Core user-interest contract.

These tests pin the multi-repo design rules: preserve the real request, keep
initial objective + newest steering, do not turn inquiries into implementation,
and spend no extra provider call on the default path.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from src.context.user_interest import (
    MAX_CONSTRAINTS,
    MAX_EVIDENCE_ITEMS,
    MAX_INSTRUCTION_CHARS,
    MAX_OBJECTIVE_CHARS,
    MAX_OUTCOME_ITEMS,
    SCHEMA_VERSION,
    UserInterest,
    decide_interest_mode,
    infer_explicit_followup_relationship,
    render_user_interest,
    resolve_user_interest,
)


@pytest.mark.parametrize(
    ("text", "mode", "change_policy"),
    [
        ("Implement the user-interest contract.", "act", "changes_requested"),
        ("Only change Agent Core and run the tests.", "act", "changes_requested"),
        ("Can you implement this and verify it?", "act", "changes_requested"),
        ("Run the focused tests.", "act", "unspecified"),
        ("Run the tests without changing code.", "act", "no_changes"),
        ("Actually, run the tests without changing code.", "act", "no_changes"),
        ("Review the parser and fix the boundary bug.", "act", "changes_requested"),
        ("Was the desktop test successful?", "answer", "unspecified"),
        ("Please explain how the router works.", "answer", "unspecified"),
        ("Tell me the issues without changing anything.", "answer", "no_changes"),
        ("Do not edit code; only analyze the failure.", "answer", "no_changes"),
        ("okkk bro", "social", "unspecified"),
        ("go ahead", "social", "unspecified"),
        ("The cache seems slow.", "undetermined", "unspecified"),
    ],
)
def test_conservative_interest_decision(text, mode, change_policy):
    assert decide_interest_mode(text)[:2] == (mode, change_policy)


def test_action_words_use_boundaries_not_substrings():
    # "add" must not match inside "address"; uncertain prose is left for the
    # main model rather than silently authorizing mutation.
    assert decide_interest_mode("The address handling seems surprising.")[0] == "undetermined"


@pytest.mark.parametrize(
    ("text", "relationship"),
    [
        ("New task: explain the cache.", "replaces"),
        ("Actually, use SQLite instead of Postgres.", "corrects"),
        ("Only touch Agent Core.", "corrects"),
        ("The cache seems slow.", "undetermined"),
    ],
)
def test_only_explicit_followup_relationships_are_inferred(text, relationship):
    assert infer_explicit_followup_relationship(text) == relationship


def test_new_interest_captures_objective_constraints_outcomes_and_evidence():
    text = (
        "Implement user-interest routing. Only change Agent Core. "
        "Do not deploy. Verify it with focused tests and provide evidence."
    )
    interest = resolve_user_interest(
        objective=text,
        latest_instruction=text,
        relationship="new",
    )

    assert interest.schema_version == SCHEMA_VERSION
    assert interest.objective == text
    assert interest.latest_substantive_instruction == text
    assert interest.mode == "act"
    assert interest.change_policy == "changes_requested"
    assert any("Implement user-interest routing" in item for item in interest.requested_outcomes)
    assert any("Only change Agent Core" in item for item in interest.constraints)
    assert any("Do not deploy" in item for item in interest.constraints)
    assert any("focused tests" in item for item in interest.requested_evidence)
    assert len(interest.fingerprint) == 16


def test_followup_is_scope_preserving_and_ack_does_not_replace_it():
    first = resolve_user_interest(
        objective="Build the authentication flow.",
        latest_instruction="Build the authentication flow.",
        relationship="new",
    )
    correction = resolve_user_interest(
        previous=first.to_state(),
        objective=first.objective,
        latest_instruction="Only update the API; keep the UI unchanged and run tests.",
        relationship="undetermined",
    )
    ack = resolve_user_interest(
        previous=correction.to_state(),
        objective=correction.objective,
        latest_instruction="okkk bro",
        relationship="continue",
    )

    assert correction.objective == "Build the authentication flow."
    assert correction.latest_substantive_instruction.startswith("Only update")
    assert correction.relationship == "corrects"
    assert correction.mode == "act"
    assert any("keep the UI unchanged" in item for item in correction.constraints)
    assert ack.latest_instruction == "okkk bro"
    assert ack.latest_substantive_instruction == correction.latest_substantive_instruction
    assert ack.mode == correction.mode
    assert ack.change_policy == correction.change_policy


def test_correction_prefix_does_not_hide_action_or_original_wording():
    active = resolve_user_interest(
        objective="Implement Agent Core.",
        latest_instruction="Implement Agent Core.",
        relationship="new",
    )
    correction = resolve_user_interest(
        previous=active.to_state(),
        objective=active.objective,
        latest_instruction="Actually, run the tests without changing code.",
        relationship="undetermined",
    )

    assert correction.relationship == "corrects"
    assert correction.mode == "act"
    assert correction.change_policy == "no_changes"
    assert correction.latest_instruction == (
        "Actually, run the tests without changing code."
    )


def test_unrelated_turn_does_not_replace_active_interest():
    active = resolve_user_interest(
        objective="Fix the parser without changing its public API.",
        latest_instruction="Fix the parser without changing its public API.",
        relationship="new",
    )
    unrelated = resolve_user_interest(
        previous=active.to_state(),
        objective=active.objective,
        latest_instruction="What time is it?",
        relationship="unrelated",
    )

    assert unrelated.objective == active.objective
    assert unrelated.latest_substantive_instruction == active.latest_substantive_instruction
    assert unrelated.constraints == active.constraints
    assert unrelated.latest_instruction == "What time is it?"
    assert unrelated.relationship == "unrelated"
    assert unrelated.mode == "answer"
    assert unrelated.focus_text() == "What time is it?"

    resumed = resolve_user_interest(
        previous=unrelated.to_state(),
        objective=active.objective,
        latest_instruction="continue",
        relationship="continue",
    )
    assert resumed.relationship == "continue"
    assert resumed.mode == active.mode
    assert resumed.change_policy == active.change_policy
    assert resumed.latest_substantive_instruction == active.latest_substantive_instruction
    assert resumed.focus_text() == active.focus_text()


def test_explicit_new_task_resets_old_scope():
    old = resolve_user_interest(
        objective="Implement login. Never touch billing.",
        latest_instruction="Implement login. Never touch billing.",
        relationship="new",
    )
    new = resolve_user_interest(
        previous=old.to_state(),
        objective="Explain the cache architecture.",
        latest_instruction="Explain the cache architecture.",
        relationship="new",
    )

    assert new.objective == "Explain the cache architecture."
    assert new.mode == "answer"
    assert not any("billing" in item for item in new.constraints)
    assert new.steering == ()


def test_explicit_replacement_resets_active_scope_without_a_classifier_call():
    old = resolve_user_interest(
        objective="Implement login. Never touch billing.",
        latest_instruction="Implement login. Never touch billing.",
        relationship="new",
    )
    replacement = resolve_user_interest(
        previous=old.to_state(),
        objective=old.objective,
        latest_instruction="New task: explain the cache architecture.",
        relationship="undetermined",
    )

    assert replacement.relationship == "replaces"
    assert replacement.objective == "explain the cache architecture."
    assert replacement.mode == "answer"
    assert not any("billing" in item for item in replacement.constraints)


def test_contract_is_bounded_json_safe_and_round_trips():
    huge = "Implement x. Only keep this bounded. Verify with tests. " + "z" * 20_000
    interest = resolve_user_interest(
        objective=huge,
        latest_instruction=huge,
        relationship="new",
    )
    state = interest.to_state()
    restored = UserInterest.from_state(state)

    assert restored is not None
    assert len(interest.objective) <= MAX_OBJECTIVE_CHARS
    assert len(interest.latest_instruction) <= MAX_INSTRUCTION_CHARS
    assert len(interest.constraints) <= MAX_CONSTRAINTS
    assert len(interest.requested_outcomes) <= MAX_OUTCOME_ITEMS
    assert len(interest.requested_evidence) <= MAX_EVIDENCE_ITEMS
    assert isinstance(state["constraints"], list)
    assert isinstance(state["requested_outcomes"], list)
    assert restored.objective == interest.objective
    assert restored.fingerprint == interest.fingerprint


def test_rendered_contract_is_explicit_about_source_and_precedence():
    interest = resolve_user_interest(
        objective="Implement the feature.",
        latest_instruction="Do not deploy; run tests.",
        relationship="continue",
    )
    rendered = render_user_interest(interest)

    assert "USER INTEREST CONTRACT (schema v1)" in rendered
    assert "Overall goal: Implement the feature." in rendered
    assert "Latest instruction: Do not deploy; run tests." in rendered
    assert "Requested deliverable/outcome excerpts" in rendered
    assert "newest conflict wins" in rendered
    assert "do not convert an inquiry into edits" in rendered
    assert "materially change execution" in rendered
    assert interest.fingerprint in rendered


def test_context_task_layer_uses_versioned_contract():
    from src.context.context_engine import ContextEngine

    interest = resolve_user_interest(
        objective="Implement the router.",
        latest_instruction="Only touch Agent Core and verify it.",
        relationship="continue",
    )
    message = ContextEngine._task_layer(  # type: ignore[misc]
        object(),
        {
            "current_task": interest.objective,
            "latest_instruction": interest.latest_instruction,
            "user_interest": interest.to_state(),
        },
    )

    assert "USER INTEREST CONTRACT (schema v1)" in message.content
    assert "Only touch Agent Core" in message.content
    assert "Requested verification/evidence excerpts" in message.content


def test_interest_changes_invalidate_context_hash():
    from src.context.context_engine import ContextEngine

    engine = object.__new__(ContextEngine)
    base = {
        "current_task": "Build login",
        "latest_instruction": "Build login",
        "workspace": ".",
    }
    first = resolve_user_interest(
        objective="Build login",
        latest_instruction="Build login",
        relationship="new",
    )
    second = resolve_user_interest(
        previous=first.to_state(),
        objective="Build login",
        latest_instruction="Keep the public API unchanged.",
        relationship="continue",
    )

    assert engine._hash_state({**base, "user_interest": first.to_state()}) != engine._hash_state(
        {**base, "user_interest": second.to_state()}
    )


def _config() -> dict:
    return {"configurable": {"thread_id": "interest-test", "workspace": "."}}


def test_task_manager_first_turn_persists_interest_from_message(monkeypatch):
    import src.graphs.chat_graph as cg

    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)
    monkeypatch.setattr(
        cg,
        "_task_manager_llm",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("first-turn interest must not call another model")
        ),
    )
    out = cg.task_manager_node(
        {
            "messages": [HumanMessage("Implement Agent Core interest routing and run tests.")],
            "current_task": "",
        },
        _config(),
    )

    assert out["task_action"] == "new"
    assert out["latest_instruction"].startswith("Implement Agent Core")
    assert out["user_interest"]["mode"] == "act"
    assert out["user_interest"]["change_policy"] == "changes_requested"


def test_default_followup_updates_interest_with_zero_classifier_calls(monkeypatch):
    import src.graphs.chat_graph as cg

    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)
    monkeypatch.setattr(
        cg,
        "_task_manager_llm",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("default interest path constructed a classifier")
        ),
    )
    initial = resolve_user_interest(
        objective="Implement Agent Core.",
        latest_instruction="Implement Agent Core.",
        relationship="new",
    )
    out = cg.task_manager_node(
        {
            "messages": [],
            "current_task": initial.objective,
            "latest_instruction": "Only touch Agent Core and verify with tests.",
            "user_interest": initial.to_state(),
            "token_usage": {},
        },
        _config(),
    )

    assert out["task_action"] == "continue"
    assert out["user_interest"]["relationship"] == "corrects"
    assert out["user_interest"]["mode"] == "act"
    assert out["user_interest"]["latest_substantive_instruction"].startswith(
        "Only touch Agent Core"
    )
    assert any("Only touch" in item for item in out["user_interest"]["constraints"])


def test_quick_ack_preserves_latest_substantive_interest(monkeypatch):
    import src.graphs.chat_graph as cg

    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)
    active = resolve_user_interest(
        objective="Implement Agent Core.",
        latest_instruction="Only touch Agent Core and verify with tests.",
        relationship="continue",
    )
    state = {
        "current_task": active.objective,
        "latest_instruction": "okkk bro",
        "user_interest": active.to_state(),
        "token_usage": {},
    }
    out = cg.task_manager_node(state, _config())
    merged = {**state, **out}

    assert out["task_action"] == "continue"
    assert "user_interest" not in out
    assert merged["latest_instruction"] == "okkk bro"
    assert merged["user_interest"] == active.to_state()
    assert merged["user_interest"]["latest_substantive_instruction"] == (
        active.latest_substantive_instruction
    )


def test_plan_approval_preserves_substantive_interest(monkeypatch):
    import src.graphs.chat_graph as cg

    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)
    active = resolve_user_interest(
        objective="Implement Agent Core.",
        latest_instruction="Only touch Agent Core and run tests.",
        relationship="corrects",
    )
    out = cg.task_manager_node(
        {
            "current_task": active.objective,
            "latest_instruction": "yes",
            "user_interest": active.to_state(),
            "plan": [{"id": 1, "description": "Implement", "status": "pending"}],
            "plan_goal": active.objective,
            "plan_created": True,
            "token_usage": {},
        },
        _config(),
    )

    assert out["task_action"] == "execute_approved_plan"
    assert out["user_interest"]["latest_instruction"] == "yes"
    assert out["user_interest"]["latest_substantive_instruction"].startswith(
        "Only touch Agent Core"
    )
    assert out["user_interest"]["mode"] == "act"


def test_quick_ack_after_unrelated_turn_restores_active_mode(monkeypatch):
    import src.graphs.chat_graph as cg

    monkeypatch.delenv("CRUSORAI_TASK_CLASSIFIER", raising=False)
    active = resolve_user_interest(
        objective="Implement Agent Core.",
        latest_instruction="Only touch Agent Core and run tests.",
        relationship="new",
    )
    unrelated = resolve_user_interest(
        previous=active.to_state(),
        objective=active.objective,
        latest_instruction="What time is it?",
        relationship="unrelated",
    )
    out = cg.task_manager_node(
        {
            "current_task": active.objective,
            "latest_instruction": "okkk",
            "user_interest": unrelated.to_state(),
            "token_usage": {},
        },
        _config(),
    )

    assert out["task_action"] == "continue"
    assert out["user_interest"]["relationship"] == "continue"
    assert out["user_interest"]["mode"] == "act"
    assert out["user_interest"]["latest_substantive_instruction"].startswith(
        "Only touch Agent Core"
    )


def test_answer_interest_cannot_bind_mutation_or_delegation_tools(tmp_path):
    import src.graphs.chat_graph as cg

    interest = resolve_user_interest(
        objective="How should src/router.py be implemented?",
        latest_instruction="Explain the approach without changing any files.",
        relationship="new",
    )
    config = {
        "configurable": {
            "thread_id": "read-only-interest",
            "workspace": str(tmp_path),
        }
    }
    bound = {
        tool.name
        for tool in cg._resolve_bound_tools(
            {
                "current_task": interest.objective,
                "latest_instruction": interest.latest_instruction,
                "user_interest": interest.to_state(),
            },
            config,
        )
    }

    assert {"read_file", "search_code", "web_search"} <= bound
    assert not {
        "write_file", "edit_file", "run_terminal", "execute_code",
        "delegate_to_subagent", "hub_install",
    } & bound
    assert config["configurable"]["execution_phase"] == "read_only_interest"
    assert config["configurable"]["phase_max_file_mutations"] == 0


def test_answer_interest_does_not_trigger_delivery_or_completion_work(tmp_path):
    from langchain_core.messages import AIMessage
    import src.graphs.chat_graph as cg
    from src.graphs.gates import _deliverables_missing_on_disk, should_continue

    interest = resolve_user_interest(
        objective="How should we implement src/router.py?",
        latest_instruction="Explain it without making changes.",
        relationship="new",
    )
    state = {
        "current_task": interest.objective,
        "latest_instruction": interest.latest_instruction,
        "user_interest": interest.to_state(),
        "workspace": str(tmp_path),
        "messages": [AIMessage(content="Use a small typed routing contract.")],
        "finish_nudges": 0,
    }

    assert cg._requires_file_delivery(state) is False
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []
    assert should_continue(state) == "finalize"


def test_no_change_action_can_verify_but_cannot_mutate(tmp_path):
    from langchain_core.messages import AIMessage
    import src.graphs.chat_graph as cg
    from src.graphs.gates import _deliverables_missing_on_disk, should_continue

    interest = resolve_user_interest(
        objective="Run the tests without changing code.",
        latest_instruction="Run the tests without changing code.",
        relationship="new",
    )
    config = {
        "configurable": {
            "thread_id": "no-change-action",
            "workspace": str(tmp_path),
        }
    }
    state = {
        "current_task": interest.objective,
        "latest_instruction": interest.latest_instruction,
        "user_interest": interest.to_state(),
        "workspace": str(tmp_path),
        "messages": [AIMessage(content="I would run them next.")],
        "finish_nudges": 0,
    }
    bound = {tool.name for tool in cg._resolve_bound_tools(state, config)}

    assert interest.mode == "act"
    assert interest.change_policy == "no_changes"
    assert {"run_terminal", "read_file"} <= bound
    assert not {"write_file", "edit_file", "copy_file", "execute_code"} & bound
    assert config["configurable"]["execution_phase"] == "no_change_action"
    assert cg._requires_file_delivery(state) is False
    assert _deliverables_missing_on_disk(state, str(tmp_path)) == []
    assert should_continue(state) == "finish_gate"


def test_answer_continuation_nudge_does_not_require_tool_activity(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
    import src.graphs.chat_graph as cg

    monkeypatch.setattr(cg, "memory_manager", None)
    interest = resolve_user_interest(
        objective="Explain the router without changing code.",
        latest_instruction="Explain the router without changing code.",
        relationship="new",
    )
    out = cg.finalize_node(
        {
            "current_task": interest.objective,
            "latest_instruction": interest.latest_instruction,
            "user_interest": interest.to_state(),
            "messages": [
                HumanMessage(content=interest.objective),
                SystemMessage(content="Continue the answer."),
                AIMessage(content="The router uses a bounded contract."),
            ],
            "nudged_at_msg_count": 1,
            "steps_completed": [],
            "failed_steps": [],
            "plan": [],
        },
        _config(),
    )

    assert out["task_completed"] is True
    assert out["task_status"] == "completed"


def test_plan_prompt_carries_versioned_interest_contract(tmp_path):
    import src.graphs.chat_graph as cg

    interest = resolve_user_interest(
        objective="Implement the router.",
        latest_instruction="Only touch Agent Core; do not deploy; run tests.",
        relationship="corrects",
    )
    out = cg.planner_node(
        {
            "current_task": interest.objective,
            "latest_instruction": interest.latest_instruction,
            "user_interest": interest.to_state(),
            "execution_mode": "plan",
            "token_usage": {},
        },
        {
            "configurable": {
                "thread_id": "interest-plan",
                "workspace": str(tmp_path),
            }
        },
    )

    prompt = out["messages"][0].content
    assert "USER INTEREST CONTRACT (schema v1)" in prompt
    assert "Only touch Agent Core" in prompt
    assert "do not deploy" in prompt
    assert out["plan_goal"] == "Implement the router."
