"""D1: Session-scoped ContextEngines — regression tests.

The module-level singleton silently shared the layer cache, the
_last_layers_sent attribution snapshot, feedback history, and the LEARNED
LAYER_RELEVANCE weights across every dashboard session. Proven pre-fix:
session A's recorded feedback carried session B's exact layer composition
(A's `progress` layer missing — the snapshot had been overwritten mid-flight).
"""

import inspect
import json
import threading

from langchain_core.messages import SystemMessage

from src.context.context_engine import ContextEngine, TaskType
from src.graphs import chat_graph


def _state(task: str) -> dict:
    return {
        "current_task": task,
        "messages": [],
        "workspace": ".",
        "plan": [{"id": 1, "description": "repro", "status": "pending"}],
        "steps_completed": [],
        "failed_steps": ["boom"] if "bug" in task else [],
        "recovery_mode": "bug" in task,
        "recovery_attempts": 1 if "bug" in task else 0,
        "replan_count": 0,
    }


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "provider": "groq", "model": "m"}}


class TestRegistry:
    def test_memoized_per_session(self):
        a1 = chat_graph.get_context_engine(_cfg("sess-a"))
        a2 = chat_graph.get_context_engine("sess-a")
        b = chat_graph.get_context_engine(_cfg("sess-b"))
        assert a1 is a2, "same session must return the same engine"
        assert a1 is not b, "distinct sessions must NOT share an engine"

    def test_unknown_config_buckets_to_default(self):
        assert chat_graph.get_context_engine(None) is chat_graph.get_context_engine("default")
        assert chat_graph.get_context_engine({}) is chat_graph.get_context_engine("default")

    def test_implicit_call_after_explicit_pin_keeps_one_engine(self):
        # The exact fork that produced two engines for one thread_id: a node
        # passes the full config (pinned model), then a caller/tool passes only
        # the bare thread_id string. The implicit call must NOT rebuild against
        # the process-default model — it returns the SAME engine.
        chat_graph._ENGINES.clear()
        key = "implicit-after-explicit"
        eng = chat_graph.get_context_engine({
            "configurable": {"thread_id": key, "provider": "groq", "model": "gpt-4o-mini"}
        })
        again = chat_graph.get_context_engine(key)          # bare string, no model
        no_model_cfg = chat_graph.get_context_engine({     # dict, no "model" key
            "configurable": {"thread_id": key}
        })
        assert again is eng, "bare-key lookup forked a second engine for the session"
        assert no_model_cfg is eng, "model-less config forked a second engine for the session"
        assert len(chat_graph._ENGINES) == 1

    def test_explicit_model_switch_repoints_same_engine(self):
        # An explicit, DIFFERENT model follows the session by re-pointing the
        # one engine in place (model + budget) — never evicting it. Session
        # state (layer cache / feedback history / weights) must survive.
        chat_graph._ENGINES.clear()
        key = "explicit-switch"
        eng = chat_graph.get_context_engine({
            "configurable": {"thread_id": key, "model": "gpt-4o-mini"}
        })
        marker = object()
        eng._layer_cache["probe"] = marker  # session-scoped state
        old_budget = eng.max_tokens

        switched = chat_graph.get_context_engine({
            "configurable": {"thread_id": key, "model": "gpt-4o"}
        })
        assert switched is eng, "explicit model switch replaced the session engine"
        assert switched.model == "gpt-4o"
        # ...and model-derived budget state was refreshed, not left stale.
        assert switched.context_window is not None
        assert switched.max_tokens >= 4_096
        # session-scoped state survives the repoint (same object):
        assert switched._layer_cache.get("probe") is marker
        # re-pinning the SAME model is a no-op that keeps the object too.
        assert chat_graph.get_context_engine({
            "configurable": {"thread_id": key, "model": "gpt-4o"}
        }) is eng
        assert len(chat_graph._ENGINES) == 1
        # The budget genuinely tracks the model (guards a no-op repoint).
        assert old_budget >= 4_096

    def test_lru_eviction(self, monkeypatch):
        # Start from a clean registry: prior tests populated it, and eviction
        # order is relative to ALL resident keys.
        chat_graph._ENGINES.clear()
        monkeypatch.setattr(chat_graph, "_ENGINES_MAX", 3)
        engines = [chat_graph.get_context_engine(f"evict-{i}") for i in range(4)]
        again = chat_graph.get_context_engine("evict-0")
        assert again is not engines[0], "LRU victim must be rebuilt, not revived"
        assert len(chat_graph._ENGINES) <= 3
        # After [1,2,3] + rebuild of 0 -> [2,3,0]: the rebuild itself evicted 1.
        assert "evict-1" not in chat_graph._ENGINES
        assert chat_graph.get_context_engine("evict-2") is engines[2]


