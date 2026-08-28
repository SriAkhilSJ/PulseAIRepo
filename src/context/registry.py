"""
registry.py -- Pluggable Context Engine Registry for PulseAI.
============================================================

Supports selecting and loading different context engines (such as the default
PulseAI engine, Hermes-compatible ContextCompressor, LeanTail engine, or
third-party plugins such as Lossless Context Management / LCM).

Selection is configured via PULSEAI_CONTEXT_ENGINE env or config setting
(defaulting to "pulse").
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Type

from src.context.base import ContextEngineBase

log = logging.getLogger("pulseai.context.registry")

_REGISTRY: Dict[str, Callable[..., ContextEngineBase]] = {}


def register_context_engine(
    name: str,
    factory: Callable[..., ContextEngineBase] | Type[ContextEngineBase],
) -> None:
    """Register a context engine class or factory callable under a short name."""
    key = name.strip().lower()
    _REGISTRY[key] = factory
    log.debug("Registered context engine: %s", key)


def _ensure_defaults() -> None:
    if "pulse" not in _REGISTRY:
        from src.context.context_engine import ContextEngine
        _REGISTRY["pulse"] = ContextEngine
        _REGISTRY["compressor"] = ContextEngine
        _REGISTRY["lean"] = lambda **kw: ContextEngine(volatile_tail=True, **kw)


def get_context_engine_class(name: str) -> Optional[Callable[..., ContextEngineBase]]:
    """Retrieve registered context engine by name."""
    _ensure_defaults()
    return _REGISTRY.get(name.strip().lower())


def list_context_engines() -> List[str]:
    """Return all registered context engine names."""
    _ensure_defaults()
    return sorted(_REGISTRY.keys())


def create_context_engine(name: str = "pulse", **kwargs: Any) -> ContextEngineBase:
    """Instantiate a registered context engine. Defaults to 'pulse'."""
    _ensure_defaults()
    key = name.strip().lower()
    factory = _REGISTRY.get(key)
    if factory is None:
        log.warning("Context engine '%s' not found; falling back to 'pulse'", name)
        factory = _REGISTRY.get("pulse")
    if factory is None:
        from src.context.context_engine import ContextEngine
        return ContextEngine(**kwargs)
    return factory(**kwargs)
