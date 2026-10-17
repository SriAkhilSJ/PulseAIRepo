"""
Permission config — OpenCode's human-in-the-loop rule table, adapted.

Upstream (`packages/core/src/permission.ts` + the permissions docs):
every tool call asserts (action, resources); a ruleset of
(action-pattern, resource-pattern, effect) decides allow / ask /
deny, LAST matching rule wins; if any resource denies, the call is
denied; else if any asks, the human is asked; else it runs. The
"always" verdicts a human gives join the ruleset as session grants
(ApprovalQueue) and outrank config asks.

Crusor keeps that evaluation verbatim and layers it OVER the
SafetyGuard, which stays the hard floor: a config "allow" can never
silence a guard ask (secrets, unrestorable files, dangerous
commands), and a config "deny" blocks even calls the guard likes.

Config files (later files win; inside a file, later rules win):

    ~/.crusorai/settings.json
    <workspace>/.crusorai/settings.json

Shape mirrors OpenCode's `permission` config, plus per-agent
overrides under `agent.<name>.permission` (the main agent is
"build"; sub-agents key by their mode — research, code, review…):

    {
      "permission": {
        "*": "ask",
        "bash": { "*": "ask", "git *": "allow", "rm *": "deny" },
        "edit": { "*": "deny", "src/**": "allow" }
      },
      "agent": { "review": { "permission": { "edit": "deny" } } }
    }

Actions: read, edit, glob, grep, list, bash, task, skill, question,
webfetch, websearch, session_search, doom_loop, external_directory —
plus any raw tool name. `question`, `websearch` and `doom_loop` take
a plain action string only (upstream's action-only rule).

Built-in defaults (upstream): everything allows, except
`doom_loop` and `external_directory`, which ask, and reads of
`.env` / `.env.*`, which are denied (`*.env.example` allowed).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

Rule = tuple[str, str, str]  # (action pattern, resource pattern, effect)

_EFFECTS = {"allow", "ask", "deny"}

_BASE_RULES: tuple[Rule, ...] = (
    ("read", "*.env", "deny"),
    ("read", "*.env.*", "deny"),
    ("read", "*.env.example", "allow"),
    ("doom_loop", "*", "ask"),
    ("external_directory", "*", "ask"),
)

_SETTINGS_CACHE: dict[str, tuple[int, dict]] = {}


def wildcard_match(pattern: str, value: str) -> bool:
    """Upstream Wildcard: `*` any run (slashes included), `?` one char."""
    regex = "".join(
        ".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
        for ch in pattern
    )
    return re.fullmatch(regex, value, flags=re.DOTALL) is not None


def evaluate(action: str, resource: str, rules: list[Rule]) -> str:
    """Last matching rule wins; no match defaults to allow (the
    SafetyGuard underneath is the floor, config only tightens)."""
    winner = "allow"
    for rule_action, rule_resource, effect in rules:
        if wildcard_match(rule_action, action) and wildcard_match(rule_resource, resource):
            winner = effect
    return winner


def effect_for(action: str, resources: list[str], rules: list[Rule]) -> str:
    """Upstream aggregation: any deny denies, else any ask asks."""
    effects = [evaluate(action, resource or "*", rules) for resource in (resources or ["*"])]
    if "deny" in effects:
        return "deny"
    if "ask" in effects:
        return "ask"
    return "allow"


def _rules_from_info(info: Any) -> list[Rule]:
    """OpenCode PermissionConfig Info: a bare action string, or
    {action: action | {pattern: action}} (key order preserved)."""
    rules: list[Rule] = []
    if isinstance(info, str):
        if info in _EFFECTS:
            rules.append(("*", "*", info))
        return rules
    if not isinstance(info, dict):
        return rules
    for action, rule in info.items():
        if isinstance(rule, str):
            if rule in _EFFECTS:
                rules.append((str(action), "*", rule))
        elif isinstance(rule, dict):
            for pattern, effect in rule.items():
                if effect in _EFFECTS:
                    rules.append((str(action), str(pattern), str(effect)))
    return rules


def _read_settings(path: Path) -> dict:
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = str(path)
    cached = _SETTINGS_CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _SETTINGS_CACHE[key] = (stat.st_mtime_ns, data)
    return data


def _settings_paths(workspace: str) -> list[Path]:
    home = os.environ.get("CRUSORAI_HOME", "").strip()
    root = Path(home) if home else Path.home() / ".crusorai"
    paths = [root / "settings.json"]
    if workspace:
        paths.append(Path(workspace) / ".crusorai" / "settings.json")
    return paths


def load_permission_rules(workspace: str, agent: str = "") -> list[Rule]:
    """Base defaults, then global config, then workspace config;
    per-agent sections ride after their file's global section."""
    rules: list[Rule] = list(_BASE_RULES)
    for path in _settings_paths(workspace):
        data = _read_settings(path)
        rules.extend(_rules_from_info(data.get("permission")))
        if agent:
            agent_cfg = (data.get("agent") or {}).get(agent)
            if isinstance(agent_cfg, dict):
                rules.extend(_rules_from_info(agent_cfg.get("permission")))
    return rules