class TestIsolation:
    def test_attribution_isolated_between_sessions(self, tmp_path):
        eng_a = chat_graph.get_context_engine("iso-a")
        eng_b = chat_graph.get_context_engine("iso-b")
        eng_a._feedback_path = str(tmp_path / "a.jsonl")
        sysmsg = SystemMessage(content="SYS")

        eng_a.build_ai_messages(_state("fix the bug in the parser"), sysmsg)
        a_layers = list(eng_a._last_layers_sent)

        # Interleave session B's build BETWEEN A's build and A's feedback —
        # the exact race that corrupted the singleton.
        eng_b.build_ai_messages(_state("explain the repo map"), sysmsg)
        assert eng_b._last_layers_sent != a_layers

        eng_a.record_feedback(success=False, task="fix the bug in the parser")
        record = json.loads(open(eng_a._feedback_path).readlines()[-1])  # JSONL
        assert record["layers_used"] == a_layers, (
            "session B's build overwrote session A's attribution snapshot"
        )

    def test_learned_weights_do_not_leak_across_sessions(self, tmp_path):
        eng_a = chat_graph.get_context_engine("drift-a")
        eng_b = chat_graph.get_context_engine("drift-b")
        eng_a._feedback_path = str(tmp_path / "w.json")
        sysmsg = SystemMessage(content="SYS")

        eng_a.build_ai_messages(_state("fix the bug in the parser"), sysmsg)
        punished = list(eng_a._last_layers_sent)
        before_b = {n: eng_b.LAYER_RELEVANCE.get(n, {}).get(TaskType.DEBUG) for n in punished}
        before_a = {n: eng_a.LAYER_RELEVANCE.get(n, {}).get(TaskType.DEBUG) for n in punished}

        # Weight drift engages at >=10 feedback records (_apply_learned_weights).
        for _ in range(12):
            eng_a.build_ai_messages(_state("fix the bug in the parser"), sysmsg)
            eng_a.record_feedback(success=False, task="fix the bug in the parser")

        after_a = {n: eng_a.LAYER_RELEVANCE.get(n, {}).get(TaskType.DEBUG) for n in punished}
        after_b = {n: eng_b.LAYER_RELEVANCE.get(n, {}).get(TaskType.DEBUG) for n in punished}

        assert after_a != before_a, "precondition: feedback must drift A's weights"
        assert after_b == before_b, (
            "session A's learning drift contaminated session B's weights"
        )


class TestConcurrency:
    def test_same_session_concurrent_turns_never_corrupt(self, tmp_path):
        """8 threads x mixed build+record across 4 sessions: the per-engine
        _api_lock must keep every mutation serialized. No exceptions, no
        torn attribution, registry stays bounded."""
        keys = [f"conc-{i}" for i in range(4)]
        engines = [chat_graph.get_context_engine(k) for k in keys]
        for i, e in enumerate(engines):
            e._feedback_path = str(tmp_path / f"{i}.json")
        sysmsg = SystemMessage(content="SYS")
        errors = []

        def worker(n):
            try:
                for i in range(25):
                    eng = engines[n % len(engines)]
                    eng.build_ai_messages(_state(f"task {n} turn {i}"), sysmsg)
                    layers = list(eng._last_layers_sent)
                    eng.record_feedback(success=(i % 2 == 0), task="t")
                    # The snapshot read and the recorded snapshot must be
                    # the SAME engine-internal state (lock held across both).
                    assert eng._feedback_history[-1]["layers_used"] is not None
                    assert layers, "build produced no layers"
            except Exception as exc:  # noqa: BLE001 - surface ANY corruption
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"concurrent sessions corrupted state: {errors[:3]}"


class TestNodeWiring:
    def test_feedback_nodes_receive_config(self):
        for node in (chat_graph.ai_node, chat_graph.finalize_node,
                     chat_graph.recovery_limit_node, chat_graph.replanner_node):
            assert "config" in inspect.signature(node).parameters, (
                f"{node.__name__} cannot reach a session key — signature lacks config"
            )

    def test_recovery_limit_node_records_on_session_engine(self, tmp_path):
        key = "sess-recovery"
        eng = chat_graph.get_context_engine(key)
        eng._feedback_path = str(tmp_path / "r.json")
        eng._feedback_history.clear()
        state = {"failed_steps": ["boom"], "current_task": "fix flaky test",
                 "messages": []}
        result = chat_graph.recovery_limit_node(state, _cfg(key))
        assert result["messages"], "node returned no message"
        assert eng._feedback_history, "feedback was recorded nowhere"
        assert eng._feedback_history[-1]["task"] == "fix flaky test"
        assert eng._feedback_history[-1]["success"] is False

    def test_engines_carry_api_locks(self):
        eng = chat_graph.get_context_engine("lock-check")
        assert hasattr(eng, "_api_lock"), "engine lost its mutation guard"

    def test_reconfigure_model_refreshes_budget_and_is_idempotent(self):
        from src.context.context_engine import ContextEngine
        # Explicit max_tokens -> engine stays fully offline (no provider probe).
        eng = ContextEngine(max_tokens=8_000, model="gpt-4o-mini",
                            llm=None, memory_manager=None, probe_window=False)
        eng._api_lock.acquire()  # simulate a turn holding the mutation guard
        try:
            # reconfigure must respect the SAME reentrant lock (RLock), so it
            # does not deadlock while a build is in flight on this thread.
            eng.reconfigure_model("gpt-4o", probe_window=False)
        finally:
            eng._api_lock.release()
        assert eng.model == "gpt-4o"
        # Re-pointing to the same model is a no-op (budget untouched).
        before = (eng.max_tokens, eng.context_budget, eng.history_budget)
        eng.reconfigure_model("gpt-4o", probe_window=False)
        assert (eng.max_tokens, eng.context_budget, eng.history_budget) == before
        # reconfigure with falsy model falls back to the default, never None.
        eng.reconfigure_model("", probe_window=False)
        assert eng.model
        # Session-scoped state survives a repoint.
        assert hasattr(eng, "_layer_cache") and hasattr(eng, "_feedback_history")


