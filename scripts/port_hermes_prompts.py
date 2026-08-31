#!/usr/bin/env python3
"""Extract the pinned Hermes prompt corpus into Pulse's vendored prompt engine.

This is the mechanical half of the "pin-to-pin" port: instead of retyping
Hermes's prompt text (which drifts the moment someone edits it), we parse the
upstream module, lift the prompt-bearing constants verbatim, and write them to
``src/prompts/hermes/upstream_corpus.json`` with a provenance manifest.

At runtime ``src/prompts/hermes/guidance.py`` loads that corpus and applies ONE
documented transformation — the Hermes→Pulse tool-name rename map — so the
words are upstream's and the identifiers are Pulse's. The parity test re-runs
the same extraction against a checkout of the pinned commit and asserts
byte-equality, which is what makes "pin to pin" checkable rather than a claim.

Usage:
    python3 scripts/port_hermes_prompts.py /path/to/hermes-agent
"""
from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import json
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "src" / "prompts" / "hermes" / "upstream_corpus.json"

# module -> symbols to lift. Everything here is a top-level assignment whose
# value is a literal (str / tuple / int / float / dict of literals).
WANTED: dict[str, list[str]] = {
    "agent/prompt_builder.py": [
        "DEFAULT_AGENT_IDENTITY",
        "HERMES_AGENT_HELP_GUIDANCE",
        "HERMES_AGENT_HELP_GUIDANCE_NO_SKILLS",
        "MEMORY_GUIDANCE",
        "USER_PROFILE_GUIDANCE",
        "SESSION_SEARCH_GUIDANCE",
        "SKILLS_GUIDANCE",
        "TOOL_USE_ENFORCEMENT_GUIDANCE",
        "TOOL_USE_ENFORCEMENT_MODELS",
        "EXECUTION_GUIDANCE_MODELS",
        "TASK_COMPLETION_GUIDANCE",
        "PARALLEL_TOOL_CALL_GUIDANCE",
        "OPENAI_MODEL_EXECUTION_GUIDANCE",
        "GOOGLE_MODEL_OPERATIONAL_GUIDANCE",
        "STEER_MARKER_OPEN",
        "STEER_MARKER_CLOSE",
        "STEER_CHANNEL_NOTE",
        "DEVELOPER_ROLE_MODELS",
        "_MEDIA_NATIVE",
        "CONTEXT_FILE_MAX_CHARS",
        "CONTEXT_TRUNCATE_HEAD_RATIO",
        "CONTEXT_TRUNCATE_TAIL_RATIO",
        "_CONTEXT_FILE_CHARS_PER_TOKEN",
        "_CONTEXT_FILE_WINDOW_FRACTION",
        "_CONTEXT_FILE_DYNAMIC_CEILING",
        "_SKILLS_PROMPT_CACHE_MAX",
        "_SKILLS_SNAPSHOT_VERSION",
        "_WINDOWS_BASH_SHELL_HINT",
        "WSL_ENVIRONMENT_HINT",
    ],
    "agent/plan_prompt.py": ["_PLAN_MODE_RULES", "_PLAN_CRAFT"],
    "agent/learn_prompt.py": [
        "_AUTHORING_STANDARDS",
        "_KNOWLEDGE_SKILL_STANDARDS",
        "_SOURCE_HYGIENE",
    ],
}

# Deliberately NOT ported, with the reason recorded in the manifest so the
# gap is auditable instead of silent.
EXCLUDED = {
    "KANBAN_GUIDANCE": "kanban board protocol — Pulse has no kanban server or kanban_* tools",
    "PLATFORM_HINTS": "messenger/relay surfaces (Telegram/Discord/Signal/HUD) — Pulse ships IDE + CLI only",
    "TELEGRAM_RICH_MESSAGES_HINT": "Telegram rendering hint — no Telegram surface",
    "_LOCAL_CRON_DELIVERY_NOTE": "cron delivery — Pulse has no cron daemon",
    "hud_surface_note": "floating-HUD per-turn note — no HUD surface",
    "build_memory_guidance": "composed by hand in guidance.py from the MEMORY_GUIDANCE corpus entry",
    "execution_guidance_text": "re-implemented in guidance.py against Pulse's tool names",
}