_SAVED_FILE = "permissions-saved.json"


def _saved_path(workspace: str) -> Path | None:
    if not workspace:
        return None
    return Path(workspace) / ".crusorai" / _SAVED_FILE


def _read_saved(path: Path) -> list[dict]:
    """The saved file is a JSON list; shares the mtime cache."""
    try:
        stat = path.stat()
    except OSError:
        return []
    key = str(path)
    cached = _SETTINGS_CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns:
        data = cached[1]
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        _SETTINGS_CACHE[key] = (stat.st_mtime_ns, data)  # type: ignore[assignment]
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def saved_rules(workspace: str) -> list[Rule]:
    """Upstream PermissionSaved: "always" verdicts persist PER
    PROJECT as allow rules, evaluated after the config rules. They
    release a config ASK; they never release a config DENY (the
    caller checks config deny first, upstream's denied())."""
    path = _saved_path(workspace)
    if path is None:
        return []
    rules: list[Rule] = []
    for row in _read_saved(path):
        action = str(row.get("action") or "")
        resource = str(row.get("resource") or "")
        if action and resource:
            rules.append((action, resource, "allow"))
    return rules


def save_grant(workspace: str, action: str, resources: list[str]) -> None:
    """Persist an "always" verdict (upstream PermissionSaved.add)."""
    path = _saved_path(workspace)
    if path is None or not action:
        return
    rows = _read_saved(path)
    have = {
        (str(r.get("action") or ""), str(r.get("resource") or "")) for r in rows
    }
    changed = False
    for resource in resources or ["*"]:
        key = (action, str(resource or "*"))
        if key not in have:
            rows.append({"action": key[0], "resource": key[1]})
            have.add(key)
            changed = True
    if not changed:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        _SETTINGS_CACHE.pop(str(path), None)
    except OSError:
        pass


def saved_allows(action: str, resources: list[str], saved: list[Rule]) -> bool:
    """Does a saved pattern actually MATCH this call? (evaluate()'s
    default is allow, so "allowed with saved appended" would wave
    through everything — a match must exist, the field-caught class
    where a grant for notes.py waved through other.py.)"""
    return any(
        wildcard_match(rule_action, action) and wildcard_match(rule_resource, resource or "*")
        for rule_action, rule_resource, _effect in saved
        for resource in (resources or ["*"])
    )


def saved_releases(workspace: str, tool_name: str, args: dict) -> bool:
    """Would a persisted "always" pattern allow this call? Config deny
    on the same (action, resources) still wins (upstream precedence)."""
    action, resources = tool_action_resources(tool_name, args or {})
    rules = load_permission_rules(workspace, "")
    if effect_for(action, resources, rules) == "deny":
        return False
    return saved_allows(action, resources, saved_rules(workspace))


def _first_str(args: dict, *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return ""


def tool_action_resources(tool_name: str, args: dict | None) -> tuple[str, list[str]]:
    """Map a Crusor tool call to its OpenCode-style (action, resources)."""
    args = args or {}
    name = tool_name or ""
    if name == "read_file":
        return "read", [_first_str(args, "path", "file_path")]
    if name in ("write_file", "edit_file"):
        return "edit", [_first_str(args, "path", "file_path")]
    if name == "copy_file":
        return "edit", [r for r in (_first_str(args, "src"), _first_str(args, "dst", "path")) if r]
    if name == "list_files":
        return "list", [_first_str(args, "path") or "."]
    if name == "search_files":
        return "glob", [_first_str(args, "pattern", "query")]
    if name == "search_code":
        return "grep", [_first_str(args, "pattern", "query")]
    if name == "session_search":
        return "session_search", [_first_str(args, "query")]
    if name in ("run_terminal", "start_terminal", "terminal"):
        return "bash", [_first_str(args, "command", "cmd")]
    if name == "execute_code":
        return "bash", [_first_str(args, "code", "command")]
    if name in ("delegate_to_subagent", "delegate_to_subagent_batch"):
        return "task", [_first_str(args, "subagent_type", "mode", "agent")]
    if name in ("web_fetch", "web_extract"):
        return "webfetch", [_first_str(args, "url", "urls")]
    if name == "web_search":
        return "websearch", []
    if name in ("skills_list", "skill_view", "skill_manage", "hub_search", "hub_install"):
        return "skill", [_first_str(args, "name", "skill", "query")]
    if name in ("clarify", "ask_user"):
        return "question", []
    return name, [_first_str(args, "path", "file_path", "command", "query", "url", "target")]
