"""
Skill Manager for CrusorCodeAI
============================
Teach the agent reusable patterns and preferences.
Skills are automatically injected into context when relevant.

Examples:
- "Always use type hints"
- "Prefer FastAPI over Flask"
- "Write Google-style docstrings"
- "Use black formatting"

What this changes:
- The agent remembers your preferences without repeating them
- Skills trigger automatically based on task keywords
- The agent feels personalized to your workflow

D39 (hermes curator + skill_usage): skills now carry lifecycle metadata —
`created_by` provenance ("user" vs "agent"), `pinned` (exempts a skill from
every auto-transition), usage telemetry (`use_count` / `view_count` /
`patch_count` / `last_activity_at`), and a curator state machine
(active -> stale -> archived) that ONLY touches agent-created skills, never
deletes, and leaves pinned skills alone. `skills_manifest()` emits a compact
byte-stable index (the hermes skills-index manifest idea).
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

_DEFAULT_STALE_AFTER_DAYS = 30
_DEFAULT_ARCHIVE_AFTER_DAYS = 90
# hermes injects full skill bodies; bundled Crusor skills are authored to fit
# comfortably under this cap while keeping real workflow (not just a summary).
_BUNDLED_INSTRUCTION_CAP = 6000


def _parse_skill_frontmatter(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter_dict, body).

    Dependency-free targeted parser for the simple hermes frontmatter shape:
    `name`, `version`, `description`, inline lists (`key: [a, b]`), block
    lists (`key:` followed by `- item` lines) and the nested
    `metadata.hermes.*` block. Anything it can't parse is skipped silently —
    a malformed skill must never block boot (D17 fail-open).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text.strip()
    fm: dict = {}
    stack: list[tuple[int, str]] = []  # open container keys: (indent, key)

    def _dict_bucket() -> dict:
        """Walk the open stack creating dicts; convert seeded lists."""
        node = fm
        for _indent, key in stack:
            child = node.get(key)
            if not isinstance(child, dict):
                # `key:` seeded as a block list; a deeper key proves it is
                # actually a mapping (e.g. metadata: > hermes: > tags:)
                child = {}
                node[key] = child
            node = child
        return node

    for raw in lines[1:end]:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", stripped)
        if m and not stripped.startswith("- "):
            key, val = m.group(1).lower(), m.group(2).strip()
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not val:
                # could become a block list (- items) or a nested mapping —
                # seed a list; _dict_bucket converts on demand
                _dict_bucket()[key] = []
                stack.append((indent, key))
                continue
            if val.startswith("[") and val.endswith("]"):
                value: Any = [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            else:
                value = val.strip("'\"")
            _dict_bucket()[key] = value
        elif stripped.startswith("- ") and stack:
            item = stripped[2:].strip().strip("'\"")
            node = fm
            for _indent, key in stack[:-1]:
                child = node.get(key)
                if not isinstance(child, dict):
                    break
                node = child
            target = node.get(stack[-1][1])
            if isinstance(target, list):
                target.append(item)
    return fm, "\n".join(lines[end + 1:]).strip()


def _frontmatter_triggers(frontmatter: dict) -> list[str]:
    """Derive skill triggers from frontmatter `keywords` / `triggers` keys.

    Tags are deliberately excluded: they are taxonomy (hermes uses them for
    catalog search), and generic words like "quality" or "development" match
    far too loosely as substrings. Deduped, order-stable, lowercased.
    """
    collected: list[str] = []

    def _scan(node: Any) -> None:
        if isinstance(node, str):
            for t in node.replace(",", " ").split():
                collected.append(t.lower())
        elif isinstance(node, list):
            for item in node:
                _scan(item)

    for key in ("keywords", "triggers"):
        val = frontmatter.get(key)
        if val:
            _scan(val if isinstance(val, list) else [val])
    seen: set[str] = set()
    triggers: list[str] = []
    for t in collected:
        if t and t not in seen:
            seen.add(t)
            triggers.append(t)
    return triggers

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_NOW = lambda: _utcnow().isoformat(timespec="seconds")


def _iso_to_dt(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None


class SkillManager:
    """
    Manages user-defined skills that inject into agent context.
    """
    def __init__(self, storage_path: str | None = None):
        if storage_path is None:
            home = os.path.expanduser("~")
            crusor_dir = os.path.join(home, ".crusorai")
            os.makedirs(crusor_dir, exist_ok=True)
            self.storage_path = os.path.join(crusor_dir, "skills.json")
        else:
            self.storage_path = storage_path

        self._skills: list[dict] = []
        # D39: single writer for skills.json — the skills layer injects on
        # every build in the dashboard's worker threads.
        self._save_lock = threading.Lock()
        self._load()
        self._load_bundled_skills()

    # =========================================================
    # PERSISTENCE
    # =========================================================

    def _ensure_metadata(self, skill: dict) -> dict:
        """Normalize a (possibly legacy) skill dict to the D39 lifecycle
        shape. Returns the skill dict (mutated) with defaults filled."""
        skill.setdefault("enabled", True)
        skill.setdefault("created_by", "user")
        skill.setdefault("description", "")
        skill.setdefault("pinned", False)
        skill.setdefault("state", "active")
        skill.setdefault("use_count", 0)
        skill.setdefault("view_count", 0)
        skill.setdefault("patch_count", 0)
        skill.setdefault("created_at", _NOW())
        skill.setdefault("updated_at", None)
        skill.setdefault("last_activity_at", None)
        return skill

    def _load(self) -> None:
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list):
                self._skills = [self._ensure_metadata(s) for s in raw if isinstance(s, dict)]
        except Exception:
            self._skills = []

    def _load_bundled_skills(self, skills_dir: str | None = None) -> None:
        """Load enterprise SKILL.md from PulseAIRepo/skills/*/SKILL.md (hermes parity).

        Each SKILL.md becomes a pinned, enabled skill (`created_by=bundled`,
        never auto-archived). Trigger derivation, in priority order (hermes
        prompt_builder parity):
          1. an explicit `**Triggers:**` line in the body
          2. frontmatter `keywords:` / `triggers:` (tags are taxonomy only)
          3. fallback: the folder name

        The injected instruction is the skill BODY (frontmatter stripped) —
        injecting raw YAML was wasting the budget on keys the model can't use.
        """
        try:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            if skills_dir is None:
                skills_dir = os.path.join(repo_root, "skills")
            if not os.path.isdir(skills_dir):
                return
            for entry in os.listdir(skills_dir):
                md = os.path.join(skills_dir, entry, "SKILL.md")
                if not os.path.isfile(md):
                    continue
                text = open(md, encoding="utf-8").read()
                frontmatter, body = _parse_skill_frontmatter(text)
                # 1) explicit **Triggers:** line
                triggers: list[str] = []
                for line in body.splitlines():
                    if line.strip().lower().startswith("**triggers:**"):
                        raw = line.split(":", 1)[-1].strip().lstrip("*").strip()
                        # comma-separated is the authored form; tolerate a
                        # bare space-separated list (legacy)
                        if "," in raw:
                            triggers = [t.strip().lower() for t in raw.split(",") if t.strip()]
                        else:
                            triggers = [t.strip().lower() for t in raw.split() if t.strip()]
                        break
                # 2) frontmatter keywords / triggers (NOT tags — tags are
                #    taxonomy and match far too loosely as substrings)
                if not triggers:
                    triggers = _frontmatter_triggers(frontmatter)
                if not triggers:
                    triggers = [entry.lower()]
                # Avoid duplicate
                if any(s["name"] == entry for s in self._skills):
                    continue
                # Instruction = body without frontmatter, capped. Bundled
                # skills carry real workflow (hermes injects full bodies), so
                # the cap is higher than the user-skill default.
                instruction = body.strip()[:_BUNDLED_INSTRUCTION_CAP]
                self._skills.append(self._ensure_metadata({
                    "name": entry,
                    "description": str(frontmatter.get("description", "") or "").strip(),
                    "triggers": triggers,
                    "instruction": instruction,
                    "enabled": True,
                    "created_by": "bundled",
                    "pinned": True,
                    "state": "active",
                    "created_at": _NOW(),
                    "updated_at": _NOW(),
                    "last_activity_at": _NOW(),
                }))
        except Exception:
            pass

    def _save(self) -> None:
        with self._save_lock:
            try:
                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(self._skills, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

    # =========================================================
    # CRUD
    # =========================================================

    def add_skill(
        self,
        name: str,
        triggers: list[str],
        instruction: str,
        *,
        created_by: str = "user",
        pinned: bool = False,
        description: str = "",
        source: dict | None = None,
    ) -> None:
        """
        Add a new skill (or update an existing one by name).
        Args:
            name: Skill name (e.g. "Type Hint Rule")
            triggers: Keywords that activate this skill (e.g., ["python", "function"])
            instruction: The prompt text injected when triggered
            created_by: "user" (foreground user-facing path) or "agent"
                (self-curation). Curator transitions only touch "agent".
            pinned: True exempts the skill from every auto-transition.
            description: One-line discovery summary for the skills index
                (Agent Skills frontmatter parity — name + description is what
                the model sees before it pulls the body).
        """
        existing = next((s for s in self._skills if s["name"] == name), None)
        if existing:
            existing["triggers"] = [t.lower() for t in triggers]
            existing["instruction"] = instruction
            if description:
                existing["description"] = description
            existing["enabled"] = True
            existing["pinned"] = existing.get("pinned", False) or pinned
            existing["state"] = "active"  # editing reactivates a stale/archived skill
            existing["patch_count"] = int(existing.get("patch_count", 0)) + 1
            existing["updated_at"] = _NOW()
            existing["last_activity_at"] = _NOW()
            if source is not None:
                existing["source"] = source
            self._save()
            return
        self._skills.append(self._ensure_metadata({
            "name": name,
            "description": description,
            "triggers": [t.lower() for t in triggers],
            "instruction": instruction,
            "enabled": True,
            "created_by": created_by,
            "pinned": pinned,
            "state": "active",
            "created_at": _NOW(),
            "updated_at": _NOW(),
            "last_activity_at": _NOW(),
        }))
        if source is not None:
            self._skills[-1]["source"] = source
        self._save()

    def remove_skill(self, name: str) -> bool:
        original_len = len(self._skills)
        self._skills = [s for s in self._skills if s["name"] != name]
        self._save()
        return len(self._skills) < original_len

    def toggle_skill(self, name: str, enabled: bool) -> bool:
        for skill in self._skills:
            if skill["name"] == name:
                skill["enabled"] = enabled
                self._save()
                return True
        return False

    def load_workspace_skills(self, workspace: str | None) -> int:
        """Scan <workspace>/.crusorai/skills/*/SKILL.md into the index as
        PROJECT skills (created_by='project', pinned) — the committed,
        team-shared lane (Claude's .claude/skills parity, field 2026-10-02:
        "that claude boring part"). The folder is the source of truth:

          - idempotent: existing project entries keep their enabled flag;
          - a file that vanished is dropped from the index (nothing on
            disk, nothing in the model's view);
          - a name already owned by a NON-project skill is skipped (a
            team folder never shadows bundled/user/hub skills);
          - malformed skills never block (D17 fail-open).

        Cheap by design (listdir + small reads) — callers may invoke it
        every chat turn. Returns the number of project skills live."""
        ws = str(workspace or "").strip()
        if not ws:
            return 0
        skills_dir = os.path.join(ws, ".crusorai", "skills")
        try:
            keep_enabled: dict[str, bool] = {
                str((s.get("source") or {}).get("path") or ""): bool(s.get("enabled", True))
                for s in self._skills if s.get("created_by") == "project"
            }
            owned = {s["name"] for s in self._skills if s.get("created_by") != "project"}
            self._skills = [s for s in self._skills if s.get("created_by") != "project"]
            if not os.path.isdir(skills_dir):
                return 0
            count = 0
            for entry in sorted(os.listdir(skills_dir)):
                md = os.path.join(skills_dir, entry, "SKILL.md")
                if not os.path.isfile(md):
                    continue
                try:
                    text = open(md, encoding="utf-8").read()
                    frontmatter, body = _parse_skill_frontmatter(text)
                    triggers = _frontmatter_triggers(frontmatter)
                    raw_name = str(frontmatter.get("name", "") or "").strip().lower()
                    name = re.sub(r"[^a-z0-9-]+", "-", raw_name).strip("-") or entry.lower()
                    if name in owned or any(s["name"] == name for s in self._skills):
                        continue  # never shadow a non-project skill
                    self._skills.append(self._ensure_metadata({
                        "name": name,
                        "description": str(frontmatter.get("description", "") or "").strip(),
                        "triggers": triggers or [name],
                        "instruction": body.strip()[:_BUNDLED_INSTRUCTION_CAP],
                        "enabled": keep_enabled.get(md, True),
                        "created_by": "project",
                        "pinned": True,
                        "state": "active",
                        "created_at": _NOW(),
                        "updated_at": _NOW(),
                        "last_activity_at": _NOW(),
                        "source": {"kind": "project", "path": md},
                    }))
                    count += 1
                except Exception:
                    continue  # one broken team file never blocks the rest
            return count
        except Exception:
            return 0

    def list_skills(self) -> list[dict]:
        return list(self._skills)

    def get_usage(self, name: str) -> dict | None:
        """D39: telemetry snapshot for one skill."""
        skill = next((s for s in self._skills if s["name"] == name), None)
        if skill is None:
            return None
        return {
            "use_count": skill.get("use_count", 0),
            "view_count": skill.get("view_count", 0),
            "patch_count": skill.get("patch_count", 0),
            "state": skill.get("state", "active"),
            "pinned": skill.get("pinned", False),
            "created_by": skill.get("created_by", "user"),
            "last_activity_at": skill.get("last_activity_at"),
        }

    # =========================================================
    # USAGE TELEMETRY (D39)
    # =========================================================

    def record_usage(self, name: str, action: str) -> None:
        """Record a usage event for a skill and persist.

        action: "use" (injected into context), "view" (inspected), or
        "patch" (updated). Pinned/archived skills still count usage.
        """
        skill = next((s for s in self._skills if s["name"] == name), None)
        if skill is None:
            return
        if action == "use":
            skill["use_count"] = int(skill.get("use_count", 0)) + 1
        elif action == "view":
            skill["view_count"] = int(skill.get("view_count", 0)) + 1
        elif action == "patch":
            skill["patch_count"] = int(skill.get("patch_count", 0)) + 1
        else:
            return
        skill["last_activity_at"] = _NOW()
        self._save()

    # =========================================================
    # SELECTION / INJECTION
    # =========================================================

    def get_relevant_skills(self, task: str) -> list[str]:
        """
        Return instructions for enabled, non-archived skills whose triggers
        match the task, and record 'use' telemetry for each match.
        """
        task_lower = (task or "").lower()
        instructions = []
        for skill in self._skills:
            if not skill.get("enabled", True):
                continue
            if skill.get("state") == "archived":
                continue
            if any(trigger in task_lower for trigger in skill.get("triggers", [])):
                instructions.append(f"**{skill['name']}:** {skill['instruction']}")
                self.record_usage(skill["name"], "use")
        return instructions

    def get_skills_text(self, task: str) -> str:
        """
        Return formatted skills text for context injection.
        """
        instructions = self.get_relevant_skills(task)
        if not instructions:
            return ""
        lines = ["=== ACTIVE SKILLS ==="]
        lines.append("The following user preferences apply to this task:\n")
        for inst in instructions:
            lines.append(f"- {inst}")
        lines.append("\nFollow these preferences when completing the task.")
        return "\n".join(lines)

    def skills_manifest(self) -> str:
        """D39: compact, byte-stable index of all enabled skills. Stable as
        long as the skills file doesn't change (the hermes skills-index
        manifest idea, sans the token bloat of full instructions)."""
        rows = []
        for skill in self._skills:
            if not skill.get("enabled", True):
                continue
            marker = " [pinned]" if skill.get("pinned") else ""
            rows.append(f"- **{skill['name']}** ({', '.join(skill.get('triggers', []))}){marker}")
        if not rows:
            return ""
        return "=== SKILLS INDEX ===\n" + "\n".join(rows)

    # =========================================================
    # CURATOR (D39, hermes curator.py)
    # =========================================================

    def curator_run(
        self,
        stale_after_days: int = _DEFAULT_STALE_AFTER_DAYS,
        archive_after_days: int = _DEFAULT_ARCHIVE_AFTER_DAYS,
    ) -> list[dict[str, Any]]:
        """Auto-transition agent-created skills: active -> stale ->
        archived based on last_activity_at. Invariants: only created_by ==
        "agent"; pinned skills exempt; NEVER deletes (archive is the most
        destructive action); archived skills already stay archived.

        Returns a report of transitions performed (empty when nothing
        moved). Called on demand (e.g. after a background review run)."""
        report: list[dict[str, Any]] = []
        now = _utcnow()
        changed = False
        for skill in self._skills:
            if skill.get("created_by") != "agent":
                continue
            if skill.get("pinned"):
                continue
            state = skill.get("state", "active")
            if state == "archived":
                continue
            last = _iso_to_dt(skill.get("last_activity_at"))
            if last is None:
                continue
            age_days = (now - last).days
            new_state = state
            if age_days >= archive_after_days:
                new_state = "archived"
            elif age_days >= stale_after_days:
                new_state = "stale"
            if new_state != state:
                skill["state"] = new_state
                skill["updated_at"] = _NOW()
                changed = True
                report.append({
                    "name": skill["name"],
                    "from": state,
                    "to": new_state,
                    "idle_days": age_days,
                })
        if changed:
            self._save()
        return report

# Global singleton
skill_manager = SkillManager()