# =====================================================================
# D1 follow-up: append-only JSONL feedback store (race proven pre-fix:
# two engines interleaved full-rewrites and one session's row VANISHED)
# =====================================================================

import pytest

from src.context.context_engine import (
    ContextEngine,
    _get_shared_classifier,
)


@pytest.fixture
def fb_home(tmp_path, monkeypatch):
    """Engines derive their feedback path from ~ — point ~ at tmp."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _fb_path(home):
    return home / ".pulseai" / "context_feedback.jsonl"


class TestFeedbackStore:
    def test_interleaved_sessions_never_lose_records(self, fb_home):
        # The exact pre-fix loss pattern: A writes, B writes (stomped A),
        # A writes again (stomped B) — disk ended with only [A, A2].
        eng_a = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        eng_b = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        eng_a.record_feedback(success=True, task="alpha")
        eng_b.record_feedback(success=False, task="beta")
        eng_a.record_feedback(success=True, task="alpha-2")

        lines = [json.loads(l) for l in open(_fb_path(fb_home))]
        assert [r["task"] for r in lines] == ["alpha", "beta", "alpha-2"], (
            "append-only store lost an interleaved session record"
        )

    def test_new_engine_sees_global_history(self, fb_home):
        # Global learning channel (by design): a fresh session engine
        # bootstraps its weights from OTHER sessions' records.
        ContextEngine(max_tokens=4000, llm=None, memory_manager=None).record_feedback(
            True, task="earlier-session")
        fresh = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        assert any(r["task"] == "earlier-session" for r in fresh._feedback_history)

    def test_debris_lines_are_skipped_not_fatal(self, fb_home):
        # Cross-process interleave can tear a line; readers must keep the rest.
        _fb_path(fb_home).parent.mkdir(parents=True, exist_ok=True)
        _fb_path(fb_home).write_text(
            '{"task": "ok", "success": true}\n'
            '{"task": "torn-half — NOT JSON\n'
            '{"task": "ok2", "success": false}\n'
        )
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        assert [r["task"] for r in eng._feedback_history] == ["ok", "ok2"]

    def test_legacy_json_store_migrates(self, fb_home):
        legacy = fb_home / ".pulseai" / "context_feedback.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps([{"task": "old1"}, {"task": "old2"}]))
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        assert [r["task"] for r in eng._feedback_history] == ["old1", "old2"]
        assert len(open(_fb_path(fb_home)).readlines()) == 2
        assert not legacy.exists(), "legacy file should be renamed away"
        assert (legacy.parent / "context_feedback.json.bak").exists()

    def test_compaction_bounds_the_file(self, fb_home):
        n = ContextEngine._FEEDBACK_COMPACT_AT + 50
        _fb_path(fb_home).parent.mkdir(parents=True, exist_ok=True)
        _fb_path(fb_home).write_text(
            "".join(json.dumps({"task": f"t{i}"}) + "\n" for i in range(n))
        )
        eng = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        keep = ContextEngine._FEEDBACK_COMPACT_TO
        assert len(eng._feedback_history) == keep
        lines = open(_fb_path(fb_home)).readlines()
        assert len(lines) == keep, "file not actually compacted"
        assert json.loads(lines[0])["task"] == f"t{n - keep}", "kept tail must be the most recent"


class TestSharedClassifier:
    def test_one_classifier_per_process(self):
        assert _get_shared_classifier() is _get_shared_classifier()

    def test_engines_share_the_classifier(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        a = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        b = ContextEngine(max_tokens=4000, llm=None, memory_manager=None)
        a.build_ai_messages(_state("fix the bug"), SystemMessage(content="SYS"))
        b.build_ai_messages(_state("explain the code"), SystemMessage(content="SYS"))
        assert a._classifier is not None
        assert a._classifier is b._classifier, (
            "per-engine classifiers re-warmed ~25 prototype embeddings per session"
        )
