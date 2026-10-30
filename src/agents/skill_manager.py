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
import time
from datetime import datetime, timezone
from typing import Any

_DEFAULT_STALE_AFTER_DAYS = 30
_DEFAULT_ARCHIVE_AFTER_DAYS = 90
# hermes injects full skill bodies; bundled Crusor skills are authored to fit
# comfortably under this cap while keeping real workflow (not just a summary).
_BUNDLED_INSTRUCTION_CAP = 6000

# How many characters of architect books may be injected for free (no tool call)
# at planning time. 16 000 chars ≈ 4 200 tokens ≈ 3-4 books: enough that the
# common plan needs zero `skill_view` calls, small enough that it never crowds
# out the actual task. Override with SKILL_INJECT_CHARS.
_INJECT_CHARS = int(os.environ.get("SKILL_INJECT_CHARS", "16000"))


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
            # Commas separate triggers, whitespace does NOT: "server state"
            # is one phrase. Word-splitting it produced "server" and "state",
            # which match almost any task and flood the injection.
            for part in node.split(","):
                t = part.strip().lower()
                if t:
                    collected.append(t)
        elif isinstance(node, list):
            for item in node:
                _scan(item)

    for key in ("keywords", "triggers"):
        val = frontmatter.get(key)
        if val:
            _scan(val if isinstance(val, list) else [val])
    # Agent Skills spec keeps the frontmatter surface closed, so a skill that
    # wants routing keywords without inventing top-level fields carries them in
    # the free-form `metadata` map instead. `crusor-triggers` is that slot.
    meta = frontmatter.get("metadata")
    if isinstance(meta, dict):
        for key in ("crusor-triggers", "keywords", "triggers"):
            val = meta.get(key)
            if val:
                _scan(val if isinstance(val, list) else [val])
    seen: set[str] = set()
    triggers: list[str] = []
    for t in collected:
        if t and t not in seen:
            seen.add(t)
            triggers.append(t)
    return triggers

_TRIGGER_CACHE: dict[str, "re.Pattern[str]"] = {}


def trigger_matches(task_lower: str, trigger: str) -> bool:
    """Whole-word matching for a trigger against a lowercased task.

    Substring matching fired ``vite`` on "vitest" and ``test`` on "latest".
    A trigger matches only at a token boundary; hyphens stay part of the token
    so "end-to-end" and "next.js" keep working.
    """
    t = (trigger or "").strip().lower()
    if not t or not task_lower:
        return False
    # Cheap reject first: the regex needs the literal trigger as a substring, so
    # a `str.__contains__` (nanoseconds) answers "no" for most of 2 400 comparisons
    # before any regex runs. Matching 240 skills' worth of triggers went 9.3 -> 1.1 ms.
    if t not in task_lower:
        return False
    pattern = _TRIGGER_CACHE.get(t)
    if pattern is None:
        # Trailing "s" is tolerated so "unit test" still fires on "unit tests"
        # while "vite" still does not fire on "vitest".
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"s?(?![a-z0-9])")
        _TRIGGER_CACHE[t] = pattern
    return pattern.search(task_lower) is not None


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



# ---------------------------------------------------------------------------
# Plan Mode stack spine
#
# "An architect-level plan is not one book." A product plan has to answer the
# same concerns in every domain — shell, boundary, data, security, delivery —
# and trigger matching alone cannot supply that: "build a SaaS for field
# service teams" matches three books, none of them the API or the data model.
# So a product-shaped task also gets a spine: one book per concern, per domain
# its words point at. Narrow tasks ("add retry to the bridge") get none.
# ---------------------------------------------------------------------------
_STACK_SPINE: dict[str, tuple[str, ...]] = {
    "website": ("website-architect", "frontend-development-architect", "backend-development-architect",
                "api-development-architect", "database-engineering-architect",
                "security-architect", "testing-and-deployment-architect"),
    "mobile": ("mobile-architect", "mobile-offline-sync-architect",
               "mobile-release-architect", "mobile-security-architect"),
    "desktop": ("desktop-architect", "desktop-ipc-architect",
                "desktop-distribution-architect", "desktop-update-architect"),
    "data": ("data-engineering-architect", "warehouse-architect",
             "ingestion-architect", "analytics-engineering-architect"),
    "ai-ml": ("ai-ml-architect", "model-selection-architect", "rag-architect",
              "evals-architect"),
    "cloud-and-devops": ("cloud-and-devops-architect", "aws-architect",
                         "terraform-architect", "kubernetes-architect",
                         "sre-observability-architect"),
}

