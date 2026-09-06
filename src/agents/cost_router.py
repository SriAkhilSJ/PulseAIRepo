
"""
Cost-Aware Router for PulseCodeAI
==================================
Routes tasks to the cheapest adequate model instead of always
using the most expensive one.
Simple tasks → Fast/cheap models
Complex tasks → Powerful models

What this changes:
- Cuts API costs by 40-70% on simple tasks
- Automatically upgrades to powerful models when needed
- Falls back safely if the cheap model isn't configured
"""
import os
from typing import Literal
from src.config.settings import LLM_PROVIDER, LLM_MODEL

class CostRouter:
    """
    Analyzes task complexity and routes to the optimal model.
    Falls back to the user's default provider if the target isn't configured.
    """
    def __init__(self):
        self._last_route = None
        self._forced_tier = None
        self._cheap_count = 0
        self._standard_count = 0
        self._premium_count = 0
        # Field 2026-09-06 (owner: "why does the model read Groq API when the
        # agent runs through custom api?"): a PRESENT-but-invalid key put
        # groq in the cheap tier, and every cheap-tier turn paid a 401 round
        # trip before failover. The router now keeps its own dead set: once
        # auth fails, ROUTE selection skips the pair for the process life —
        # not just the request path.
        self._dead: set[tuple[str, str]] = set()
        self._build_tiers()

    def mark_dead(self, provider: str, model: str) -> None:
        """Retire a (provider, model) pair from route selection after an
        authentication failure. In-process only: a fixed key should get a
        fresh shot on the next app start."""
        self._dead.add((str(provider or ""), str(model or "")))

    def _offload_enabled(self) -> bool:
        raw = (os.environ.get("PULSEAI_CHEAP_TIER", "") or "").strip().lower()
        return raw not in {"off", "false", "0", "no"}

    def _build_tiers(self):
        """
        Build available tiers from the user's configuration.
        Only adds alternative providers if their API keys are present.
        """
        # Default: everything falls back to what the user already set up
        self.tiers = {
            "cheap": {"provider": LLM_PROVIDER, "model": LLM_MODEL},
            "standard": {"provider": LLM_PROVIDER, "model": LLM_MODEL},
            "premium": {"provider": LLM_PROVIDER, "model": LLM_MODEL},
        }

        # Try to add Groq as cheap tier (if available and different from
        # default; PULSEAI_CHEAP_TIER=off disables the offload entirely —
        # routing knobs are configuration, never hardcoded).
        try:
            if not self._offload_enabled():
                print("[cost_router] cheap-tier offload disabled (PULSEAI_CHEAP_TIER=off)", flush=True)
            else:
                from src.config.settings import GROQ_API_KEY
                if GROQ_API_KEY and LLM_PROVIDER != "groq":
                    self.tiers["cheap"] = {
                        "provider": "groq",
                        "model": "llama-3.1-8b-instant",
                    }
        except Exception:
            pass

        # Try to add OpenAI as premium tier (if available and different from default)
        try:
            from src.config.settings import OPENAI_API_KEY
            if OPENAI_API_KEY and LLM_PROVIDER != "openai":
                self.tiers["premium"] = {
                    "provider": "openai",
                    "model": "gpt-4o",
                }
        except Exception:
            pass

    def classify(self, task: str, current_plan: list | None = None) -> Literal["cheap", "standard", "premium"]:
        """
        Classify task complexity for routing.
        """
        if self._forced_tier:
            return self._forced_tier

        task_lower = task.lower()
        # Premium signals: architecture, complex reasoning, debugging
        premium_signals = [
            "architecture", "design", "refactor", "redesign", "restructure",
            "migrate", "microservice", "database schema", "authentication",
            "authorization", "security audit", "performance optimization",
            "debug", "fix", "troubleshoot", "complex", "integrate",
            "multi-step", "plan", "review", "audit",
        ]

        # Cheap signals: simple lookups, explanations, trivial edits
        cheap_signals = [
            "what is", "how do i", "explain", "show me", "list ",
            "find ", "where is", "hello", "hi ", "count ", "sum ",
            "print ", "create a simple", "quick ", "just ", "tell me",
        ]

        if any(s in task_lower for s in premium_signals):
            return "premium"

        if any(s in task_lower for s in cheap_signals) and len(task) < 120:
            return "cheap"

        # Multi-step plans suggest standard or premium
        if current_plan and len(current_plan) > 5:
            return "premium"

        return "standard"

    def route(self, task: str = "", current_plan: list | None = None) -> tuple[str, str]:
        """
        Return (provider, model) for the given task.
        Falls back to default if the target provider fails.
        """
        tier = self.classify(task, current_plan)
        
        # Increment counters
        if tier == "cheap": self._cheap_count += 1
        elif tier == "standard": self._standard_count += 1
        elif tier == "premium": self._premium_count += 1

        result = (self.tiers[tier]["provider"], self.tiers[tier]["model"])
        failed_over = False
        if result in self._dead:
            # Auth-dead pairs never get a doomed request at route time; the
            # default tier answers instead (hermes circuit-breaker spirit —
            # the breaker lives at ROUTE selection, not just the request).
            result = (LLM_PROVIDER, LLM_MODEL)
            failed_over = True
        self._last_route = {
            "tier": tier,
            "provider": result[0],
            "model": result[1],
            "task_preview": task[:60],
            **({"failed_over": True} if failed_over else {}),
        }
        return result

    def get_last_route_info(self) -> str:
        if not self._last_route:
            return "No routing decision yet."
        r = self._last_route
        return (
            f"Last route: {r['tier'].upper()} tier "
            f"→ {r['provider']} / {r['model']}"
        )

    def override_tier(self, tier: Literal["cheap", "standard", "premium"]):
        self._forced_tier = tier

    def clear_override(self):
        self._forced_tier = None

# Global singleton — shared across the agent
cost_router = CostRouter()
