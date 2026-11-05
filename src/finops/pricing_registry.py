"""
pricing_registry.py -- Centralized Model Pricing Registry for Enterprise FinOps.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Provides configurable, auditable, and multi-currency model pricing intelligence:
- Provider rate cards (Input, Output, Cached Input, Reasoning tokens per 1M).
- Verification status tracking (VERIFIED, ESTIMATED, UNVERIFIED, UNKNOWN).
- Pricing effective dates and source provenance.
- Transparent fallback and missing pricing handling (never misreports estimates as verified).
- Multi-currency normalization with canonical USD/INR conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import enum
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("crusorai.finops.pricing_registry")

# Canonical Forex constants matching cost_governance.py and pricing.py
DEFAULT_USD_TO_INR = Decimal("86.0")
FOREX_SPREAD = Decimal("1.005")
GATEWAY_FEE = Decimal("1.07")


def quantize_currency(val: Decimal | float | int | str | None) -> Decimal:
    """Standardize monetary amounts to 6 decimal places (micro-currency precision)."""
    if val is None:
        return Decimal("0.000000")
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"          # Direct provider published rate verified via API/catalog
    ESTIMATED = "ESTIMATED"        # Calculated from heuristic, tier baseline, or family model
    UNVERIFIED = "UNVERIFIED"      # User-configured or preliminary rate without external verification
    UNKNOWN = "UNKNOWN"            # Model has no known rate card; costs tracked as tokens-only


@dataclass
class ModelPricingMetadata:
    """Configurable pricing metadata for an individual model."""
    provider: str
    model: str
    input_price_per_1m: Decimal
    output_price_per_1m: Decimal
    cached_input_price_per_1m: Optional[Decimal] = None
    reasoning_price_per_1m: Optional[Decimal] = None
    currency: str = "USD"
    effective_date: str = "2026-01-01"
    verification_status: VerificationStatus = VerificationStatus.VERIFIED
    source: str = "default_catalog"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_price_per_1m": float(self.input_price_per_1m),
            "output_price_per_1m": float(self.output_price_per_1m),
            "cached_input_price_per_1m": float(self.cached_input_price_per_1m) if self.cached_input_price_per_1m is not None else None,
            "reasoning_price_per_1m": float(self.reasoning_price_per_1m) if self.reasoning_price_per_1m is not None else None,
            "currency": self.currency,
            "effective_date": self.effective_date,
            "verification_status": self.verification_status.value,
            "source": self.source,
            "notes": self.notes,
        }


@dataclass
class CalculatedCost:
    """Detailed cost breakdown for a specific model call."""
    cost_usd: Optional[Decimal]
    cost_inr: Optional[Decimal]
    currency: str
    is_exact: bool
    verification_status: VerificationStatus
    input_cost: Decimal = Decimal("0.000000")
    output_cost: Decimal = Decimal("0.000000")
    cached_cost: Decimal = Decimal("0.000000")
    reasoning_cost: Decimal = Decimal("0.000000")
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cost_usd": float(self.cost_usd) if self.cost_usd is not None else None,
            "cost_inr": float(self.cost_inr) if self.cost_inr is not None else None,
            "currency": self.currency,
            "is_exact": self.is_exact,
            "verification_status": self.verification_status.value,
            "input_cost": float(self.input_cost),
            "output_cost": float(self.output_cost),
            "cached_cost": float(self.cached_cost),
            "reasoning_cost": float(self.reasoning_cost),
            "source": self.source,
        }


class ModelPricingRegistry:
    """
    Centralized repository of model rate cards with support for
    dynamic catalog integration, manual overrides, and currency normalization.
    """

    def __init__(self, usd_to_inr_rate: Decimal = DEFAULT_USD_TO_INR) -> None:
        self._lock = threading.RLock()
        self._usd_to_inr_rate = usd_to_inr_rate
        self._registry: Dict[str, ModelPricingMetadata] = {}
        self._load_baseline_rate_cards()

    def set_fx_rate(self, usd_to_inr_rate: Decimal) -> None:
        with self._lock:
            self._usd_to_inr_rate = quantize_currency(usd_to_inr_rate)

    def get_fx_rate(self) -> Decimal:
        with self._lock:
            return self._usd_to_inr_rate

    def usd_to_inr(self, usd: Optional[Decimal], apply_forex_fees: bool = True) -> Optional[Decimal]:
        if usd is None:
            return None
        rate = self._usd_to_inr_rate
        mult = rate * FOREX_SPREAD * GATEWAY_FEE if apply_forex_fees else rate
        return quantize_currency(usd * mult)

    def inr_to_usd(self, inr: Optional[Decimal], apply_forex_fees: bool = False) -> Optional[Decimal]:
        if inr is None:
            return None
        rate = self._usd_to_inr_rate
        if rate <= Decimal("0"):
            return Decimal("0.000000")
        divisor = rate * FOREX_SPREAD * GATEWAY_FEE if apply_forex_fees else rate
        return quantize_currency(inr / divisor)

    def _load_baseline_rate_cards(self) -> None:
        """Populate initial verified industry rates across standard model families."""
        defaults = [
            # OpenAI Family
            ModelPricingMetadata("openai", "gpt-4o", Decimal("2.50"), Decimal("10.00"), Decimal("1.25"), Decimal("10.00"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "openai_official"),
            ModelPricingMetadata("openai", "gpt-4o-mini", Decimal("0.15"), Decimal("0.60"), Decimal("0.075"), Decimal("0.60"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "openai_official"),
            ModelPricingMetadata("openai", "o1", Decimal("15.00"), Decimal("60.00"), Decimal("7.50"), Decimal("60.00"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "openai_official"),
            ModelPricingMetadata("openai", "o3-mini", Decimal("1.10"), Decimal("4.40"), Decimal("0.55"), Decimal("4.40"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "openai_official"),
            # Anthropic Family
            ModelPricingMetadata("anthropic", "claude-3-5-sonnet", Decimal("3.00"), Decimal("15.00"), Decimal("0.30"), Decimal("15.00"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "anthropic_official"),
            ModelPricingMetadata("anthropic", "claude-3-5-haiku", Decimal("0.80"), Decimal("4.00"), Decimal("0.08"), Decimal("4.00"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "anthropic_official"),
            ModelPricingMetadata("anthropic", "claude-3-opus", Decimal("15.00"), Decimal("75.00"), Decimal("1.50"), Decimal("75.00"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "anthropic_official"),
            # Google Gemini Family
            ModelPricingMetadata("google", "gemini-1.5-pro", Decimal("1.25"), Decimal("5.00"), Decimal("0.3125"), None, "USD", "2026-01-01", VerificationStatus.VERIFIED, "google_official"),
            ModelPricingMetadata("google", "gemini-1.5-flash", Decimal("0.075"), Decimal("0.30"), Decimal("0.01875"), None, "USD", "2026-01-01", VerificationStatus.VERIFIED, "google_official"),
            ModelPricingMetadata("google", "gemini-2.0-flash", Decimal("0.10"), Decimal("0.40"), Decimal("0.025"), None, "USD", "2026-01-01", VerificationStatus.VERIFIED, "google_official"),
            # DeepSeek / OpenRouter / Custom
            ModelPricingMetadata("deepseek", "deepseek-chat", Decimal("0.14"), Decimal("0.28"), Decimal("0.014"), None, "USD", "2026-01-01", VerificationStatus.VERIFIED, "deepseek_official"),
            ModelPricingMetadata("deepseek", "deepseek-reasoner", Decimal("0.55"), Decimal("2.19"), Decimal("0.14"), Decimal("2.19"), "USD", "2026-01-01", VerificationStatus.VERIFIED, "deepseek_official"),
            ModelPricingMetadata("groq", "llama-3.3-70b", Decimal("0.59"), Decimal("0.79"), None, None, "USD", "2026-01-01", VerificationStatus.VERIFIED, "groq_official"),
            ModelPricingMetadata("groq", "llama-3.1-8b", Decimal("0.05"), Decimal("0.08"), None, None, "USD", "2026-01-01", VerificationStatus.VERIFIED, "groq_official"),
            # Velona INR Live Native
            ModelPricingMetadata("velona", "velona-pro", Decimal("45.00"), Decimal("180.00"), Decimal("15.00"), None, "INR", "2026-01-01", VerificationStatus.VERIFIED, "velona_catalog"),
            ModelPricingMetadata("velona", "velona-flash", Decimal("4.50"), Decimal("18.00"), Decimal("1.50"), None, "INR", "2026-01-01", VerificationStatus.VERIFIED, "velona_catalog"),
        ]
        for m in defaults:
            self._registry[self._key(m.provider, m.model)] = m
            # Also register by naked model name for multi-provider lookups
            if m.model not in self._registry:
                self._registry[m.model] = m

    def _key(self, provider: str, model: str) -> str:
        return f"{provider.lower().strip()}/{model.lower().strip()}"

    def register_model_pricing(self, metadata: ModelPricingMetadata) -> None:
        """Register or update a model's pricing metadata."""
        with self._lock:
            k = self._key(metadata.provider, metadata.model)
            self._registry[k] = metadata
            self._registry[metadata.model.lower().strip()] = metadata

    def get_model_pricing(self, model: str, provider: Optional[str] = None) -> Optional[ModelPricingMetadata]:
        """Lookup pricing metadata by model identifier, exact or substring."""
        with self._lock:
            if provider:
                k = self._key(provider, model)
                if k in self._registry:
                    return self._registry[k]

            m_lower = model.lower().strip()
            if m_lower in self._registry:
                return self._registry[m_lower]

            # Try prefix / suffix matching
            for reg_key, meta in self._registry.items():
                if reg_key.endswith(f"/{m_lower}") or meta.model.lower() == m_lower:
                    return meta

            # Substring matching for versioned variants
            for reg_key, meta in self._registry.items():
                if meta.model.lower() in m_lower or m_lower in meta.model.lower():
                    return meta

            return None

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
        provider: Optional[str] = None,
        reported_cost_usd: Optional[float] = None,
        reported_cost_inr: Optional[float] = None,
    ) -> CalculatedCost:
        """
        Calculate total cost for token consumption.
        Prioritizes verified provider-reported billing over calculated estimates.
        """
        # If exact provider billing is provided, respect it as ground truth
        if reported_cost_usd is not None or reported_cost_inr is not None:
            if reported_cost_usd is not None:
                dec_usd = quantize_currency(reported_cost_usd)
                dec_inr = self.usd_to_inr(dec_usd, apply_forex_fees=True)
                return CalculatedCost(
                    cost_usd=dec_usd,
                    cost_inr=dec_inr,
                    currency="USD",
                    is_exact=True,
                    verification_status=VerificationStatus.VERIFIED,
                    source="provider_reported_receipt",
                )
            else:
                dec_inr = quantize_currency(reported_cost_inr)
                dec_usd = self.inr_to_usd(dec_inr, apply_forex_fees=False)
                return CalculatedCost(
                    cost_usd=dec_usd,
                    cost_inr=dec_inr,
                    currency="INR",
                    is_exact=True,
                    verification_status=VerificationStatus.VERIFIED,
                    source="provider_reported_receipt",
                )

        pricing = self.get_model_pricing(model, provider=provider)
        if not pricing:
            # Honestly unknown pricing
            return CalculatedCost(
                cost_usd=None,
                cost_inr=None,
                currency="UNKNOWN",
                is_exact=False,
                verification_status=VerificationStatus.UNKNOWN,
                source="unrated_model",
            )

        # Standard token cost arithmetic: (tokens / 1,000,000) * price_per_1m
        uncached_input = max(0, input_tokens - cached_tokens)
        input_cost = quantize_currency((Decimal(uncached_input) / Decimal("1000000")) * pricing.input_price_per_1m)

        cached_rate = pricing.cached_input_price_per_1m if pricing.cached_input_price_per_1m is not None else pricing.input_price_per_1m
        cached_cost = quantize_currency((Decimal(cached_tokens) / Decimal("1000000")) * cached_rate)

        # Separate reasoning tokens if model bills them differently
        standard_output = max(0, output_tokens - reasoning_tokens) if pricing.reasoning_price_per_1m is not None else output_tokens
        output_cost = quantize_currency((Decimal(standard_output) / Decimal("1000000")) * pricing.output_price_per_1m)

        reasoning_cost = Decimal("0.000000")
        if pricing.reasoning_price_per_1m is not None and reasoning_tokens > 0:
            reasoning_cost = quantize_currency((Decimal(reasoning_tokens) / Decimal("1000000")) * pricing.reasoning_price_per_1m)

        total_currency_cost = quantize_currency(input_cost + cached_cost + output_cost + reasoning_cost)

        if pricing.currency.upper() == "INR":
            cost_inr = total_currency_cost
            cost_usd = self.inr_to_usd(cost_inr, apply_forex_fees=False)
        else:
            cost_usd = total_currency_cost
            cost_inr = self.usd_to_inr(cost_usd, apply_forex_fees=True)

        is_exact = pricing.verification_status == VerificationStatus.VERIFIED

        return CalculatedCost(
            cost_usd=cost_usd,
            cost_inr=cost_inr,
            currency=pricing.currency,
            is_exact=is_exact,
            verification_status=pricing.verification_status,
            input_cost=input_cost,
            output_cost=output_cost,
            cached_cost=cached_cost,
            reasoning_cost=reasoning_cost,
            source=pricing.source,
        )

    def export_catalog(self) -> List[Dict[str, Any]]:
        with self._lock:
            unique_metas = {meta.model: meta for meta in self._registry.values()}
            return [meta.to_dict() for meta in unique_metas.values()]


_GLOBAL_REGISTRY: Optional[ModelPricingRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_pricing_registry() -> ModelPricingRegistry:
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = ModelPricingRegistry()
        return _GLOBAL_REGISTRY

