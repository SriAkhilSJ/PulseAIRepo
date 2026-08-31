"""P9 behavior contracts for src/context/layer_policy.py.

The engine delegates its layer policy (scoring, dedup, placement,
compression, budget allocation) to this module. These tests pin the
module's behavior directly (model=None => heuristic token counting,
deterministic, no provider, no embedder) and pin the engine's
delegation seams so a future refactor can't silently break either side.
"""

import string

from langchain_core.messages import SystemMessage

from src.context import layer_policy
from src.context.context_engine import ContextEngine, TaskType
from src.context.token_budget import count_tokens


def _engine() -> ContextEngine:
    return ContextEngine(max_tokens=4000, llm=None, memory_manager=None)


def _tagged(name: str, body: str = "this is a test body") -> SystemMessage:
    return SystemMessage(
        content=f"=== {body.upper()}",
        response_metadata={"layer": name},
    )


# ---------------------------------------------------------------------------
# Relevance base: shared, never mutated by any engine
# ---------------------------------------------------------------------------

def test_relevance_base_is_isolated_from_engine_instances():
    base = layer_policy.LAYER_RELEVANCE_BASE["repo_map"][TaskType.DEBUG]
    eng = _engine()
    eng.LAYER_RELEVANCE["repo_map"][TaskType.DEBUG] = 0.999
    assert layer_policy.LAYER_RELEVANCE_BASE["repo_map"][TaskType.DEBUG] == base, (
        "engine mutated the module-level relevance base"
    )
    fresh = _engine()
    assert fresh.LAYER_RELEVANCE["repo_map"][TaskType.DEBUG] == base


def test_engine_scoring_reads_live_relevance_dict():
    """A feedback nudge into eng.LAYER_RELEVANCE must be visible to the
    next score — the delegate passes the instance dict, not a copy."""
    eng = _engine()
    layers = [_tagged("tone", "gentle"), _tagged("plan", "steps")]
    before = eng._score_and_sort_layers(layers, "t", TaskType.CHAT)
    # CHAT priors: tone=0.30, plan=0.0 -> tone ranks first. Flip plan above tone.
    assert before[0][1].response_metadata["layer"] == "tone"
    eng.LAYER_RELEVANCE["plan"][TaskType.CHAT] = 0.95
    after = eng._score_and_sort_layers(layers, "t", TaskType.CHAT)
    assert after[0][1].response_metadata["layer"] == "plan", (
        "engine scored against a stale relevance snapshot"
    )


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def test_allocate_budget_always_sums_to_max_tokens():
    for task in TaskType:
        ctx, hist = layer_policy.allocate_budget(10_000, task)
        assert ctx + hist == 10_000, task
        assert ctx > 0 and hist > 0, task


def test_allocate_budget_pinned_ratios():
    assert layer_policy.allocate_budget(10_000, TaskType.DEBUG) == (3500, 6500)
    assert layer_policy.allocate_budget(10_000, TaskType.CHAT) == (2000, 8000)
    assert layer_policy.allocate_budget(10_000, TaskType.EXPLORE) == (5000, 5000)


# ---------------------------------------------------------------------------
# Attribution + placement
# ---------------------------------------------------------------------------

def test_infer_layer_name_tag_beats_header():
    m = SystemMessage(
        content="=== PLAN: do things",
        response_metadata={"layer": "tone"},
    )
    assert layer_policy.infer_layer_name(m) == "tone"


def test_infer_layer_name_header_fallback_and_unknown():
    assert layer_policy.infer_layer_name(
        SystemMessage(content="=== GIT CONTEXT\nnothing")
    ) == "git_context"
    assert layer_policy.infer_layer_name(
        SystemMessage(content="=== LONG-TERM MEMORY\nmem")
    ) == "long_term_memory"
    assert layer_policy.infer_layer_name(
        SystemMessage(content="something else entirely")
    ) == "unknown"


def test_emission_order_known_then_unknown_then_volatile():
    known = layer_policy.emission_sort_key(_tagged("task"))
    unknown = layer_policy.emission_sort_key(_tagged("mystery"))
    volatile = layer_policy.emission_sort_key(_tagged("git_context"))
    assert known[0] == 0 and known[1] == layer_policy.BUILDER_ORDER.index("task")
    assert unknown == (1, "mystery")
    assert volatile == (2, "git_context")
    assert known < unknown < volatile


def test_position_volatile_tail_layouts():
    stable = _tagged("task", "do it")
    git = _tagged("git_context", "dirty")
    history = ["h1"]

    # flag off: untouched concatenation
    out = layer_policy.position_volatile_tail([stable, git], history, False)
    assert out == [stable, git, "h1"]

    # flag on, no volatile present: stable + history
    out = layer_policy.position_volatile_tail([stable], history, True)
    assert out == [stable, "h1"]

    # flag on, volatile present: [stable, history, preamble, volatile]
    out = layer_policy.position_volatile_tail([stable, git], history, True)
    assert out[0] is stable
    assert out[1] == "h1"
    assert out[2].content == layer_policy.VOLATILE_TAIL_PREAMBLE
    assert out[3] is git


# ---------------------------------------------------------------------------
# Scoring (deterministic mode — embeddings off by default)
# ---------------------------------------------------------------------------

