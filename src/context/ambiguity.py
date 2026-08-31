"""P10: task-ambiguity detection.

Two paths, one contract ("never encode on a deadline-bound turn"):

- ``detect_ambiguity_advanced`` — embedding similarity against a small
  fixed hint vocabulary (D2: the 26 constant hint strings are
  content-addressed in the embedding cache, so steady-state turns cost
  one encode). Enabled ONLY when the explicit offline policy flag is on;
  any embedder failure falls back to the heuristic.
- ``detect_ambiguity_fallback`` — deterministic vague/specific keyword
  heuristic. The default path for deadline-bound turns.

The engine keeps ``_detect_ambiguity_advanced`` / ``_detect_ambiguity_fallback``
as thin delegates (pinned by ``test_embedding_cache.py``); the
D27-registered ``_ambiguity_layer`` builder calls the delegate, so the
build path is untouched.
"""

from typing import Optional

from langchain_core.messages import SystemMessage

# Advanced-path hint vocabulary (26 constants + the live task string).
AMBIGUOUS_HINTS = [
    "fix it", "make it better", "improve", "update", "refactor",
    "optimize", "clean up", "debug", "solve", "handle this",
]
SPECIFIC_HINTS = [
    "file", "function", "class", "method", "module",
    "create", "add", "delete", "rename", "move",
    "test", "bug", "error", "line", "import", "path",
]

# Fallback-path keyword vocabulary (substring match on lowercased task).
VAGUE_HINTS = [
    "fix it", "make it better", "improve", "update", "refactor",
    "optimize", "clean up", "debug", "solve", "handle this",
    "do it", "change it", "check it", "look at it",
]
SPECIFIC_KEYWORDS = [
    "file", "function", "class", "method", "module",
    "create", "add ", "delete", "rename", "move ",
    "test", "bug", "error", "line ", "import ",
    "path", "directory", "folder", "install",
]

AMBIGUITY_ALERT_ADVANCED = (
    "=== AMBIGUITY ALERT ===\n"
    "The current task appears vague or underspecified.\n\n"
    "Before acting, the agent should consider:\n"
    "- Which specific file, function, or module needs attention?\n"
    "- What does 'better' or 'fixed' mean in this context?\n"
    "- Are there tests, examples, or docs that clarify the goal?\n\n"
    "If the task remains unclear after checking available context, "
    "use ask_user() to get clarification rather than making assumptions."
)

AMBIGUITY_ALERT_FALLBACK = (
    "=== AMBIGUITY ALERT ===\n"
    "The current task appears vague or underspecified. "
    "Consider clarifying before acting."
)


def detect_ambiguity_advanced(
    task: str,
    allow_embedding_compute: bool,
) -> Optional[SystemMessage]:
    if not allow_embedding_compute:
        # Deadline-bound turns use the deterministic heuristic — the
        # advanced path encodes the task, which must never happen during
        # context preparation.
        return detect_ambiguity_fallback(task)

    try:
        from src.llm.factory import get_embedder
        embedder = get_embedder()
        # D2: 26 of these 27 strings are module constants — re-encoding
        # them every single turn was the purest waste in the engine.
        from src.context.embedding_cache import get_embedding_cache
        vecs = get_embedding_cache().encode(
            embedder, [task] + AMBIGUOUS_HINTS + SPECIFIC_HINTS
        )
        task_emb = vecs[0]
        amb_embs = vecs[1 : 1 + len(AMBIGUOUS_HINTS)]
        spec_embs = vecs[1 + len(AMBIGUOUS_HINTS):]

        amb_sim = max(sum(a * b for a, b in zip(task_emb, e)) for e in amb_embs)
        spec_sim = max(sum(a * b for a, b in zip(task_emb, e)) for e in spec_embs)

        if amb_sim > 0.55 and spec_sim < 0.50:
            return SystemMessage(content=AMBIGUITY_ALERT_ADVANCED)
        return None
    except Exception:
        # Fallback to original heuristic if embedder fails
        return detect_ambiguity_fallback(task)


def detect_ambiguity_fallback(task: str) -> Optional[SystemMessage]:
    has_vague = any(v in task.lower() for v in VAGUE_HINTS)
    has_specific = any(s in task.lower() for s in SPECIFIC_KEYWORDS)
    if has_vague and not has_specific:
        return SystemMessage(content=AMBIGUITY_ALERT_FALLBACK)
    return None