def _encode(value):
    """JSON-serialise a lifted constant, preserving tuple/set identity.

    Tuples and frozensets matter here: the model-gating tuples
    (TOOL_USE_ENFORCEMENT_MODELS, EXECUTION_GUIDANCE_MODELS) are used with
    ``in``/``any`` and immutability is part of the upstream contract, so a
    silent tuple->list downgrade would be a fidelity loss.
    """
    if isinstance(value, (tuple, list)):
        return {"__tuple__": True, "items": [_encode(v) for v in value]} if isinstance(value, tuple) else [_encode(v) for v in value]
    if isinstance(value, (frozenset, set)):
        return {"__set__": True, "items": sorted(_encode(v) for v in value)}
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _upstream_meta(root: Path) -> dict:
    commit = ""
    when = ""
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        when = subprocess.run(
            ["git", "-C", str(root), "show", "-s", "--format=%cI", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:  # not a git checkout (e.g. a tarball) — pin by hash only
        pass
    return {"commit": commit, "commit_date": when, "repo": "NousResearch/hermes-agent"}


_STUB_MODULES = (
    "hermes_constants",
    "agent",
    "agent.runtime_cwd",
    "agent.skill_utils",
    "utils",
    "tools",
    "tools.threat_patterns",
)


class _StubFinder:
    """Import hook that answers ONLY the known-heavy upstream imports with stubs.

    ``agent/prompt_builder.py`` imports provider/skills machinery at module
    top-level that a lifting run does not need; any other import is left to the
    real importer so an unexpected dependency shows up as an error instead of
    being silently stubbed into a wrong constant.
    """

    def find_module(self, fullname, path=None):  # pragma: no cover - py<3.12 API
        return self if fullname in _STUB_MODULES else None

    def load_module(self, fullname):  # pragma: no cover - py<3.12 API
        return self._make(fullname)

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _STUB_MODULES:
            return None
        return importlib.machinery.ModuleSpec(fullname, self)

    def create_module(self, spec):
        return self._make(spec.name)

    def exec_module(self, module):
        return None

    @staticmethod
    def _make(name):
        mod = types.ModuleType(name)

        def _stub(*args, **kwargs):
            return None

        mod.__getattr__ = lambda attr: _stub  # type: ignore[attr-defined]
        return mod


def _lift(module_path: Path, names: list[str]) -> tuple[dict, list[str]]:
    """Lift the wanted top-level constants out of an upstream module.

    Runs the module with its heavy imports stubbed, then reads the values — so
    constants *computed* at module scope (``MEMORY_GUIDANCE`` via
    ``build_memory_guidance``, ``STEER_CHANNEL_NOTE`` via an f-string) are
    captured exactly as upstream builds them, not as a paraphrase. Anything the
    run cannot produce is reported as missed rather than guessed.
    """
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    out: dict[str, object] = {}
    missed: list[str] = []
    wanted = set(names)

    finder = _StubFinder()
    saved_path = list(sys.path)
    sys.meta_path.insert(0, finder)
    sys.path.insert(0, str(module_path.parent.parent))
    namespace: dict[str, object] = {"__name__": "hermes_port_lift", "__file__": str(module_path)}
    try:
        exec(compile(source, str(module_path), "exec"), namespace)  # noqa: S102 - pinned upstream source
    except Exception as exc:
        print(f"  exec fallback for {module_path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        sys.meta_path.remove(finder)
        sys.path[:] = saved_path

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                if target.id in namespace:
                    out[target.id] = namespace[target.id]
                    continue
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except Exception:
                    missed.append(target.id)
    for name in names:
        if name not in out and name not in missed:
            missed.append(name)
    return out, missed


def main(root: str) -> int:
    ref = Path(root).resolve()
    corpus: dict[str, dict] = {}
    files: dict[str, dict] = {}

    for rel, names in WANTED.items():
        path = ref / rel
        if not path.is_file():
            print(f"MISSING upstream module: {path}", file=sys.stderr)
            return 2
        source = path.read_text(encoding="utf-8")
        values, missed = _lift(path, names)
        if missed:
            print(f"{rel}: not liftable as literals: {sorted(set(missed))}", file=sys.stderr)
        files[rel] = {
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "lines": len(source.splitlines()),
            "lifted": sorted(values),
        }
        module_key = rel.split("/")[1].removesuffix(".py")
        entry = corpus.setdefault(module_key, {})
        for key, value in values.items():
            entry[key] = _encode(value)

    doc = {
        "provenance": {
            **_upstream_meta(ref),
            "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "extractor": "scripts/port_hermes_prompts.py",
            "note": (
                "Prompt text lifted verbatim from the pinned upstream checkout. "
                "Pulse applies ONLY the documented tool-name rename map at load "
                "time (see src/prompts/hermes/guidance.py). Nothing else is rewritten."
            ),
        },
        "files": files,
        "constants": corpus,
        "excluded": EXCLUDED,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(len(str(v)) for m in corpus.values() for v in m.values())
    print(f"wrote {OUT.relative_to(REPO)} — {sum(len(m) for m in corpus.values())} constants, {total} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
