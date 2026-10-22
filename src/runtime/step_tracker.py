"""Granular Step-by-Step Diagnostic & Performance Engine for CrusorAI / PulseAI.

Tracks every internal node execution, tool dispatch, token usage, prompt-cache hit,
verification state, and diagnosed bottleneck across the entire lifecycle of an agent turn.

Exports to:
  - System traces at ~/.crusorai/traces/{session_id}.jsonl
  - Workspace reports at diagnostics/
      ├── traces/{session_id}.jsonl
      ├── PERFORMANCE_REPORT_{session_id}.md
      └── LATEST_PERFORMANCE_AUDIT.md
  - Rich CLI visualizer via `python scripts/diagnose_steps.py`
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.runtime.quality_evaluator import UserAskQualityEvaluator, QualityReport

_TRACE_LOCK = threading.Lock()

def estimate_cost(model_name: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0,
                  *, cache_reported: bool = False) -> float | None:
    """Estimate USD using the ledger's provider/manual catalog; unknown stays unknown."""
    from src.telemetry.call_ledger import estimate_cost_usd

    return estimate_cost_usd(
        model_name,
        input_tokens,
        output_tokens,
        cached_tokens=cached_tokens,
        cache_reported=cache_reported,
    )


@dataclass
class ToolExecutionRecord:
    name: str
    args_summary: str = ""
    status: str = "success"  # success, failed, timeout, denied
    duration_ms: float = 0.0
    exit_code: Optional[int] = None
    output_preview: str = ""
    error: Optional[str] = None


@dataclass
class StepRecord:
    session_id: str
    step_index: int
    node_name: str
    started_at: float
    ended_at: float = 0.0
    duration_s: float = 0.0
    llm_duration_s: float = 0.0
    tool_duration_s: float = 0.0
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_reported: bool = True
    cache_hit_ratio: float = 0.0
    tokens_per_second: float = 0.0
    estimated_cost_usd: float | None = None
    tool_calls: list[ToolExecutionRecord] = field(default_factory=list)
    verification_status: str = "not_applicable"
    compaction_active: bool = False
    plan_progress: str = ""
    user_ask: str = ""
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at_iso"] = datetime.fromtimestamp(
            self.started_at, tz=timezone.utc
        ).isoformat()
        if self.ended_at:
            d["ended_at_iso"] = datetime.fromtimestamp(
                self.ended_at, tz=timezone.utc
            ).isoformat()
        return d


