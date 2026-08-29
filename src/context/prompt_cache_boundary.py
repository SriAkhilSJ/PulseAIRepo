"""Prompt-cache boundary — registry of stable prefixes (Hermes parity)."""
from __future__ import annotations
from collections import OrderedDict

_MAX_ENTRIES = 32
_registry: OrderedDict[str, None] = OrderedDict()

def register_stable_prefix(prefix: str) -> None:
    if not prefix: return
    _registry[prefix] = None
    _registry.move_to_end(prefix)
    while len(_registry) > _MAX_ENTRIES:
        _registry.popitem(last=False)

def find_stable_prefix(content: str) -> str:
    best = ""
    for p in list(_registry.keys()):
        if content.startswith(p) and len(p) > len(best):
            best = p
            _registry.move_to_end(p)
    return best
