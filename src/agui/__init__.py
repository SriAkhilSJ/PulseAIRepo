"""AG-UI edge for CrusorAI (AGUI_A2UI_PLAN.md Phase 1).

Desktop keeps Bridge Protocol v2 internally; this package is the
translation layer for AG-UI consumers at the edge: event mapping
(`mapping`) and the endpoint bind guard (`bind`).
"""
from src.agui.bind import BindDecision, resolve_bind
from src.agui.mapping import V2ToAguiTranslator, interrupt_resume_to_v2

__all__ = [
    "BindDecision",
    "V2ToAguiTranslator",
    "interrupt_resume_to_v2",
    "resolve_bind",
]