class StepTracker:
    """Session-scoped tracker that records granular step metrics and auto-diagnoses bottlenecks."""

    _instances: dict[str, StepTracker] = {}
    _lock = threading.Lock()

    @classmethod
    def get_tracker(cls, session_id: str = "default", workspace_root: Optional[str] = None) -> StepTracker:
        with cls._lock:
            if session_id not in cls._instances:
                cls._instances[session_id] = StepTracker(session_id, workspace_root)
            return cls._instances[session_id]

    def __init__(self, session_id: str, workspace_root: Optional[str] = None):
        self.session_id = session_id or "default"
        self.steps: list[StepRecord] = []
        self._current_step: Optional[StepRecord] = None
        self._step_counter = 0
        self.start_time = time.time()
        self.user_ask: str = ""
        self.marked_edits: list[str] = []
        self.verification_status: str = "passed"
        self.final_assistant_message: str = ""
        self.verification_receipts: dict[str, Any] = {}

        # System-wide trace directory
        self.system_trace_dir = Path(os.path.expanduser("~")) / ".crusorai" / "traces"
        self.system_trace_dir.mkdir(parents=True, exist_ok=True)
        self.system_trace_file = self.system_trace_dir / f"{self.session_id}.jsonl"
        self.latest_symlink = self.system_trace_dir / "latest.jsonl"

        # Workspace diagnostics folder (always easily accessible)
        ws = Path(workspace_root) if workspace_root else Path.cwd()
        self.workspace_root = ws
        self.workspace_diag_dir = ws / "diagnostics"
        self.workspace_traces_dir = self.workspace_diag_dir / "traces"
        self.workspace_diag_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_traces_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_trace_file = self.workspace_traces_dir / f"{self.session_id}.jsonl"

    def set_user_ask(self, user_ask: str) -> None:
        """Set or update the user's prompt instruction."""
        if user_ask:
            self.user_ask = str(user_ask).strip()

    def set_final_message(self, message: str) -> None:
        """Set the final assistant completion message."""
        if message:
            self.final_assistant_message = str(message).strip()

    def set_verification_receipts(self, receipts: dict[str, Any]) -> None:
        """Attach verified receipts (e.g. browser console errors, typechecks)."""
        if receipts:
            self.verification_receipts = dict(receipts)

    def start_step(self, node_name: str, state: Optional[dict[str, Any]] = None) -> StepRecord:
        """Called when a LangGraph node starts executing."""
        self._step_counter += 1
        now = time.time()
        v_status = "not_applicable"
        plan_str = ""
        compaction_flag = False

        if state:
            v_status = str(state.get("verification_status") or "not_applicable")
            self.verification_status = v_status
            if not self.user_ask:
                # Extract initial user ask from task or messages
                task_candidate = state.get("current_task") or state.get("latest_instruction") or state.get("task")
                if task_candidate:
                    self.user_ask = str(task_candidate).strip()
                elif "messages" in state and state["messages"]:
                    for m in state["messages"]:
                        m_type = getattr(m, "type", None) or type(m).__name__.lower()
                        if "human" in m_type or "user" in m_type:
                            self.user_ask = str(getattr(m, "content", "")).strip()
                            break

            if state.get("marked_edits"):
                for edit_path in state["marked_edits"]:
                    if edit_path not in self.marked_edits:
                        self.marked_edits.append(str(edit_path))

            plan = state.get("plan") or []
            if plan:
                done = sum(1 for p in plan if p.get("status") == "completed")
                plan_str = f"{done}/{len(plan)}"
            compaction_flag = bool(state.get("usage_pressure_active", False))

        step = StepRecord(
            session_id=self.session_id,
            step_index=self._step_counter,
            node_name=node_name,
            started_at=now,
            verification_status=v_status,
            compaction_active=compaction_flag,
            plan_progress=plan_str,
            user_ask=self.user_ask,
        )
        self._current_step = step
        return step

    def record_llm_metrics(
        self,
        *,
        model: str,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: Optional[int] = 0,
        cache_reported: Optional[bool] = None,
        duration_s: float = 0.0,
    ) -> None:
        """Attach LLM token, latency, and cache metrics to the current step."""
        if not self._current_step:
            return
        self._current_step.model = str(model or "")
        self._current_step.provider = str(provider or "")
        self._current_step.input_tokens = int(input_tokens or 0)
        self._current_step.output_tokens = int(output_tokens or 0)
        self._current_step.cached_tokens = int(cached_tokens or 0)
        self._current_step.llm_duration_s = round(float(duration_s or 0.0), 3)

        # Provider / Gateway cache telemetry check (e.g. Velona omits input_token_details)
        custom_base = os.environ.get("CUSTOM_BASE_URL", "").lower()
        velona_base = os.environ.get("VELONA_BASE_URL", "").lower()
        is_velona = (
            "velona" in custom_base
            or "velona" in velona_base
            or "velona" in str(provider or "").lower()
        )
        if cache_reported is not None:
            self._current_step.cache_reported = bool(cache_reported)
        elif is_velona:
            self._current_step.cache_reported = False
        else:
            self._current_step.cache_reported = True

        if self._current_step.input_tokens > 0:
            self._current_step.cache_hit_ratio = round(
                self._current_step.cached_tokens / self._current_step.input_tokens, 4
            )
        if duration_s > 0 and self._current_step.output_tokens > 0:
            self._current_step.tokens_per_second = round(
                self._current_step.output_tokens / duration_s, 1
            )

        self._current_step.estimated_cost_usd = estimate_cost(
            self._current_step.model,
            self._current_step.input_tokens,
            self._current_step.output_tokens,
            self._current_step.cached_tokens,
            cache_reported=self._current_step.cache_reported,
        )

    def record_tool_call(
        self,
        name: str,
        args: Any = None,
        status: str = "success",
        duration_ms: float = 0.0,
        exit_code: Optional[int] = None,
        output: str = "",
        error: Optional[str] = None,
    ) -> None:
        """Record an executed tool call on the current step."""
        if not self._current_step:
            return

        if isinstance(args, dict):
            args_str = ", ".join(f"{k}={repr(v)[:50]}" for k, v in args.items())
        else:
            args_str = str(args)[:100]

        out_preview = str(output or "").strip()
        if len(out_preview) > 150:
            out_preview = out_preview[:140] + "..."

        rec = ToolExecutionRecord(
            name=name,
            args_summary=args_str,
            status=status,
            duration_ms=round(duration_ms, 2),
            exit_code=exit_code,
            output_preview=out_preview,
            error=error,
        )
        self._current_step.tool_calls.append(rec)
        self._current_step.tool_duration_s += round(duration_ms / 1000.0, 3)

    def finish_step(self, custom_diagnostics: Optional[list[str]] = None) -> StepRecord:
        """Finalize the current step, run automatic bottleneck checks, and persist."""
        if not self._current_step:
            return None  # type: ignore

        step = self._current_step
        step.ended_at = time.time()
        step.duration_s = round(step.ended_at - step.started_at, 3)

        # Performance Diagnostic Rules
        if step.node_name == "ai":
            if len(step.tool_calls) == 1 and step.tool_calls[0].name in (
                "read_file",
                "write_file",
                "edit_file",
            ):
                step.diagnostics.append(
                    "⚠️ UNDER_BATCHED: Single file tool emitted. Batching or PTC can collapse multiple turns into one."
                )

            if step.provider in ("openai", "anthropic", "deepseek", "groq") and step.input_tokens > 4000:
                if step.cached_tokens == 0 and getattr(step, "cache_reported", True):
                    step.diagnostics.append(
                        "⚠️ CACHE_MISS: 0 cached tokens on a large prompt. Ensure prompt prefix is byte-stable."
                    )
                elif step.cache_hit_ratio >= 0.70:
                    step.diagnostics.append(
                        f"✅ CACHE_HIT: {int(step.cache_hit_ratio * 100)}% of prompt served from cache."
                    )

            if step.duration_s > 15.0:
                step.diagnostics.append(
                    f"⚠️ LATENCY_SPIKE: Step took {step.duration_s}s (LLM: {step.llm_duration_s}s, Tools: {step.tool_duration_s}s)."
                )

        for tc in step.tool_calls:
            if tc.status != "success" or (tc.exit_code is not None and tc.exit_code != 0):
                step.diagnostics.append(
                    f"❌ TOOL_FAILURE: '{tc.name}' failed (exit {tc.exit_code}): {tc.error or tc.output_preview}"
                )

        if step.compaction_active:
            step.diagnostics.append(
                "ℹ️ COMPACTION_ACTIVE: Usage crossed 75% window threshold; running in lean history mode."
            )

        if custom_diagnostics:
            step.diagnostics.extend(custom_diagnostics)

        self.steps.append(step)
        self._current_step = None

        self._persist_step(step)
        self._export_markdown_report()
        return step

    def _persist_step(self, step: StepRecord) -> None:
        try:
            line = json.dumps(step.to_dict(), ensure_ascii=False)
            with _TRACE_LOCK:
                # 1. System trace
                with open(self.system_trace_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                with open(self.latest_symlink, "w", encoding="utf-8") as f:
                    f.write(self.system_trace_file.name)

                # 2. Workspace trace
                with open(self.workspace_trace_file, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def _known_total_cost_usd(self) -> float | None:
        metered = [s for s in self.steps if s.input_tokens or s.output_tokens]
        if not metered or any(s.estimated_cost_usd is None for s in metered):
            return None
        return round(sum(float(s.estimated_cost_usd) for s in metered), 4)

    def compute_performance_score(self) -> dict[str, Any]:
        """Compute an overall 0-100 Agent Performance Health Score."""
        if not self.steps:
            return {"score": 100, "grade": "A+", "breakdown": {}}

        total_steps = len(self.steps)
        total_duration = sum(s.duration_s for s in self.steps)
        avg_step_duration = total_duration / total_steps if total_steps > 0 else 0

        total_input_tokens = sum(s.input_tokens for s in self.steps)
        total_cached_tokens = sum(s.cached_tokens for s in self.steps)

        all_tool_calls = [tc for s in self.steps for tc in s.tool_calls]
        failed_tool_calls = [
            tc
            for tc in all_tool_calls
            if tc.status != "success" or (tc.exit_code is not None and tc.exit_code != 0)
        ]
        tool_failure_rate = (
            len(failed_tool_calls) / len(all_tool_calls) if all_tool_calls else 0.0
        )

        ai_steps = [s for s in self.steps if s.node_name == "ai"]
        multi_tool_steps = [s for s in ai_steps if len(s.tool_calls) > 1]
        batch_rate = (
            len(multi_tool_steps) / len(ai_steps) if len(ai_steps) > 0 else 1.0
        )

        # 1. Latency Score (Max 25 pts)
        latency_score = max(5.0, min(25.0, 25.0 - (max(0.0, avg_step_duration - 3.0) * 0.9)))

        # 2. Cache Score (Max 25 pts)
        # Check if cache telemetry is supported / reported by the upstream provider/gateway.
        # When using Velona or an OpenAI-compatible router that omits input_token_details,
        # cached_tokens is 0 on the wire even if KV-caching operates upstream.
        custom_base = os.environ.get("CUSTOM_BASE_URL", "").lower()
        velona_base = os.environ.get("VELONA_BASE_URL", "").lower()
        is_velona_session = (
            "velona" in custom_base
            or "velona" in velona_base
            or any("velona" in (s.provider or "").lower() for s in self.steps)
            or any(not getattr(s, "cache_reported", True) for s in self.steps)
        )

        has_cache_telemetry = (
            total_cached_tokens > 0
            or (not is_velona_session and any(s.provider in ("openai", "anthropic", "deepseek", "groq") for s in self.steps))
        )

        if total_cached_tokens > 0:
            cache_hit_rate = total_cached_tokens / total_input_tokens if total_input_tokens > 0 else 0.0
            cache_score = 5.0 + (cache_hit_rate * 20.0)
            telemetry_available = True
        elif is_velona_session or not has_cache_telemetry:
            # Upstream provider/gateway (e.g. Velona) does not return input_token_details metadata.
            # Do NOT dock 20 points from the agent health score; the prefix layout is active upstream.
            cache_hit_rate = 0.0
            cache_score = 25.0
            telemetry_available = False
        else:
            # Direct provider that supports telemetry reported 0 cached tokens (actual cache miss)
            cache_hit_rate = 0.0
            cache_score = 5.0
            telemetry_available = True

        # 3. Correctness & Error Score (Max 25 pts)
        error_score = max(0.0, 25.0 - (tool_failure_rate * 100.0))

        # 4. Batching & Concurrency Score (Max 25 pts)
        batch_score = 15.0 + (batch_rate * 10.0)

        total_score = round(latency_score + cache_score + error_score + batch_score, 1)

        if total_score >= 90:
            grade = "A (Elite)"
        elif total_score >= 80:
            grade = "B (Strong)"
        elif total_score >= 70:
            grade = "C (Moderate Bottlenecks)"
        else:
            grade = "D (Needs Optimization)"

        # Actionable Optimization Ideas
        ideas = []
        if telemetry_available:
            if cache_hit_rate < 0.60 and total_input_tokens > 20000:
                ideas.append("⚡ **Enable Prompt Caching:** Your prompt cache hit rate is below 60%. Ensure your system persona and tool definitions are placed at the static prefix to prevent cache-busting.")
        else:
            if total_input_tokens > 20000:
                ideas.append("ℹ️ **Provider Telemetry Notice:** Active gateway (Velona / custom router) omits `input_token_details` in completion chunks. Static prefix layout is maintained upstream at the server layer.")

        if avg_step_duration > 15.0:
            ideas.append("⏱️ **Reduce Turn Latency:** Consider using a direct-API caching provider (e.g. DeepSeek V3 or Claude Sonnet) or narrowing the active toolset.")
        if len(failed_tool_calls) > 0:
            ideas.append(f"🔧 **Tool Error Remediation:** {len(failed_tool_calls)} tool calls failed. Check environment setup, missing dependencies, or file paths.")
        if batch_rate < 0.30 and len(ai_steps) > 4:
            ideas.append("📦 **Encourage Parallel Tool Calling & PTC:** The model is emitting tools serially. Add prompt examples demonstrating multi-file writes in a single assistant turn.")

        if not ideas:
            ideas.append("🎉 **Optimal Performance:** Agent execution is fast, cache-aligned, and error-free.")

        return {
            "score": total_score,
            "grade": grade,
            "breakdown": {
                "latency_score": round(latency_score, 1),
                "cache_score": round(cache_score, 1),
                "correctness_score": round(error_score, 1),
                "batching_score": round(batch_score, 1),
            },
            "metrics": {
                "avg_step_duration_s": round(avg_step_duration, 2),
                "cache_hit_rate_pct": round(cache_hit_rate * 100, 1),
                "telemetry_available": telemetry_available,
                "tool_failure_rate_pct": round(tool_failure_rate * 100, 1),
                "total_cost_usd": self._known_total_cost_usd(),
                "priced_calls": sum(
                    1 for s in self.steps
                    if (s.input_tokens or s.output_tokens) and s.estimated_cost_usd is not None
                ),
                "total_cost_calls": sum(1 for s in self.steps if s.input_tokens or s.output_tokens),
            },
            "actionable_ideas": ideas,
        }

    def compute_quality_score(self, user_ask: Optional[str] = None) -> QualityReport:
        """Evaluate output quality, deliverable fulfillment, and constraint adherence against user prompt."""
        ask_text = user_ask or self.user_ask or ""
        all_tool_calls = [
            {"name": tc.name, "args": tc.args_summary, "status": tc.status, "exit_code": tc.exit_code}
            for s in self.steps
            for tc in s.tool_calls
        ]
        runtime_perf = self.compute_performance_score()

        evaluator = UserAskQualityEvaluator(str(self.workspace_root))
        return evaluator.evaluate(
            user_ask=ask_text,
            session_id=self.session_id,
            runtime_score=runtime_perf["score"],
            marked_edits=self.marked_edits,
            tool_records=all_tool_calls,
            verification_status=self.verification_status,
            final_assistant_message=self.final_assistant_message,
            verification_receipts=self.verification_receipts,
        )

    def compute_unified_agent_score(self, user_ask: Optional[str] = None) -> dict[str, Any]:
        """Compute complete multi-dimensional scorecard (Quality + Runtime Execution)."""
        runtime = self.compute_performance_score()
        quality_rep = self.compute_quality_score(user_ask)

        return {
            "unified_score": quality_rep.unified_score,
            "unified_grade": quality_rep.unified_grade,
            "quality": quality_rep.to_dict(),
            "runtime": runtime,
        }

    def _export_markdown_report(self) -> None:
        """Export a clean Markdown audit report with both Runtime and Output Quality scorecards."""
        try:
            perf = self.compute_performance_score()
            quality = self.compute_quality_score()
            total_tokens_in = sum(s.input_tokens for s in self.steps)
            total_tokens_out = sum(s.output_tokens for s in self.steps)
            cached_tokens = sum(s.cached_tokens for s in self.steps)
            total_time = sum(s.duration_s for s in self.steps)
            total_cost = perf["metrics"]["total_cost_usd"]
            total_cost_label = (
                f"**${total_cost:.4f} USD**"
                if total_cost is not None
                else f"**Unknown** ({perf['metrics']['priced_calls']}/{perf['metrics']['total_cost_calls']} token-bearing calls priced in USD)"
            )

            cache_val_str = (
                f"**{perf['metrics']['cache_hit_rate_pct']}%** ({cached_tokens:,} cached)"
                if perf["metrics"]["telemetry_available"]
                else f"**N/A** (Provider Velona/Gateway omits `input_token_details`)"
            )

            md = []
            md.append(f"# 📊 Agent Performance & Diagnostics Audit (Task Quality & Execution)")
            md.append(f"**Session ID:** `{self.session_id}`  ")
            md.append(f"**Generated At:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`  ")
            if self.user_ask:
                md.append(f"**User Ask:** *\"{self.user_ask}\"*  ")
            md.append("")
            md.append("---")
            md.append("## 🏆 Champion Agent Unified Scorecard")
            md.append("")
            md.append(f"| Dimension | Score | Grade | Weight |")
            md.append(f"| :--- | :--- | :--- | :--- |")
            md.append(f"| **Unified Benchmark Score** | **{quality.unified_score} / 100** | **`{quality.unified_grade}`** | **100%** |")
            md.append(f"| 🎯 **Output Quality & Fulfillment** | **{quality.quality_score} / 100** | `{quality.quality_grade}` | 60% |")
            md.append(f"| ⚡ **Runtime Execution & Economics** | **{perf['score']} / 100** | `{perf['grade']}` | 40% |")
            md.append("")
            md.append("---")
            md.append("## 🎯 Output Quality & Intent Fulfillment Breakdown")
            md.append("")
            for p_key, p_val in quality.pillars.items():
                p_dict = p_val.to_dict()
                icon = "✅" if p_dict["status"] == "pass" else ("⚠️" if p_dict["status"] == "warning" else "❌")
                md.append(f"### {icon} {p_dict['name']}: `{p_dict['score']} / {p_dict['max_score']}`")
                for d in p_dict["details"]:
                    md.append(f"- 🔹 {d}")
                for ded in p_dict["deductions"]:
                    md.append(f"- ⚠️ {ded}")
                md.append("")

            md.append("---")
            md.append("## ⚡ Runtime Execution & Economics Scorecard")
            md.append("")
            md.append(f"| Metric | Result | Target |")
            md.append(f"| :--- | :--- | :--- |")
            md.append(f"| **Runtime Health Score** | **{perf['score']} / 25** (`{perf['grade']}`) | $\\ge 85$ (Grade A) |")
            md.append(f"| **Total Steps & Duration** | {len(self.steps)} steps in {total_time:.1f}s (avg {perf['metrics']['avg_step_duration_s']}s/step) | $<5.0$s / step |")
            md.append(f"| **Total Token Usage** | {total_tokens_in:,} input / {total_tokens_out:,} output | Dynamic Bounded |")
            md.append(f"| **Prompt Cache Hit Rate** | {cache_val_str} | $\\ge 70\\%$ |")
            md.append(f"| **Estimated Cost** | {total_cost_label} | $< $0.05 / task |")
            md.append("")
            md.append("### Runtime Sub-Scores")
            md.append(f"- **Latency Efficiency:** `{perf['breakdown']['latency_score']} / 25`")
            md.append(f"- **Prompt Cache Stability:** `{perf['breakdown']['cache_score']} / 25`")
            md.append(f"- **Tool Correctness & Safety:** `{perf['breakdown']['correctness_score']} / 25`")
            md.append(f"- **Batching & Concurrency:** `{perf['breakdown']['batching_score']} / 25`")
            md.append("")
            md.append("---")
            md.append("## 💡 Actionable Improvement Ideas (How to Compete with Sharks)")
            md.append("")
            all_ideas = quality.recommendations + perf["actionable_ideas"]
            for idea in all_ideas:
                md.append(f"- {idea}")
            md.append("")
            md.append("---")
            md.append("## 📜 Step-by-Step Execution Log")
            md.append("")
            md.append("| Step | Node | Duration | Tokens (In/Out) | Cache % | Tools Executed & Status |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

            for s in self.steps:
                tools_str = ""
                for tc in s.tool_calls:
                    icon = "✅" if tc.status == "success" and (tc.exit_code is None or tc.exit_code == 0) else "❌"
                    tools_str += f"`{icon} {tc.name}` "
                if not tools_str:
                    tools_str = "*None*"

                if s.input_tokens > 0:
                    if getattr(s, "cache_reported", True) and s.cached_tokens > 0:
                        cache_str = f"{int(s.cache_hit_ratio * 100)}%"
                    elif not getattr(s, "cache_reported", True) or not perf["metrics"]["telemetry_available"]:
                        cache_str = "N/A"
                    else:
                        cache_str = "0%"
                else:
                    cache_str = "-"
                tok_str = f"{s.input_tokens:,} / {s.output_tokens:,}" if s.input_tokens > 0 else "-"
                md.append(f"| **{s.step_index}** | `{s.node_name}` | {s.duration_s:.2f}s | {tok_str} | {cache_str} | {tools_str} |")

            md_content = "\n".join(md)

            # Write specific session report and latest pointer
            session_report = self.workspace_diag_dir / f"PERFORMANCE_REPORT_{self.session_id}.md"
            latest_report = self.workspace_diag_dir / "LATEST_PERFORMANCE_AUDIT.md"

            with _TRACE_LOCK:
                with open(session_report, "w", encoding="utf-8") as f:
                    f.write(md_content)
                with open(latest_report, "w", encoding="utf-8") as f:
                    f.write(md_content)
        except Exception:
            pass


def print_step_report(session_id: Optional[str] = None, user_ask: Optional[str] = None) -> None:
    """CLI printer that renders a clean colored diagnostic view of the agent run."""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    trace_dir = Path(os.path.expanduser("~")) / ".crusorai" / "traces"
    if not session_id:
        latest_file = trace_dir / "latest.jsonl"
        if latest_file.exists():
            session_id = latest_file.read_text(encoding="utf-8").strip().replace(".jsonl", "")
        else:
            files = sorted(trace_dir.glob("*.jsonl"), key=os.path.getmtime, reverse=True)
            if files:
                session_id = files[0].stem
            else:
                # Check workspace traces
                ws_traces = sorted(Path("diagnostics/traces").glob("*.jsonl"), key=os.path.getmtime, reverse=True)
                if ws_traces:
                    session_id = ws_traces[0].stem
                else:
                    print("❌ No trace records found.")
                    return

    target_file = trace_dir / f"{session_id}.jsonl"
    if not target_file.exists():
        # Try prefix matching in trace_dir
        matches = list(trace_dir.glob(f"*{session_id}*.jsonl"))
        if matches:
            target_file = matches[0]
        else:
            ws_matches = list((Path("diagnostics/traces")).glob(f"*{session_id}*.jsonl"))
            if ws_matches:
                target_file = ws_matches[0]
            else:
                target_file = Path("diagnostics/traces") / f"{session_id}.jsonl"

    if not target_file.exists():
        print(f"❌ Trace file not found for session: {session_id}")
        return

    records = []
    with open(target_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    if not records:
        print("❌ Trace file is empty.")
        return

    tracker = StepTracker(session_id)
    tracker.steps = [
        StepRecord(
            session_id=session_id,
            step_index=r.get("step_index", i + 1),
            node_name=r.get("node_name", ""),
            started_at=r.get("started_at", 0),
            ended_at=r.get("ended_at", 0),
            duration_s=r.get("duration_s", 0),
            llm_duration_s=r.get("llm_duration_s", 0),
            tool_duration_s=r.get("tool_duration_s", 0),
            model=r.get("model", ""),
            provider=r.get("provider", ""),
            input_tokens=r.get("input_tokens", 0),
            output_tokens=r.get("output_tokens", 0),
            cached_tokens=r.get("cached_tokens", 0),
            cache_hit_ratio=r.get("cache_hit_ratio", 0),
            tokens_per_second=r.get("tokens_per_second", 0),
            estimated_cost_usd=r.get("estimated_cost_usd", 0),
            tool_calls=[ToolExecutionRecord(**tc) for tc in r.get("tool_calls", [])],
            verification_status=r.get("verification_status", "not_applicable"),
            compaction_active=r.get("compaction_active", False),
            diagnostics=r.get("diagnostics", []),
            user_ask=r.get("user_ask", ""),
        )
        for i, r in enumerate(records)
    ]

    inferred_user_ask = user_ask
    if not inferred_user_ask:
        for r in records:
            if r.get("user_ask"):
                inferred_user_ask = r["user_ask"]
                break

    perf = tracker.compute_performance_score()
    quality = tracker.compute_quality_score(inferred_user_ask)
    total_tokens_in = sum(s.input_tokens for s in tracker.steps)
    total_tokens_out = sum(s.output_tokens for s in tracker.steps)
    cached_tokens = sum(s.cached_tokens for s in tracker.steps)
    total_time = sum(s.duration_s for s in tracker.steps)

    cache_val_str = (
        f"{perf['metrics']['cache_hit_rate_pct']}% ({cached_tokens:,} tokens cached)"
        if perf["metrics"]["telemetry_available"]
        else f"N/A (Provider Velona/Gateway omits input_token_details)"
    )

    print("=" * 80)
    print(f" 📊 CHAMPION AGENT EVALUATION REPORT — Session: {session_id}")
    print("=" * 80)
    print(f"• UNIFIED BENCHMARK SCORE : {quality.unified_score}/100 [{quality.unified_grade}]")
    print(f"• 🎯 Output Quality Score : {quality.quality_score}/100 [{quality.quality_grade}]")
    print(f"• ⚡ Runtime Health Score : {perf['score']}/100 [{perf['grade']}]")
    print(f"• Total Steps & Duration  : {len(tracker.steps)} steps in {total_time:.1f}s (avg {perf['metrics']['avg_step_duration_s']}s/step)")
    print(f"• Total Tokens & Cost     : {total_tokens_in:,} in / {total_tokens_out:,} out (${perf['metrics']['total_cost_usd']:.4f} USD)")
    print(f"• Prompt Cache Hit Rate   : {cache_val_str}")
    print("-" * 80)
    print(f"  Quality Pillars: Deliverables: {quality.pillars['deliverables'].score}/35 | Constraints: {quality.pillars['constraints'].score}/25 | Soundness: {quality.pillars['soundness'].score}/25 | Polish: {quality.pillars['presentation'].score}/15")
    print(f"  Runtime Pillars: Latency: {perf['breakdown']['latency_score']}/25 | Cache: {perf['breakdown']['cache_score']}/25 | Tools: {perf['breakdown']['correctness_score']}/25 | Batching: {perf['breakdown']['batching_score']}/25")
    print("=" * 80)

    print(f"{'#':<3} | {'Node':<10} | {'Time':<6} | {'Tokens (In/Out)':<16} | {'Cache %':<8} | {'Tools Executed / Status':<28}")
    print("-" * 80)

    for s in tracker.steps:
        tools_str = ""
        for tc in s.tool_calls:
            icon = "✅" if tc.status == "success" and (tc.exit_code is None or tc.exit_code == 0) else "❌"
            tools_str += f"{icon} {tc.name} "
        if not tools_str:
            tools_str = "(no tools)"
        
        if s.input_tokens > 0:
            if getattr(s, "cache_reported", True) and s.cached_tokens > 0:
                c_hit = f"{int(s.cache_hit_ratio * 100)}%"
            elif not getattr(s, "cache_reported", True) or not perf["metrics"]["telemetry_available"]:
                c_hit = "N/A"
            else:
                c_hit = "0%"
        else:
            c_hit = "-"
        tok_str = f"{s.input_tokens}/{s.output_tokens}"
        print(f"{s.step_index:<3} | {s.node_name:<10} | {s.duration_s:<5.2f}s | {tok_str:<16} | {c_hit:<8} | {tools_str:<28}")

    print("\n" + "=" * 80)
    print(" 💡 ACTIONABLE IMPROVEMENT IDEAS (Saved to diagnostics/ folder):")
    print("=" * 80)
    for idea in (quality.recommendations + perf["actionable_ideas"]):
        print(f" • {idea}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    print_step_report(sid)
