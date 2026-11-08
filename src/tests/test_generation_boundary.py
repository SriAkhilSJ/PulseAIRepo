"""Generation-boundary repair (provider-free).

Live10 evidence: `src/duration.py` returned `finish_reason='length'` at exactly
8192 output tokens and the fail-closed adapter refused to write it. There was no
recovery path, so the turn died before tests or titling.

This suite pins:

* finish-reason normalization and fail-closed truncation detection;
* provider-aware effective output ceilings (no invented caps);
* one bounded recovery regeneration (a NEW paid dispatch, never a merge);
* no partial/invalid source ever reaches the workspace;
* separate reservation/settlement/ledger record for the recovery;
* dispatch-budget and cancellation limits;
* the exact P0.6.7 historical prompt with a Live10-shaped truncation, then a
  complete recovery, 10/10 pytest and clean cross-file validation.

All provider clients here are deterministic fakes. No network.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src.orchestration.model_adapter as ma
from src.finops.invocation_context import read_invocations
from src.llm.acceptance_guard import acceptance_mode
from src.llm.factory import RetryLLMProxy
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.orchestration.model_adapter import (
    IncompleteModelOutputError,
    ModelExecutionAdapter,
    assert_provider_output_complete,
    extract_generated_source,
)
from src.orchestration.models import ExecutionLimits, EngineeringTaskNode
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator

REPO = Path(__file__).resolve().parents[2]
LIVE7 = REPO / "diagnostics" / "p0_6_7" / "live7" / "evidence.json"
PROMPT = json.loads(LIVE7.read_text(encoding="utf-8"))["prompt"]
PROMPT_SHA = "a887a669c05b7f2c1392405f830d0661b517dbadc7aa30ce75a253b254fe05f8"

FIXED_MODULE = '''from __future__ import annotations

import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_COMPONENT = re.compile(r"(\\d+)([hms])")


def parse_duration(value: str) -> int:
    """Parse a duration such as '1h30m' into whole seconds."""
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    if not value.strip():
        raise ValueError("empty duration")
    if "-" in value:
        raise ValueError("negative durations are not allowed")
    if "." in value:
        raise ValueError("floats are not accepted")
    compact = value.replace(" ", "")
    units = re.findall(r"([hms])", compact)
    if len(units) != len(set(units)):
        raise ValueError("duplicate units are not allowed")
    position = 0
    total = 0
    for match in _COMPONENT.finditer(compact):
        if match.start() != position:
            raise ValueError("missing number or unknown unit")
        total += int(match.group(1)) * _UNITS[match.group(2)]
        position = match.end()
    if position != len(compact):
        raise ValueError("unknown unit or missing number")
    return total
'''

FIXED_TEST = '''import pytest
from src.duration import parse_duration


def test_one_hour_thirty_minutes():
    assert parse_duration("1h30m") == 5400


def test_two_minutes_fifteen_seconds():
    assert parse_duration("2m 15s") == 135


def test_forty_five_seconds():
    assert parse_duration("45s") == 45


def test_hour_minute_second_with_spaces():
    assert parse_duration("1h 30m 15s") == 5415


def test_duplicate_unit_raises():
    with pytest.raises(ValueError):
        parse_duration("1h1h")


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        parse_duration("1d")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        parse_duration("")


def test_missing_number_raises():
    with pytest.raises(ValueError):
        parse_duration("h")


def test_negative_value_raises():
    with pytest.raises(ValueError):
        parse_duration("-1h")


def test_non_string_raises_type_error():
    with pytest.raises(TypeError):
        parse_duration(42)
'''

TRUNCATED = '```python\nfrom __future__ import annotations\n\nimport re\n\n\ndef parse_duration('


class Resp:
    def __init__(self, content: str, *, finish: str = "stop",
                 in_tok: int = 100, out_tok: int = 50, usage: bool = True):
        self.content = content
        self.response_metadata = {"finish_reason": finish} if finish else {}
        self.additional_kwargs = {}
        self.tool_calls = []
        if usage:
            self.usage_metadata = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
            }


def _target(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("Target file path:"):
            return line.split(":", 1)[1].strip()
    return ""


class Live10LLM:
    """First source response truncated; recovery and tests complete."""

    def __init__(self, *, recovery: Resp | None = None, always_truncated: bool = False):
        self.prompts: list[str] = []
        self.kwargs: list[dict] = []
        self.recovery = recovery
        self.always_truncated = always_truncated
        self._max_attempts = 1

    def invoke(self, prompt: str, **kwargs):
        self.prompts.append(prompt)
        self.kwargs.append(kwargs)
        target = _target(prompt)
        if target.endswith("test_duration.py"):
            return Resp(f"```python\n{FIXED_TEST}\n```", out_tok=300)
        if "RECOVERY:" in prompt:
            if self.recovery is not None:
                return self.recovery
            if self.always_truncated:
                return Resp(TRUNCATED, finish="length", out_tok=8192)
            return Resp(f"```python\n{FIXED_MODULE}\n```", out_tok=900)
        return Resp(TRUNCATED, finish="length", out_tok=8192)


class ScopedLLM:
    def __init__(self):
        self.calls = 0
        self.kwargs: list[dict] = []
        self._max_attempts = 1

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        return Resp(f"```python\n{FIXED_MODULE}\n```")


def _git_ws() -> Path:
    ws = Path(tempfile.mkdtemp(prefix="p0_gen_boundary_")).resolve()
    (ws / "README.md").write_text("# ws\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=False)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=ws, check=False)
    subprocess.run(["git", "config", "user.name", "a"], cwd=ws, check=False)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=False)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=ws, check=False)
    return ws


def _independent_smoke(module_path: Path) -> dict:
    """Run the acceptance harness's own 9-check contract smoke.

    Reusing ``LiveAcceptance._independent_smoke`` keeps the offline replay
    honest: these are not the agent's tests, they are the harness checks the
    live acceptance would have run after the turn.
    """
    harness_path = REPO / "benchmarks" / "crusor_desktop_acceptance" / "live_acceptance.py"
    spec = importlib.util.spec_from_file_location("live_acceptance", harness_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_acceptance"] = module
    spec.loader.exec_module(module)
    return module.LiveAcceptance._independent_smoke(module_path)


def _new_orchestrator(ws: Path) -> EngineeringExecutionOrchestrator:    return EngineeringExecutionOrchestrator(
        str(ws), tenant_id="p0_gen_boundary",
        limits=ExecutionLimits(
            max_cost_inr=5.0, max_dispatch_budget=5,
            max_correction_attempts=0, test_timeout_seconds=120.0,
        ),
        mock_mode=False, provider="custom", model="z-ai/glm-5.3-flash",
    )


def _run_historical(ws: Path, llm):
    original = ma.get_llm
    ma.get_llm = lambda provider=None, model=None: llm
    try:
        orch = _new_orchestrator(ws)
        return orch, orch.run_task(task_prompt=PROMPT, task_id="task_gen_boundary")
    finally:
        ma.get_llm = original


def _run_historical_failure(ws: Path, llm):
    """Run the same historical task, returning the fail-closed exception.

    A generation-boundary failure aborts the turn (it must never return a
    COMPLETED delivery). The governor still reconciles in ``run_task``'s
    ``finally`` block, so accounting can be inspected after the raise.
    """
    original = ma.get_llm
    ma.get_llm = lambda provider=None, model=None: llm
    orch = _new_orchestrator(ws)
    try:
        try:
            orch.run_task(task_prompt=PROMPT, task_id="task_gen_boundary")
        except Exception as exc:  # noqa: BLE001 - the raise IS the assertion
            return orch, exc
        return orch, None
    finally:
        ma.get_llm = original


# --------------------------------------------------------------------------- #
# finish-reason and extraction boundaries
# --------------------------------------------------------------------------- #

class TestFinishReasonBoundary(unittest.TestCase):
    def test_incomplete_finish_reasons_fail_closed(self) -> None:
        for reason in ("length", "max_tokens", "max_output_tokens", "token_limit", "incomplete"):
            with self.subTest(reason=reason):
                with self.assertRaises(IncompleteModelOutputError):
                    assert_provider_output_complete(Resp("```python\nx=1\n```", finish=reason), "src/x.py")

    def test_successful_finish_reasons_pass(self) -> None:
        for reason in ("stop", "tool_calls", ""):
            with self.subTest(reason=reason):
                assert_provider_output_complete(Resp("```python\nx=1\n```", finish=reason), "src/x.py")

    def test_malformed_metadata_does_not_crash(self) -> None:
        response = SimpleNamespace(content="```python\nx=1\n```", response_metadata="not-a-dict")
        assert_provider_output_complete(response, "src/x.py")

    def test_truncated_text_is_not_extracted(self) -> None:
        # An unclosed fence is rejected even if the provider did not report a
        # finish reason; extraction never guesses a complete payload.
        with self.assertRaises(Exception):
            extract_generated_source("```python\ndef f(:\n", "src/x.py")


# --------------------------------------------------------------------------- #
# provider-aware output ceiling
# --------------------------------------------------------------------------- #

class TestOutputCeiling(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = Path(tempfile.mkdtemp(prefix="p0_gen_cap_")).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def _node(self) -> EngineeringTaskNode:
        return EngineeringTaskNode(
            node_id="task_duration", description="Implement src/x.py",
            objective="Create src/x.py with function f(value).",
            target_files=["src/x.py"], max_tokens=8192,
        )

    def _finops(self) -> OrchestrationFinOpsGovernor:
        return OrchestrationFinOpsGovernor(
            "cap_task", budget_inr=5.0, token_budget=150000,
            storage_dir=str(self.ws / "finops"), workspace_root=str(self.ws),
        )

    def test_request_uses_provider_aware_effective_cap(self) -> None:
        from src.llm.output_budget import requested_output_cap

        llm = ScopedLLM()
        adapter = ModelExecutionAdapter(
            str(self.ws), tenant_id="t", mock_mode=False,
            provider="custom", model="z-ai/glm-5.3-flash",
        )
        original = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: llm
        try:
            code = adapter._call_model_for_implementation(
                node=self._node(), target_file="src/x.py", existing_content="",
                specification=None, blueprint=None, project_knowledge=None,
                finops=self._finops(),
            )
        finally:
            ma.get_llm = original
        self.assertIn("def parse_duration", code)
        expected = requested_output_cap("z-ai/glm-5.3-flash", provider="custom", requested=8192)
        self.assertEqual(llm.kwargs[0]["max_tokens"], expected)
        self.assertLessEqual(expected, 8192)

    def test_unknown_model_does_not_invent_a_new_cap(self) -> None:
        from src.llm.output_budget import requested_output_cap

        self.assertEqual(
            requested_output_cap("no/such-model", provider="custom", requested=8192),
            8192,
        )

    def test_complete_first_response_does_not_recover(self) -> None:
        llm = ScopedLLM()
        adapter = ModelExecutionAdapter(
            str(self.ws), tenant_id="t", mock_mode=False,
            provider="custom", model="z-ai/glm-5.3-flash",
        )
        original = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: llm
        try:
            adapter._call_model_for_implementation(
                node=self._node(), target_file="src/x.py", existing_content="",
                specification=None, blueprint=None, project_knowledge=None,
                finops=self._finops(),
            )
        finally:
            ma.get_llm = original
        self.assertEqual(llm.calls, 1)
        self.assertEqual(adapter.generation_recoveries, [])
        self.assertNotIn("RECOVERY:", llm.prompts[0] if hasattr(llm, "prompts") else "")


# --------------------------------------------------------------------------- #
# historical replay (Live10 shape) through the full orchestrator
# --------------------------------------------------------------------------- #

class TestHistoricalReplay(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = _git_ws()

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_live10_truncation_recovers_and_completes(self) -> None:
        self.assertEqual(hashlib.sha256(PROMPT.encode()).hexdigest(), PROMPT_SHA)
        llm = Live10LLM()
        orch, delivery = _run_historical(self.ws, llm)

        self.assertEqual(delivery.verdict.value, "COMPLETED", delivery.remaining_limitations)
        self.assertTrue(delivery.independently_verified)
        self.assertEqual(len(llm.prompts), 3, "source + recovery + tests")
        self.assertEqual(len(delivery.generation_recoveries), 1)
        self.assertEqual(delivery.generation_recoveries[0]["target_file"], "src/duration.py")
        self.assertIn("RECOVERY:", [p for p in llm.prompts if "Target file path: src/duration.py" in p][1])

        source = (self.ws / "src" / "duration.py").read_text(encoding="utf-8")
        self.assertIn("def parse_duration", source)
        self.assertEqual(source.count("def parse_duration"), 1,
                         "recovery must replace, never concatenate")
        self.assertLessEqual(len(source.splitlines()), 120)

        result = delivery.test_evidence["final_run"]
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(delivery.cross_file_validation["ok"])

        smoke = _independent_smoke(self.ws / "src" / "duration.py")
        self.assertTrue(smoke["ok"], smoke)
        self.assertEqual(len(smoke["checks"]), 9)
        self.assertTrue(all(smoke["checks"].values()), smoke)

        self.assertEqual(
            sorted(delivery.files_changed),
            ["src/duration.py", "tests/test_duration.py"],
            "no unrelated file may be mutated by the replay",
        )

        fin = orch._last_finops
        self.assertEqual(fin.accounting.calls_count, 3)
        self.assertEqual(len(fin._settled_reservations), 3)
        self.assertEqual(len(fin._active_reservations), 0)
        self.assertEqual(len(fin._uncertain_reservations), 0)

        records = read_invocations(self.ws)
        self.assertEqual(len(records), 3)
        self.assertTrue(all(r["status"] == "settled" for r in records))
        recovery = [r for r in records if r["operation_type"] == "recovery"]
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0]["purpose"], "node_task_duration_recovery1")
        self.assertEqual(len({r["reservation_id"] for r in records}), 3)
        self.assertAlmostEqual(
            sum(r["actual_cost_inr"] for r in records),
            fin.accounting.spent_inr,
            places=6,
        )

        journal = list(self.ws.rglob("orchestration_journal.jsonl"))[0]
        events = [json.loads(line)["event_type"] for line in journal.read_text(encoding="utf-8").splitlines()]
        self.assertIn("GENERATION_RECOVERIES", events)

    def test_always_truncated_fails_without_writing_source(self) -> None:
        llm = Live10LLM(always_truncated=True)
        orch, exc = _run_historical_failure(self.ws, llm)
        self.assertIsNotNone(exc)
        self.assertIn("Provider stopped before completing output", str(exc))
        self.assertIn("finish_reason='length'", str(exc))
        self.assertFalse((self.ws / "src" / "duration.py").exists())
        source_prompts = [p for p in llm.prompts if "Target file path: src/duration.py" in p]
        self.assertEqual(len(source_prompts), 2, "one original + one bounded recovery")
        self.assertIn("RECOVERY:", source_prompts[1])
        self.assertEqual(orch._last_finops.accounting.calls_count, len(llm.prompts),
                         "no hidden provider calls")
        self.assertEqual(len(orch._last_finops._uncertain_reservations), 0)

    def test_recovery_with_invalid_python_never_mutates(self) -> None:
        llm = Live10LLM(recovery=Resp("```python\ndef parse_duration(:\n```", out_tok=50))
        orch, exc = _run_historical_failure(self.ws, llm)
        self.assertIsNotNone(exc)
        self.assertFalse((self.ws / "src" / "duration.py").exists())
        self.assertEqual(orch._last_finops.accounting.calls_count, len(llm.prompts))

    def test_recovery_with_malformed_fence_never_mutates(self) -> None:
        llm = Live10LLM(recovery=Resp("```python\ndef parse_duration(value: str) -> int:\n    return 1\n", out_tok=50))
        orch, exc = _run_historical_failure(self.ws, llm)
        self.assertIsNotNone(exc)
        self.assertFalse((self.ws / "src" / "duration.py").exists())

    def test_recovery_missing_usage_is_uncertain_not_free(self) -> None:
        llm = Live10LLM(recovery=Resp(f"```python\n{FIXED_MODULE}\n```", usage=False))
        orch, exc = _run_historical_failure(self.ws, llm)
        self.assertIsNotNone(exc)
        self.assertFalse((self.ws / "src" / "duration.py").exists())
        self.assertGreaterEqual(len(orch._last_finops._uncertain_reservations), 1)


# --------------------------------------------------------------------------- #
# bounded dispatch + cancellation
# --------------------------------------------------------------------------- #

class TestRecoveryBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.ws = Path(tempfile.mkdtemp(prefix="p0_gen_budget_")).resolve()
        self.node = EngineeringTaskNode(
            node_id="task_x", description="Implement src/x.py",
            objective="Create src/x.py with function f(value).",
            target_files=["src/x.py"], max_tokens=8192,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.ws, ignore_errors=True)

    def _adapter(self):
        return ModelExecutionAdapter(
            str(self.ws), tenant_id="t", mock_mode=False,
            provider="custom", model="z-ai/glm-5.3-flash",
        )

    def _finops(self):
        return OrchestrationFinOpsGovernor(
            "budget_task", budget_inr=5.0, token_budget=150000,
            storage_dir=str(self.ws / "finops"), workspace_root=str(self.ws),
        )

    def test_acceptance_guard_blocks_recovery_at_zero_remaining(self) -> None:
        inner = Live10LLM()
        proxy = RetryLLMProxy(inner, max_attempts=1, provider="custom")
        adapter = self._adapter()
        original = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: proxy
        try:
            with acceptance_mode("gen-boundary", max_dispatches=1):
                with self.assertRaises(IncompleteModelOutputError):
                    adapter._call_model_for_implementation(
                        node=self.node, target_file="src/x.py", existing_content="",
                        specification=None, blueprint=None, project_knowledge=None,
                        finops=self._finops(),
                    )
        finally:
            ma.get_llm = original
        self.assertEqual(inner.prompts.__len__(), 1, "no second claim after exhaustion")

    def test_cancellation_stops_before_recovery(self) -> None:
        inner = Live10LLM()
        adapter = self._adapter()
        original = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: inner
        try:
            with self.assertRaises(Exception):
                adapter._call_model_for_implementation(
                    node=self.node, target_file="src/x.py", existing_content="",
                    specification=None, blueprint=None, project_knowledge=None,
                    finops=self._finops(),
                    cancellation_checker=lambda: True,
                )
        finally:
            ma.get_llm = original
        self.assertEqual(len(inner.prompts), 1)

    def test_recovery_limit_can_be_disabled(self) -> None:
        inner = Live10LLM()
        adapter = self._adapter()
        original = ma.get_llm
        ma.get_llm = lambda provider=None, model=None: inner
        try:
            with patch.dict(os.environ, {"CRUSORAI_MAX_GENERATION_RECOVERIES": "0"}):
                with self.assertRaises(IncompleteModelOutputError):
                    adapter._call_model_for_implementation(
                        node=self.node, target_file="src/x.py", existing_content="",
                        specification=None, blueprint=None, project_knowledge=None,
                        finops=self._finops(),
                    )
        finally:
            ma.get_llm = original
        self.assertEqual(len(inner.prompts), 1)


if __name__ == "__main__":
    unittest.main()