def test_score_deterministic_formula_and_order():
    layers = [_tagged("tone"), _tagged("plan")]
    relevance = {
        "tone": {TaskType.DEBUG: 0.5},
        "plan": {TaskType.DEBUG: 0.9},
    }
    scored = layer_policy.score_and_sort_layers(
        layers, "task", TaskType.DEBUG,
        model=None, allow_embedding_compute=False, relevance=relevance,
    )
    scores = {
        m.response_metadata["layer"]: s for s, m, _ in scored
    }
    assert scores["tone"] == 0.5 * 0.9 + 0.0 * 0.1   # recency 0/1
    assert scores["plan"] == 0.9 * 0.9 + 1.0 * 0.1   # recency 1/1
    assert scored[0][1].response_metadata["layer"] == "plan"
    # every tuple carries a real token count
    assert all(isinstance(t, int) and t > 0 for _, _, t in scored)


def test_score_unknown_layer_falls_back_to_half():
    layers = [_tagged("mystery")]
    scored = layer_policy.score_and_sort_layers(
        layers, "task", TaskType.CHAT,
        model=None, allow_embedding_compute=False,
        relevance={},  # no entry at all -> 0.5 default
    )
    assert scored[0][0] == 0.5 * 0.9  # single layer: recency 0/1


# ---------------------------------------------------------------------------
# Assembly + compression
# ---------------------------------------------------------------------------

def test_assemble_under_budget_emits_builder_order_not_score_order():
    # progress has the HIGHEST score; BUILDER_ORDER says
    # task < plan < progress, so that is the emission order.
    scored = [
        (0.9, _tagged("progress"), 10),
        (0.8, _tagged("plan"), 10),
        (0.7, _tagged("task"), 10),
    ]
    out = layer_policy.assemble_hierarchical(scored, 1000, model=None)
    assert [m.response_metadata["layer"] for m in out] == [
        "task", "plan", "progress",
    ]


def test_assemble_over_budget_skips_layers_that_cannot_fit():
    big = SystemMessage(
        content="y" * 10_000, response_metadata={"layer": "tone"}
    )
    small = _tagged("task")
    big_tokens = count_tokens([big], None)
    scored = [
        (0.9, big, big_tokens),
        (0.8, small, count_tokens([small], None)),
    ]
    out = layer_policy.assemble_hierarchical(scored, big_tokens, model=None)
    # budget == exactly the big layer's size: it fits, the small one
    # has nothing left and is dropped.
    assert [m.response_metadata["layer"] for m in out] == ["tone"]


def test_compress_repo_map_strips_symbols_and_keeps_tag():
    m = SystemMessage(
        content=(
            "=== CODEBASE STRUCTURE\n"
            "src/a.py -> 3 symbols\n"
            "src/b.py -> 5 symbols\n"
            "plain line\n"
        ),
        response_metadata={"layer": "repo_map"},
    )
    out = layer_policy.compress_layer(m, max_tokens=10_000, model=None)
    assert out is not None
    assert "->" not in out.content
    assert "src/a.py" in out.content and "plain line" in out.content
    assert out.response_metadata.get("layer") == "repo_map", (
        "compression lost the identity tag"
    )


def test_compress_never_returns_over_budget_candidate():
    contents = [
        "def " + "x" * 50 + "\n" * 200,                      # code-dense
        "word " * 800,                                        # prose
        "\u00e9\u00fc\u00f1 \u4e2d\u6587 \U0001f600 " * 200,  # mixed density
    ]
    for content in contents:
        m = SystemMessage(
            content=content, response_metadata={"layer": "quality"}
        )
        for budget in (10, 25, 40, 60, 100, 150):
            out = layer_policy.compress_layer(m, budget, model=None)
            if out is not None:
                assert count_tokens([out], None) <= budget, (
                    f"returned {count_tokens([out], None)} tokens "
                    f"for budget {budget} (content kind: {content[:12]!r})"
                )


def test_compress_unfittable_returns_none():
    m = SystemMessage(content="z" * 100, response_metadata={"layer": "tone"})
    assert layer_policy.compress_layer(m, max_tokens=3, model=None) is None


# ---------------------------------------------------------------------------
# Engine delegation seams
# ---------------------------------------------------------------------------

def test_engine_delegation_round_trip():
    eng = _engine()
    m = _tagged("tone")

    assert eng._infer_layer_name(m) == layer_policy.infer_layer_name(m)

    assert eng._allocate_budget(TaskType.DEBUG) == layer_policy.allocate_budget(
        eng.max_tokens, TaskType.DEBUG
    )

    scored = [(0.5, _tagged("task"), 5), (0.9, _tagged("plan"), 5)]
    assert eng._assemble_hierarchical(list(scored), 100) == \
        layer_policy.assemble_hierarchical(list(scored), 100, model=eng.model)

    a = eng._compress_layer(m, 100)
    b = layer_policy.compress_layer(m, 100, model=eng.model)
    if a is None:
        assert b is None
    else:
        assert b is not None
        assert a.content == b.content
        assert a.response_metadata == b.response_metadata

    assert eng._emission_sort_key(m) == layer_policy.emission_sort_key(m)
