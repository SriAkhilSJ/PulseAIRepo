"""
Context Builder — Context Construction and Layer Assembly
=========================================================

Responsible for:
- Combining retrieved chunks and system layers.
- Scoring, deduplicating, and hierarchically assembling layers.
- Applying context policies (sorting, compression, volatile tail placement).
- Building planner and reviser prompt message payloads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from langchain_core.messages import BaseMessage, SystemMessage

from src.context.ranking import layer_policy
from src.context import plan_messages
from src.context.task_types import TaskType


class ContextBuilder:
    """Constructs, formats, and manages context layers and payloads."""

    def __init__(
        self,
        model: str = "",
        allow_embedding_compute: bool = False,
        volatile_tail: bool = True,
        layer_relevance: Optional[dict[str, dict[TaskType, float]]] = None,
        volatile_layers: Optional[Set[str]] = None,
    ):
        self.model = model
        self.allow_embedding_compute = allow_embedding_compute
        self.volatile_tail = volatile_tail
        self.layer_relevance = layer_relevance or {}
        self.volatile_layers = volatile_layers or set()

    def build_layers(
        self,
        builders: dict[str, Callable[[dict[str, Any]], SystemMessage | None]],
        state: dict[str, Any],
        task_type: TaskType,
        layer_cache: dict[str, Any],
        last_state_hash: Optional[str] = None,
        current_hash: Optional[str] = None,
        walkers: Optional[list[str]] = None,
        active_pool: Any = None,
        set_active_budget_cb: Optional[Callable[[Any], None]] = None,
        layer_relevance: Optional[dict[str, dict[TaskType, float]]] = None,
        volatile_layers: Optional[Set[str]] = None,
        allowed_layers: Optional[Set[str] | frozenset[str]] = None,
        layer_dep_hashes: Optional[dict[str, str]] = None,
        current_layer_hashes: Optional[dict[str, str]] = None,
    ) -> list[SystemMessage]:
        """Execute registered layer builders, respecting cache, bounds, and autonomous skips."""
        walkers = walkers or []
        n_walkers = max(1, len(walkers))
        layers: list[SystemMessage] = []
        relevance = layer_relevance if layer_relevance is not None else self.layer_relevance
        volatiles = volatile_layers if volatile_layers is not None else self.volatile_layers

        autonomous = bool(state.get("_autonomous_workspace"))
        autonomous_skip = {
            "task", "tone", "quality", "ambiguity",
            "long_term_memory", "tool_memory", "memory_validation", "reflections",
        }
        if autonomous and not state.get("plan"):
            autonomous_skip.add("plan")
        if autonomous and not (
            state.get("steps_completed") or state.get("failed_steps")
        ):
            autonomous_skip.add("progress")
        if autonomous:
            workspace = Path(state.get("workspace", "."))
            try:
                empty_workspace = not any(path.is_file() for path in workspace.rglob("*"))
            except OSError:
                empty_workspace = False
            if empty_workspace:
                autonomous_skip.update({"repo_map", "relevant_chunks", "git_context", "conventions"})

        for name, builder in builders.items():
            if autonomous and name in autonomous_skip:
                continue
            if allowed_layers is not None and name not in allowed_layers:
                continue
            relevance_map = relevance.get(name, {})
            score = relevance_map.get(task_type, 0.0)
            if score < 0.15:
                continue

            cached = None if name in volatiles else layer_cache.get(name)
            is_hit = False
            if cached:
                if last_state_hash == current_hash and current_hash is not None:
                    is_hit = True
                elif (
                    layer_dep_hashes is not None
                    and current_layer_hashes is not None
                    and name in layer_dep_hashes
                    and name in current_layer_hashes
                    and layer_dep_hashes[name] == current_layer_hashes[name]
                ):
                    is_hit = True

            if is_hit:
                layers.append(cached)
                continue

            if set_active_budget_cb is not None:
                if name in walkers and active_pool is not None:
                    set_active_budget_cb(active_pool.share(n_walkers))
                else:
                    set_active_budget_cb(None)

            try:
                msg = builder(state)
                if msg:
                    msg.response_metadata["layer"] = name
                    layers.append(msg)
                    if name not in volatiles:
                        layer_cache[name] = msg
                        if (
                            layer_dep_hashes is not None
                            and current_layer_hashes is not None
                            and name in current_layer_hashes
                        ):
                            layer_dep_hashes[name] = current_layer_hashes[name]
            except Exception as exc:
                print(f"[ContextEngine] layer '{name}' builder failed: {exc}")
                continue

        return layers

    def score_and_sort_layers(
        self,
        layers: list[SystemMessage],
        task: str,
        task_type: TaskType,
        model: Optional[str] = None,
        allow_embedding_compute: Optional[bool] = None,
        relevance: Optional[dict] = None,
    ) -> list[tuple[float, SystemMessage, int]]:
        return layer_policy.score_and_sort_layers(
            layers,
            task,
            task_type,
            model=model or self.model,
            allow_embedding_compute=(
                self.allow_embedding_compute
                if allow_embedding_compute is None
                else allow_embedding_compute
            ),
            relevance=relevance or self.layer_relevance,
        )

    def infer_layer_name(self, msg: SystemMessage) -> str:
        return layer_policy.infer_layer_name(msg)

    def deduplicate_layers(
        self,
        scored_layers: list[tuple[float, SystemMessage, int]],
        allow_embedding_compute: Optional[bool] = None,
    ) -> list[tuple[float, SystemMessage, int]]:
        return layer_policy.deduplicate_layers(
            scored_layers,
            self.allow_embedding_compute
            if allow_embedding_compute is None
            else allow_embedding_compute,
        )

    def position_volatile_tail(
        self,
        context_messages: list[SystemMessage],
        trimmed_history: list,
        volatile_tail: Optional[bool] = None,
    ) -> list:
        return layer_policy.position_volatile_tail(
            context_messages,
            trimmed_history,
            self.volatile_tail if volatile_tail is None else volatile_tail,
        )

    def emission_sort_key(self, msg: SystemMessage) -> tuple:
        return layer_policy.emission_sort_key(msg)

    def assemble_hierarchical(
        self,
        scored_layers: list[tuple[float, SystemMessage, int]],
        budget: int,
        model: Optional[str] = None,
    ) -> list[SystemMessage]:
        return layer_policy.assemble_hierarchical(
            scored_layers, budget, model=model or self.model
        )

    def compress_layer(
        self,
        msg: SystemMessage,
        max_tokens: int,
        model: Optional[str] = None,
    ) -> Optional[SystemMessage]:
        return layer_policy.compress_layer(
            msg, max_tokens, model=model or self.model
        )

    def assemble_context_payload(
        self,
        layers: list[SystemMessage],
        task: str,
        task_type: TaskType,
        budget: int,
        trimmed_history: list,
    ) -> list:
        scored = self.score_and_sort_layers(layers, task, task_type)
        deduped = self.deduplicate_layers(scored)
        fitted = self.assemble_hierarchical(deduped, budget)
        return self.position_volatile_tail(fitted, trimmed_history)

    # Planner context methods
    @staticmethod
    def wrap_planner_prompt(planner_prompt: str) -> str:
        return plan_messages.wrap_planner_prompt(planner_prompt)

    @staticmethod
    def build_planner_messages(task: str, planner_prompt: str) -> list[BaseMessage]:
        return plan_messages.build_planner_messages(task, planner_prompt)

    @staticmethod
    def build_reviser_messages(
        task: str,
        plan: list[dict],
        revision: str,
        planner_prompt: str,
    ) -> list[BaseMessage]:
        return plan_messages.build_reviser_messages(
            task, plan, revision, planner_prompt
        )


__all__ = [
    "ContextBuilder",
]
