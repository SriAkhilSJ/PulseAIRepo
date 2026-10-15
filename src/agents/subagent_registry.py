"""Sub-agent registry (OpenCode parity: an OPEN agent registry).

OpenCode's task tool spawns *agents*, not a closed mode enum: built-in
agents plus user-defined ones, each with its own description, prompt,
model, and permissions, listed dynamically in the tool description.
Crusor's version: the four built-in modes (research / code / test /
review, capabilities from ``MODE_CAPABILITIES``) plus custom agents
defined as Markdown files with YAML frontmatter:

- ``<workspace>/.crusorai/agents/<name>.md`` (project agents)
- ``~/.crusorai/agents/<name>.md`` (global agents)

Frontmatter (all optional except that the body is the prompt)::

    ---
    description: Release notes writer
    base: code                 # built-in whose defaults apply
    capabilities: workspace_read, workspace_write
    model: some-cheaper-model  # optional per-agent model
    ---

    You are a release-notes specialist. ...

A custom agent SHADOWS a built-in of the same name (OpenCode allows
redefining built-ins). Spawning can be policy-gated with env:
``CRUSORAI_SUBAGENT_ALLOWED`` (comma list; when set, only these may
spawn) and ``CRUSORAI_SUBAGENT_DENIED`` (comma list; never spawn).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from src.agents.subagent_permissions import MODE_CAPABILITIES

BUILTIN_DESCRIPTIONS = {
    "research": "Read-only research: web + codebase search, reads, summarises. Never writes.",
    "code": "Coding specialist: reads, writes and edits files, runs commands, verifies.",
    "test": "Testing specialist: runs tests and commands, reports results. Minimal edits.",
    "review": "Code reviewer: reads and critiques. Never writes.",
}

_ALIASES = {"general": "code", "explore": "research", "build": "code", "plan": "research"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class AgentDef:
    name: str
    description: str
    capabilities: tuple[str, ...]
    base_mode: str  # one of the four built-ins (prompt persona + fallbacks)
    model: str | None = None
    prompt: str | None = None  # custom system prompt (replaces persona prefix)


def _builtin(name: str) -> AgentDef:
    return AgentDef(
        name=name,
        description=BUILTIN_DESCRIPTIONS[name],
        capabilities=tuple(MODE_CAPABILITIES[name]),
        base_mode=name,
    )


def _parse_agent_file(path: Path) -> AgentDef | None:
    name = path.stem.strip().lower()
    if not _NAME_RE.match(name):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    meta: dict = {}
    body = text.strip()
    if text.startswith("---"):
        try:
            import yaml

            _, front, body = text.split("---", 2)
            meta = yaml.safe_load(front) or {}
            body = body.strip()
        except Exception:
            meta, body = {}, text.strip()
    base = str(meta.get("base") or "code").strip().lower()
    if base not in MODE_CAPABILITIES:
        base = "code"
    raw_caps = meta.get("capabilities")
    if isinstance(raw_caps, str):
        caps = tuple(c.strip() for c in raw_caps.split(",") if c.strip())
    elif isinstance(raw_caps, (list, tuple)):
        caps = tuple(str(c).strip() for c in raw_caps if str(c).strip())
    else:
        caps = tuple(MODE_CAPABILITIES[base])
    return AgentDef(
        name=name,
        description=str(meta.get("description") or f"Custom agent ({base})")[:200],
        capabilities=caps,
        base_mode=base,
        model=(str(meta["model"]).strip() or None) if meta.get("model") else None,
        prompt=body or None,
    )


def _custom_agents(workspace: str | None) -> dict[str, AgentDef]:
    found: dict[str, AgentDef] = {}
    roots: list[Path] = [Path.home() / ".crusorai" / "agents"]
    if workspace:
        roots.append(Path(workspace) / ".crusorai" / "agents")
    for root in roots:  # workspace entries override global ones
        try:
            if not root.is_dir():
                continue
            for path in sorted(root.glob("*.md")):
                parsed = _parse_agent_file(path)
                if parsed:
                    found[parsed.name] = parsed
        except Exception:
            continue
    return found


def available_agents(workspace: str | None = None) -> list[AgentDef]:
    """Built-ins plus custom agents (custom shadows builtin by name)."""
    merged: dict[str, AgentDef] = {name: _builtin(name) for name in MODE_CAPABILITIES}
    merged.update(_custom_agents(workspace))
    return [merged[name] for name in sorted(merged)]


def resolve_agent(name: str | None, workspace: str | None = None) -> AgentDef | None:
    """Resolve a requested agent name (aliases included) to its def."""
    key = str(name or "").strip().lower()
    if not key:
        return None
    customs = _custom_agents(workspace)
    if key in customs:
        return customs[key]
    key = _ALIASES.get(key, key)
    if key in MODE_CAPABILITIES:
        return _builtin(key)
    return customs.get(key)


def denied_reason(name: str) -> str | None:
    """Spawn policy gate (OpenCode: a parent agent's permissions may deny
    specific subagents). Env-driven: an allow-list when set, a deny-list
    always honoured. Returns the human reason, or None when allowed."""
    key = str(name or "").strip().lower()
    denied = {part.strip().lower() for part in os.getenv("CRUSORAI_SUBAGENT_DENIED", "").split(",") if part.strip()}
    if key in denied:
        return f"spawning sub-agent '{key}' is denied by policy (CRUSORAI_SUBAGENT_DENIED)."
    allowed = {part.strip().lower() for part in os.getenv("CRUSORAI_SUBAGENT_ALLOWED", "").split(",") if part.strip()}
    if allowed and key not in allowed:
        return f"spawning sub-agent '{key}' is not in the allow-list (CRUSORAI_SUBAGENT_ALLOWED: {', '.join(sorted(allowed))})."
    return None