_DOMAIN_WORDS: dict[str, tuple[str, ...]] = {
    "website": ("saas", "web", "webapp", "website", "product", "platform", "marketplace",
                "dashboard", "portal", "b2b", "subscription", "billing", "signup", "login",
                "api", "backend", "frontend", "full stack", "multi tenant", "multi-tenant"),
    "mobile": ("mobile", "ios", "android", "iphone", "ipad", "tablet", "app store",
               "play store", "flutter", "react native", "field team", "field service"),
    "desktop": ("desktop", "electron", "windows app", "mac app", "menu bar", "system tray"),
    "data": ("analytics", "warehouse", "etl", "elt", "reporting", "metrics", "data pipeline",
             "ingestion", "bi"),
    "ai-ml": ("llm", "ai", "ml", "model", "rag", "agent", "chatbot", "embedding", "inference"),
    "cloud-and-devops": ("cloud", "aws", "gcp", "azure", "kubernetes", "deploy", "infra",
                         "infrastructure", "terraform", "scale", "docker", "ci/cd"),
}

# Verbs that mean "design a system", not "change a line".
_PRODUCT_VERBS = ("build", "create", "design", "launch", "plan", "ship", "architect",
                  "start", "develop", "implement", "add support for", "migrate", "rewrite")


def _has_word(text: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(word), text) is not None


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
        # Legacy + user-created skills carry no phase: they are always usable.
        skill.setdefault("phase", "always")
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
        """Load bundled SKILL.md files from the skills tree (hermes parity).

        Discovery is RECURSIVE: every directory that contains a `SKILL.md` is a
        skill, whatever its depth. Taxonomy containers (no `SKILL.md`) carry
        structure only and are never injected — this is what lets the Architect
        library nest domain -> branch -> technology -> skill while every skill
        still obeys the Agent Skills rule "name == parent directory".

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
            # Deterministic discovery order: os.walk yields a directory before
            # its children; dirs.sort() keeps sibling order stable across
            # filesystems. Names must be globally unique (Agent Skills spec), so
            # the first skill discovered with a given name wins and later
            # duplicates are skipped rather than silently shadowing it.
            # Names owned by non-bundled (user/agent/hub) skills are protected:
            # a shipped skill never shadows something the user owns. Bundled
            # entries already in the store are refreshed from disk below.
            owned = {s["name"] for s in self._skills if s.get("created_by") != "bundled"}
            seen_names: set[str] = set()
            skills_root = os.path.abspath(skills_dir)
            for root, dirs, files in os.walk(skills_dir):
                dirs.sort()
                # The tree root is a container (it may carry an index
                # SKILL.md describing the library); it has never been a skill.
                if os.path.abspath(root) == skills_root:
                    continue
                if "SKILL.md" not in files:
                    continue
                entry = os.path.basename(root.rstrip(os.sep))
                if not entry or entry in owned or entry in seen_names:
                    continue
                md = os.path.join(root, "SKILL.md")
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
                # Instruction = body without frontmatter, capped. Bundled
                # skills carry real workflow (hermes injects full bodies), so
                # the cap is higher than the user-skill default.
                instruction = body.strip()[:_BUNDLED_INSTRUCTION_CAP]
                rel_path = os.path.relpath(root, skills_root).replace(os.sep, "/")
                fresh = {
                    "name": entry,
                    # Where the book sits on the shelf. Needed because the
                    # library is nested: skill_view must be able to open the
                    # file again, and browsing needs the shelf structure.
                    "path": rel_path,
                    "shelf": os.path.dirname(rel_path),
                    # Architect skills are planning instruments: they belong to
                    # the moment a plan / todo list is being written, not to the
                    # execution that follows. `metadata.crusor-phase` can set
                    # this explicitly; the `-architect` suffix is the default.
                    "phase": str(
                        frontmatter.get("metadata", {}).get("crusor-phase")
                        or ("planning" if entry.endswith("-architect") else "always")
                    ),
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
                }
                # A persisted store from an older build must not freeze an old
                # copy of a bundled skill: the file on disk is the source of
                # truth for everything except the user's lifecycle state and
                # telemetry, which are carried over.
                previous = next((x for x in self._skills if x.get("name") == entry), None)
                if previous is not None and previous.get("created_by") == "bundled":
                    fresh["created_at"] = previous.get("created_at", fresh["created_at"])
                    for key in ("enabled", "state", "pinned", "use_count",
                                "view_count", "patch_count", "last_activity_at"):
                        if key in previous:
                            fresh[key] = previous[key]
                    previous.clear()
                    previous.update(self._ensure_metadata(fresh))
                else:
                    self._skills.append(self._ensure_metadata(fresh))
                seen_names.add(entry)
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

    _usage_save_interval = 30.0  # seconds; usage counts are telemetry, not state

    def _maybe_flush_usage(self) -> None:
        """Persist usage counters at most once every 30 s.

        The store holds every book body, so writing it on each injection put
        disk churn on the planning hot path to save a counter that only feeds
        ranking statistics.
        """
        now = time.time()
        if now - getattr(self, "_last_usage_save", 0.0) < self._usage_save_interval:
            return
        self._last_usage_save = now
        self._save()

    def record_usage(self, name: str, action: str, persist: bool = True) -> None:
        """Record a usage event for a skill and persist.

        action: "use" (injected into context), "view" (inspected), or
        "patch" (updated). Pinned/archived skills still count usage.

        ``persist=False`` skips the write so a caller that records several
        events can pay for one save instead of one per skill: the store holds
        every book body, so a save mid-injection was tens of milliseconds of
        disk churn on the planning hot path for a telemetry counter.
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
        if persist:
            self._save()  # explicit events persist at once (usage telemetry contract)

    # =========================================================
    # SELECTION / INJECTION
    # =========================================================

    def get_relevant_skills(self, task: str, phase: str = "executing") -> list[str]:
        """
        Return instructions for enabled, non-archived skills whose triggers
        match the task, and record 'use' telemetry for each match.

        ``phase`` gates planning instruments: a skill recorded with
        ``phase="planning"`` (every ``*-architect`` skill) is only injected
        while a plan or todo list is being produced. During execution the
        model reaches them through ``skills_list`` / ``skill_view`` instead —
        never through a trigger match.
        """
        task_lower = (task or "").lower()
        instructions = []
        for skill in self._skills:
            if not skill.get("enabled", True):
                continue
            if skill.get("state") == "archived":
                continue
            if str(skill.get("phase", "always")) == "planning" and phase != "planning":
                continue
            if any(trigger_matches(task_lower, t) for t in skill.get("triggers", [])):
                instructions.append(f"**{skill['name']}:** {skill['instruction']}")
                self.record_usage(skill["name"], "use")
        return instructions

    def _match_score(self, task_lower: str, skill: dict) -> float:
        """How strongly this book answers this task. Longer phrases beat single words."""
        hits = [t for t in skill.get("triggers", []) if trigger_matches(task_lower, t)]
        if not hits:
            return 0.0
        score = sum(1.0 + len(t) / 20.0 for t in hits)
        name_words = {w for w in re.split(r"[-_]", str(skill.get("name", "")).lower()) if len(w) > 3}
        score += sum(0.5 for w in name_words if re.search(r"\b%s\b" % re.escape(w), task_lower))
        if str(skill.get("name", "")).endswith("-architect"):
            score += 0.25
        return score

    def ranked_for_task(self, task: str, phase: str = "planning") -> list[tuple[float, dict]]:
        """Enabled skills whose triggers match, strongest first.

        A shelf crown is dropped when a book beneath it also matched: the crown
        is an index, and injecting it next to its own child is pure waste.
        """
        task_lower = (task or "").lower()
        scored: list[tuple[float, dict]] = []
        for skill in self._skills:
            if not skill.get("enabled", True) or skill.get("state") == "archived":
                continue
            if str(skill.get("phase", "always")) == "planning" and phase != "planning":
                continue
            score = self._match_score(task_lower, skill)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda pair: -pair[0])
        kept: list[tuple[float, dict]] = []
        for score, skill in scored:
            path = str(skill.get("path") or skill.get("name") or "")
            shadowed = any(
                str(other.get("path") or "").startswith(path + "/")
                for _, other in scored
                if other is not skill
            )
            if not shadowed:
                kept.append((score, skill))
        return kept

    # How much architect material Plan Mode may carry. A plan that a strong SaaS
    # is built from is not one book: it needs the stack — shell, API, data,
    # security, delivery — plus the domain specifics. 60 000 chars ≈ 15 800
    # tokens, which is affordable once per planning turn and catastrophic only
    # if it happened every turn (it does not: the gate is the plan-mode turn).
    _PLAN_KIT_CHARS = int(os.environ.get("SKILL_PLAN_KIT_CHARS", "60000"))

    def _spine_for(self, task: str) -> list[tuple[str, str]]:
        """Books a product plan must cover, derived from the domains the task names."""
        if not self._is_product_task(task):
            return []
        spine: list[tuple[str, str]] = []
        for domain in self._detect_domains(task):
            for name in _STACK_SPINE.get(domain, ()):
                spine.append((name, domain))
        return spine

    def get_skill(self, name: str) -> dict | None:
        return next((s for s in self._skills if s.get("name") == name), None)

    def _detect_domains(self, task: str) -> list[str]:
        low = (task or "").lower()
        found = [d for d, words in _DOMAIN_WORDS.items() if any(_has_word(low, w) for w in words)]
        return found

    def _is_product_task(self, task: str) -> bool:
        low = (task or "").lower()
        return any(_has_word(low, v) or v in low for v in _PRODUCT_VERBS)

    def plan_kit(self, task: str, budget_chars: int | None = None) -> dict[str, list[dict]]:
        """The books an architect-level plan needs, grouped by how much they matter.

        Tiers, in reading order:
          core    — the crown(s) of the matched domain(s): the map and the rules
          stack   — shelf crowns that matched: one per concern (API, data, security…)
          detail  — matched books: the framework-level decisions

        Built rather than picked: a single skill cannot produce a plan that spans
        a product, and returning three books was the old behaviour.
        """
        budget = budget_chars or self._PLAN_KIT_CHARS
        ranked = self.ranked_for_task(task, phase="planning")
        spine = self._spine_for(task)

        if not ranked and not spine:
            return {"core": [], "stack": [], "detail": []}

        by_path = {str(s.get("path") or s["name"]): s for _score, s in ranked}
        core: list[dict] = []
        stack: list[dict] = []
        detail: list[dict] = []

        chosen_names: set[str] = set()
        for name, role in spine:
            skill = self.get_skill(name)
            if not skill:
                continue
            entry = {"name": name, "path": str(skill.get("path") or name),
                     "score": 0.0, "role": role,
                     "description": str(skill.get("description") or "")[:160],
                     "chars": len(str(skill.get("instruction") or ""))}
            (core if skill.get("path", "").count("/") == 0 else stack).append(entry)
            chosen_names.add(name)

        for score, skill in ranked:
            if skill["name"] in chosen_names:
                continue
            path = str(skill.get("path") or skill["name"])
            depth = path.count("/")
            entry = {"name": skill["name"], "path": path, "score": round(score, 2),
                     "description": str(skill.get("description") or "")[:160],
                     "chars": len(str(skill.get("instruction") or ""))}
            if depth == 0 and len(core) < 2:
                core.append(entry)
            elif depth == 1 and len(stack) < 8:
                # a shelf crown earns the stack slot only if its own books matched
                stack.append(entry)
            else:
                detail.append(entry)

        # Fill the budget in tier order, dropping the weakest detail first.
        def total(entries: list[dict]) -> int:
            return sum(e["chars"] for e in entries)

        kept_before = len(core) + len(stack) + len(detail)
        while core + stack + detail and total(core + stack + detail) > budget:
            if len(detail) > 3:
                detail.pop()
            elif len(stack) > 2:
                stack.pop()
            elif len(core) > 1:
                core.pop()
            else:
                break
        kept = len(core) + len(stack) + len(detail)
        return {"core": core, "stack": stack, "detail": detail,
                "dropped": max(0, len(ranked) + len(spine) - kept)}

    _PLAN_DIGEST_CHARS = int(os.environ.get("SKILL_PLAN_DIGEST_CHARS", "4000"))

    def plan_digest(self, task: str, budget_chars: int | None = None) -> str:
        """What the build phase needs from the books the plan was written from.

        Plan Mode gets the books whole; execution cannot, and should not — 13 000
        tokens of prose on every build turn is the wrong trade. What execution
        does need is the *constraints* those books imposed: which decisions were
        taken, so the code matches the plan instead of drifting from it.

        So: the same kit derivation, reduced to each book's decision headings.
        ~100 chars per book, and the full text is one skill_view away.
        """
        budget = budget_chars or self._PLAN_DIGEST_CHARS
        kit = self.plan_kit(task)
        entries = [e for tier in ("core", "stack", "detail") for e in kit[tier]]
        if not entries:
            return ""
        lines = ["=== PLAN CONSTRAINTS (architect books behind this plan) ==="]
        used = len(lines[0])
        for entry in entries:
            skill = self.get_skill(entry["name"])
            if not skill:
                continue
            body = str(skill.get("instruction") or "")
            decisions = [line.strip("# ").strip() for line in body.splitlines()
                         if line.startswith("## Decision") or line.startswith("## Step")]
            if not decisions:
                decisions = [line.strip("# ").strip() for line in body.splitlines()
                             if line.startswith("## ")][:4]
            line = f"- {entry['name']}: " + "; ".join(decisions[:6])
            if used + len(line) > budget:
                lines.append(f"- ({len(entries)} books total — open any with skill_view(\"name\"))")
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    def complete_task(self, task: str, plan_steps: list | None = None) -> dict:
        """Close the loop: return the books that governed a finished task.

        Every completed task hands its books back — name, path, provenance and
        the verification receipts the plan was supposed to satisfy. Deterministic:
        the same derivation that injected at plan time runs here, so what is
        returned is exactly what shaped the work.

        Cheap by construction (one kit derivation, no model call), safe to call
        from finalize, and never raises into the turn.
        """
        plan_text = " ".join(str(step.get("description") or "") if isinstance(step, dict)
                             else str(step) for step in (plan_steps or []))
        kit = self.plan_kit(f"{task} {plan_text}".strip())
        books = []
        for tier in ("core", "stack", "detail"):
            for entry in kit[tier]:
                skill = self.get_skill(entry["name"])
                if not skill:
                    continue
                body = str(skill.get("instruction") or "")
                receipts = []
                if "## Verification receipts" in body:
                    tail = body.split("## Verification receipts", 1)[1]
                    for line in tail.splitlines():
                        if re.match(r"^\d+\. ", line.strip()):
                            receipts.append(line.strip()[3:][:160])
                        elif receipts and line.strip() and not line.startswith("#"):
                            break
                books.append({
                    "name": entry["name"],
                    "path": str(skill.get("path") or ""),
                    "tier": tier,
                    "origin": "architect",
                    "receipts": receipts[:5],
                })
                self.record_usage(entry["name"], "use", persist=False)
        if books:
            self._save()  # the completion receipt is a real event: persist it now
        return {"task": task[:200], "books": books, "count": len(books)}

    def get_skills_text(self, task: str, phase: str = "executing") -> str:
        """Budgeted, ranked injection — the zero-call path.

        Zero calls means the *right* books already in the prompt. Injecting
        every trigger match (the old behaviour) was neither: a task matching
        five books paid ~18 000 chars for one useful book. This keeps the
        strongest few inside `_INJECT_CHARS` and says how many were left, so
        the agent knows to pull the rest deliberately.
        """
        planning = phase == "planning"
        if not planning:
            ranked = self.ranked_for_task(task, phase=phase)
            if not ranked:
                return ""
            chosen = []
            for _score, skill in ranked:
                chosen.append(f"**{skill['name']}:** {skill['instruction']}")
                self.record_usage(skill["name"], "use", persist=False)
            if chosen:
                self._maybe_flush_usage()
            return "\n".join(["=== ACTIVE SKILLS ===", *chosen])

        kit = self.plan_kit(task)
        sections: list[str] = []
        labels = {
            "core": "The domain map and its rules — read first.",
            "stack": "One book per concern the plan must cover.",
            "detail": "Framework-level decisions for the parts being built.",
        }
        for tier in ("core", "stack", "detail"):
            entries = kit[tier]
            if not entries:
                continue
            sections.append(f"### {tier.upper()} — {labels[tier]}")
            for entry in entries:
                skill = self.get_skill(entry["name"])
                if not skill:
                    continue
                sections.append(f"**{skill['name']}:** {skill['instruction']}")
                self.record_usage(skill["name"], "use", persist=False)
        if not sections:
            return ""
        self._maybe_flush_usage()
        count = sum(len(kit[t]) for t in ("core", "stack", "detail"))
        tail = []
        if kit.get("dropped"):
            tail.append(
                f"\n{kit['dropped']} more book(s) matched and were left out of the budget. "
                'Pull them deliberately with skill_view("name-a, name-b").'
            )
        return "\n\n".join([
            "=== ACTIVE SKILLS ===",
            f"Plan Mode: {count} architect books are loaded. An architect-level plan "
            "is not one book — cover the stack, then decide.",
            *sections,
            *tail,
        ])

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