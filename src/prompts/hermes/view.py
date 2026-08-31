"""``PulsePromptView`` — the Pulse backend that satisfies the Hermes prompt contract.

Upstream's prompt builders all take one argument, ``agent``, and read a fixed
set of attributes off it (``valid_tool_names``, ``model``, ``provider``,
``_memory_store``, ``load_soul_identity``, the cached-prompt slots, …). Pulse
has no ``AIAgent`` object: its equivalents are spread over
``src/config/settings``, ``src/tools/toolsets``, ``src/context/*`` and the
graph state. This module is the single seam that binds them, so the prompt
engine upstream-side stays byte-faithful and everything Pulse-specific lives
in ONE auditable place.

Nothing here builds prompt text; it only resolves inputs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def resolve_valid_tool_names(task: str = "", config: Any = None) -> Set[str]:
    """The session's tool surface — Pulse's narrow waist, not the whole registry.

    Hermes gates every guidance block on ``agent.valid_tool_names`` so a block
    can never advertise a tool the model cannot call. Pulse's equivalent of
    that resolution already exists (``src/tools/toolsets.py`` driven by
    ``runtime_profile``), so the prompt engine consumes it rather than keeping
    its own list: same gate, one source of truth.
    """
    names: List[str] = []
    try:  # pyrefly: ignore [missing-import]
        from src.agents.runtime_profile import resolve_runtime_profile
        from src.tools.toolsets import resolve_runtime_tool_names

        profile = resolve_runtime_profile(task or "", config)
        names = list(resolve_runtime_tool_names(profile, config))
    except Exception:
        try:  # pyrefly: ignore [missing-import]
            from src.tools.toolsets import all_known_tool_names

            names = list(all_known_tool_names())
        except Exception:
            names = []
    return {str(n) for n in names}


@dataclass
class PulsePromptView:
    """Attribute surface the ported prompt builders read.

    Field names intentionally match upstream's ``agent`` attributes: that is
    what lets ``system_prompt.py`` / ``context_files.py`` / ``skills_index.py``
    stay structural copies instead of rewrites.
    """

    # ── identity / persona slot ────────────────────────────────────────────
    identity: Optional[str] = None          # replaces DEFAULT_AGENT_IDENTITY when set
    load_soul_identity: bool = True
    soul_path: Optional[Path] = None

    # ── model surface ──────────────────────────────────────────────────────
    model: str = ""
    provider: str = ""
    platform: str = "ide"                    # Pulse surfaces: ide | cli | dashboard | bridge
    context_length: Optional[int] = None
    pass_session_id: bool = True
    session_id: str = ""

    # ── tool surface (drives every gate) ───────────────────────────────────
    valid_tool_names: Set[str] = field(default_factory=set)
    tools: List[Dict[str, Any]] = field(default_factory=list)

    # ── workspace ──────────────────────────────────────────────────────────
    cwd: Path = field(default_factory=Path.cwd)
    home: Optional[Path] = None
    skip_context_files: bool = False
    context_file_max_chars: Optional[int] = None

    # ── block gating (upstream config.yaml keys, Pulse env vars) ───────────
    task_completion_guidance: bool = True
    parallel_tool_call_guidance: bool = True
    execution_guidance: Any = "auto"          # "auto" | True | False | substring list
    memory_enabled: bool = False
    user_profile_enabled: bool = False
    steer_enabled: bool = True

    # ── backing stores the volatile tier renders ───────────────────────────
    memory_store: Any = None
    memory_manager: Any = None
    skill_manager: Any = None
    skills_enabled: bool = True
    skills_dir: Optional[Path] = None

    # ── per-platform prompt-hint overrides (replace / append / bare string) ─
    platform_hint_overrides: Dict[str, Any] = field(default_factory=dict)

    # ── status channel for user-visible warnings (truncation, degradation) ──
    status_sink: List[str] = field(default_factory=list)

    # ── prompt-cache slots (upstream caches these on the agent) ────────────
    _cached_system_prompt: Optional[str] = None
    _cached_system_prompt_static: Optional[str] = None
    _static_rebuild_failed_for: Optional[str] = None
    _use_prompt_caching: bool = True
    _plugin_system_prompt_sections_snapshot: Optional[tuple] = None
    _plugin_system_prompt_sections_previous: Optional[tuple] = None

    # ── compatibility shims for the upstream attribute names ──────────────
    @property
    def _task_completion_guidance(self) -> bool:
        return self.task_completion_guidance

    @property
    def _parallel_tool_call_guidance(self) -> bool:
        return self.parallel_tool_call_guidance

    @property
    def _memory_enabled(self) -> bool:
        return self.memory_enabled

    @property
    def _user_profile_enabled(self) -> bool:
        return self.user_profile_enabled

    @property
    def _memory_store(self) -> Any:
        return self.memory_store

    @property
    def _memory_manager(self) -> Any:
        return self.memory_manager

    @property
    def _platform_hint_overrides(self) -> Dict[str, Any]:
        return self.platform_hint_overrides

    def _emit_status(self, message: str) -> None:
        """Upstream's status channel; Pulse's is the bridge/dashboard receipt list."""
        if message:
            self.status_sink.append(message)

    @property
    def tools_dir(self) -> Optional[Path]:
        return self.skills_dir


def _settings() -> Any:
    try:  # pyrefly: ignore [missing-import]
        from src.config import settings

        return settings
    except Exception:
        return None


def pulse_home() -> Path:
    """Pulse's equivalent of ``HERMES_HOME`` — where SOUL.md / skills live."""
    raw = os.environ.get("PULSE_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    settings = _settings()
    candidate = getattr(settings, "PULSE_HOME", None)
    if candidate:
        return Path(str(candidate)).expanduser()
    return Path(__file__).resolve().parents[2]


def view_from_config(
    config: Any = None,
    state: Optional[Dict[str, Any]] = None,
    *,
    tools: Optional[Iterable[Any]] = None,
    task: str = "",
) -> PulsePromptView:
    """Build the view from Pulse's real runtime inputs (graph config + state).

    Defensive by design: this runs on the AG-UI path, where the caller may send
    only ``messages`` and none of the CLI/bridge configurables — the same trap
    that made ``config['configurable']['provider']`` a KeyError before the
    ``_cfg()`` helper landed. Everything falls back to settings.
    """
    configurable: Dict[str, Any] = {}
    if isinstance(config, dict):
        nested = config.get("configurable")
        configurable = dict(nested) if isinstance(nested, dict) else dict(config)
    state = state or {}
    settings = _settings()

    def cfg(key: str, default: Any = None) -> Any:
        if key in configurable and configurable[key] not in (None, ""):
            return configurable[key]
        if key in state and state[key] not in (None, ""):
            return state[key]
        if settings is not None and hasattr(settings, key.upper()):
            return getattr(settings, key.upper())
        return default

    model = str(cfg("model", getattr(settings, "LLM_MODEL", "")) or "")
    provider = str(cfg("provider", getattr(settings, "LLM_PROVIDER", "")) or "")

    workspace = str(cfg("workspace", "") or "")
    cwd = Path(workspace).expanduser() if workspace else Path.cwd()
    try:
        cwd = cwd.resolve()
    except Exception:
        pass

    context_length: Optional[int] = None
    try:  # pyrefly: ignore [missing-import]
        from src.context.model_budgets import model_window

        window = model_window(model)
        context_length = int(window) if isinstance(window, int) and window > 0 else None
    except Exception:
        context_length = None

    tool_names = resolve_valid_tool_names(task, config)
    bound_tools: List[Dict[str, Any]] = []
    for tool in tools or ():
        name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
        if name:
            bound_tools.append({"name": str(name)})
            tool_names.add(str(name))

    memory_store = None
    try:  # pyrefly: ignore [missing-import]
        from src.context.persistent_memory import PersistentMemoryWrapper

        memory_store = PersistentMemoryWrapper(None)
    except Exception:
        memory_store = None

    skill_manager = None
    try:  # pyrefly: ignore [missing-import]
        from src.agents.skill_manager import SkillManager

        skill_manager = SkillManager()
    except Exception:
        skill_manager = None

    home = pulse_home()
    return PulsePromptView(
        identity=str(cfg("persona", "") or "") or None,
        model=model,
        provider=provider,
        platform=str(cfg("surface", os.environ.get("PULSEAI_SURFACE", "ide")) or "ide"),
        context_length=context_length,
        session_id=str(cfg("thread_id", "") or cfg("session_id", "") or ""),
        valid_tool_names=tool_names,
        tools=bound_tools,
        cwd=cwd,
        home=home,
        soul_path=home / "SOUL.md",
        skip_context_files=bool(cfg("skip_context_files", False)),
        task_completion_guidance=_env_flag("PULSEAI_TASK_COMPLETION_GUIDANCE", True),
        parallel_tool_call_guidance=_env_flag("PULSEAI_PARALLEL_TOOL_GUIDANCE", True),
        execution_guidance=os.environ.get("PULSEAI_EXECUTION_GUIDANCE", "auto") or "auto",
        memory_enabled=_env_flag("PULSEAI_MEMORY_GUIDANCE", False),
        user_profile_enabled=_env_flag("PULSEAI_USER_PROFILE_GUIDANCE", False),
        steer_enabled=_env_flag("PULSEAI_STEER_NOTE", True),
        memory_store=memory_store,
        skill_manager=skill_manager,
        skills_enabled=_env_flag("PULSEAI_SKILLS_INDEX", True),
        skills_dir=home / "skills",
        platform_hint_overrides={},
    )


__all__ = [
    "PulsePromptView",
    "pulse_home",
    "resolve_valid_tool_names",
    "view_from_config",
]
