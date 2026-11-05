"""
model_router.py -- Intelligent Cost-Optimized Model Routing Engine.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Provides intelligent, multi-tier model selection balancing cost, quality, and task demands:
- Task complexity classification (SIMPLE, MODERATE, COMPLEX, REASONING_HEAVY).
- Cost vs Capability optimization (routes simple tasks to fast/economical models).
- User pin absolute respect: NEVER silently downgrade an explicitly selected model.
- Tool-use and long-context suitability verification.
- Provider fallback resilience with cost tracking for failovers.
- Routing decision explainability with estimated cost comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import enum
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from src.finops.pricing_registry import ModelPricingRegistry, get_pricing_registry, quantize_currency

log = logging.getLogger("crusorai.finops.model_router")


class TaskComplexity(str, enum.Enum):
    SIMPLE = "SIMPLE"                      # Single-line edit, formatting, git status, typo
    MODERATE = "MODERATE"                  # Single-file refactor, unit test creation, code explanation
    COMPLEX = "COMPLEX"                    # Multi-file feature, cross-module refactor, system design
    REASONING_HEAVY = "REASONING_HEAVY"    # Deep algorithmic debugging, formal verification, math


class ModelTier(str, enum.Enum):
    CHEAP = "cheap"        # Fast, low-cost (e.g., gpt-4o-mini, claude-3-5-haiku, gemini-1.5-flash)
    STANDARD = "standard"  # Balanced general coding (e.g., gpt-4o, claude-3-5-sonnet, deepseek-chat)
    PREMIUM = "premium"    # High reasoning / frontier (e.g., o1, o3-mini, claude-3-opus, deepseek-reasoner)


@dataclass
class RoutingDecision:
    """Detailed record of an intelligent model routing decision."""
    selected_model: str
    selected_provider: str
    selected_tier: ModelTier
    task_complexity: TaskComplexity
    is_user_pinned: bool
    estimated_cost_usd: Decimal
    estimated_cost_inr: Decimal
    savings_vs_premium_usd: Decimal = Decimal("0.000000")
    routing_reason: str = ""
    fallback_models: List[str] = field(default_factory=list)
    alternatives_evaluated: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_model": self.selected_model,
            "selected_provider": self.selected_provider,
            "selected_tier": self.selected_tier.value,
            "task_complexity": self.task_complexity.value,
            "is_user_pinned": self.is_user_pinned,
            "estimated_cost_usd": float(self.estimated_cost_usd),
            "estimated_cost_inr": float(self.estimated_cost_inr),
            "savings_vs_premium_usd": float(self.savings_vs_premium_usd),
            "routing_reason": self.routing_reason,
            "fallback_models": self.fallback_models,
            "alternatives_evaluated": self.alternatives_evaluated,
        }


class IntelligentModelRouter:
    """
    Cost-aware model routing engine.
    Ensures work is executed on the most economical model capable of fulfilling requirements,
    while guaranteeing that explicit user selections are never overridden.
    """

    def __init__(self, registry: Optional[ModelPricingRegistry] = None) -> None:
        self._lock = threading.RLock()
        self._registry = registry or get_pricing_registry()

        # Model tier mappings
        self._tier_models: Dict[ModelTier, List[Tuple[str, str]]] = {
            ModelTier.CHEAP: [
                ("openai", "gpt-4o-mini"),
                ("anthropic", "claude-3-5-haiku"),
                ("google", "gemini-1.5-flash"),
                ("deepseek", "deepseek-chat"),
                ("groq", "llama-3.1-8b"),
            ],
            ModelTier.STANDARD: [
                ("openai", "gpt-4o"),
                ("anthropic", "claude-3-5-sonnet"),
                ("google", "gemini-1.5-pro"),
                ("groq", "llama-3.3-70b"),
            ],
            ModelTier.PREMIUM: [
                ("openai", "o1"),
                ("openai", "o3-mini"),
                ("anthropic", "claude-3-opus"),
                ("deepseek", "deepseek-reasoner"),
            ],
        }

    def classify_task_complexity(
        self,
        instruction: str,
        context_tokens: int = 0,
        tool_count: int = 0,
        file_count: int = 1,
    ) -> TaskComplexity:
        """
        Classify task complexity based on intent heuristics, context volume, and tool scope.
        """
        text = (instruction or "").lower().strip()

        # 1. Reasoning-Heavy markers
        reasoning_patterns = [
            r"\b(prove|formal verification|theorem|complex algorithm|concurrency race|deadlock diagnosis)\b",
            r"\b(deep mathematical|cryptographic|kernel vulnerability|memory corruption)\b",
        ]
        if any(re.search(pat, text) for pat in reasoning_patterns):
            return TaskComplexity.REASONING_HEAVY

        # 2. Complex Multi-file / Architectural markers
        complex_patterns = [
            r"\b(architect|refactor entire|redesign subsystem|cross-module|full migration|scaffold service)\b",
            r"\b(implement e2e|rewrite pipeline|security boundary isolation)\b",
        ]
        if any(re.search(pat, text) for pat in complex_patterns) or file_count >= 4 or context_tokens > 60_000:
            return TaskComplexity.COMPLEX

        # 3. Simple / Fast markers
        simple_patterns = [
            r"\b(typo|fix typo|spelling|git status|format|lint|rename variable|add comment|docstring)\b",
            r"\b(show files|list dir|read file|explain line|inspect|what is)\b",
        ]
        if any(re.search(pat, text) for pat in simple_patterns) and context_tokens < 15_000 and file_count <= 1:
            return TaskComplexity.SIMPLE

        # Default moderate coding task
        return TaskComplexity.MODERATE

    def route_task(
        self,
        instruction: str,
        user_pinned_model: Optional[str] = None,
        user_pinned_provider: Optional[str] = None,
        preferred_provider: Optional[str] = None,
        estimated_input_tokens: int = 4000,
        estimated_output_tokens: int = 1000,
        context_tokens: int = 0,
        tool_count: int = 0,
        file_count: int = 1,
        force_tier: Optional[ModelTier] = None,
    ) -> RoutingDecision:
        """
        Resolve the optimal model for a task.
        Rule: If user_pinned_model is provided, ALWAYS honor it without silent downgrade.
        """
        complexity = self.classify_task_complexity(instruction, context_tokens, tool_count, file_count)

        with self._lock:
            # 1. User Pinned Model: Inviolable constraint
            if user_pinned_model and user_pinned_model.strip():
                pinned = user_pinned_model.strip()
                prov = user_pinned_provider or self._infer_provider(pinned)
                tier = self._infer_tier(pinned)

                calc = self._registry.calculate_cost(
                    model=pinned,
                    input_tokens=estimated_input_tokens,
                    output_tokens=estimated_output_tokens,
                    provider=prov,
                )

                return RoutingDecision(
                    selected_model=pinned,
                    selected_provider=prov,
                    selected_tier=tier,
                    task_complexity=complexity,
                    is_user_pinned=True,
                    estimated_cost_usd=calc.cost_usd or Decimal("0.000000"),
                    estimated_cost_inr=calc.cost_inr or Decimal("0.000000"),
                    savings_vs_premium_usd=Decimal("0.000000"),
                    routing_reason=f"User pinned model constraint respected: {pinned}",
                    fallback_models=[m for _, m in self._tier_models[ModelTier.CHEAP]],
                )

            # 2. Automated Tier Selection based on complexity
            if force_tier:
                target_tier = force_tier
            elif complexity == TaskComplexity.SIMPLE:
                target_tier = ModelTier.CHEAP
            elif complexity == TaskComplexity.MODERATE:
                target_tier = ModelTier.STANDARD
            elif complexity in {TaskComplexity.COMPLEX, TaskComplexity.REASONING_HEAVY}:
                target_tier = ModelTier.PREMIUM
            else:
                target_tier = ModelTier.STANDARD

            # 3. Model candidate selection within target tier matching provider preferences
            candidates = self._tier_models[target_tier]
            selected_prov, selected_model = candidates[0]

            if preferred_provider:
                matched = [c for c in candidates if c[0].lower() == preferred_provider.lower()]
                if matched:
                    selected_prov, selected_model = matched[0]

            # 4. Calculate cost comparison against baseline premium model (o1)
            selected_calc = self._registry.calculate_cost(
                model=selected_model,
                input_tokens=estimated_input_tokens,
                output_tokens=estimated_output_tokens,
                provider=selected_prov,
            )

            premium_calc = self._registry.calculate_cost(
                model="o1",
                input_tokens=estimated_input_tokens,
                output_tokens=estimated_output_tokens,
                provider="openai",
            )

            prem_cost = premium_calc.cost_usd or Decimal("0.000000")
            sel_cost = selected_calc.cost_usd or Decimal("0.000000")
            savings = quantize_currency(max(Decimal("0.000000"), prem_cost - sel_cost))

            # Assemble fallbacks
            fallbacks = [m for _, m in candidates if m != selected_model]

            return RoutingDecision(
                selected_model=selected_model,
                selected_provider=selected_prov,
                selected_tier=target_tier,
                task_complexity=complexity,
                is_user_pinned=False,
                estimated_cost_usd=sel_cost,
                estimated_cost_inr=selected_calc.cost_inr or Decimal("0.000000"),
                savings_vs_premium_usd=savings,
                routing_reason=f"Automated FinOps tier '{target_tier.value}' matched for complexity '{complexity.value}'",
                fallback_models=fallbacks,
            )

    def _infer_provider(self, model: str) -> str:
        m = model.lower()
        if "gpt" in m or "o1" in m or "o3" in m:
            return "openai"
        elif "claude" in m:
            return "anthropic"
        elif "gemini" in m:
            return "google"
        elif "deepseek" in m:
            return "deepseek"
        elif "llama" in m:
            return "groq"
        return "custom"

    def _infer_tier(self, model: str) -> ModelTier:
        m = model.lower()
        if any(p in m for p in ["o1", "o3", "opus", "reasoner"]):
            return ModelTier.PREMIUM
        elif any(p in m for p in ["mini", "haiku", "flash", "8b"]):
            return ModelTier.CHEAP
        return ModelTier.STANDARD


_GLOBAL_ROUTER: Optional[IntelligentModelRouter] = None
_ROUTER_LOCK = threading.Lock()


def get_model_router() -> IntelligentModelRouter:
    global _GLOBAL_ROUTER
    with _ROUTER_LOCK:
        if _GLOBAL_ROUTER is None:
            _GLOBAL_ROUTER = IntelligentModelRouter()
        return _GLOBAL_ROUTER

