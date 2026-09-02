"""``/plan`` and ``/learn`` prompt builders — ports of ``agent/plan_prompt.py``
and ``agent/learn_prompt.py``.

Both are *turn prompts*, not system-prompt mutations: upstream's rule is that
these commands never edit the system prompt or the history, precisely so the
cached prefix survives them. Pulse has the same two surfaces (execution mode
``plan``, and a skill-authoring flow), so the builders land on the same
separation.
"""
from __future__ import annotations

import datetime
import re
from typing import Iterable, Optional

from src.prompts.hermes import guidance

PLAN_DIR = ".pulseai/plans"  # upstream: .hermes/plans (same relative-path rule)
SKILL_DIR = ".pulseai/skills"  # upstream writes through skill_manage


#: Upstream's authoring standards carry Hermes's own worked examples, including
#: a list of illustrative tool names. Injecting that list verbatim would teach a
#: Pulse skill to reach for tools this runtime does not have (`terminal`,
#: `vision_analyze`, `image_generate`, `skill_manage`), so the examples are
#: retargeted at Pulse's registry — a documented substitution table, not a
#: rewrite: the sentence shapes and every other word stay upstream's.
#: Upstream's authoring standards carry Hermes's own worked examples, including
#: a bullet that enumerates the tools a skill should name. Injected verbatim it
#: would teach a Pulse skill to reach for tools this runtime does not have, so
#: the enumeration is replaced by Pulse's real registry (same bullet shape, same
#: purpose) and the remaining aliases map onto real tools.
_PULSE_REFERENCE_BULLET = (
    "- Reference Pulse tools by name in backticks: `run_terminal`, `read_file`,\n"
    "  `write_file`, `search_code`, `edit_file`, `web_fetch`, `web_search`,\n"
    "  `browser_navigate`, `browser_snapshot`, `delegate_to_subagent`, `execute_code`.\n"
)

_REFERENCE_BULLET_RE = re.compile(
    r"- Reference (?:Hermes|Pulse) tools by name in backticks:.*?`execute_code`\.\n",
    re.DOTALL,
)

TOOL_EXAMPLE_REWRITES: tuple[tuple[str, str], ...] = (
    ("extend it (`skill_manage` patch / write_file)", "extend it with `write_file`"),
    ("(`skill_manage` patch / write_file)", "(patched with `write_file`)"),
    ("add supporting files with `skill_manage` write_file", "add supporting files with `write_file`"),
    ("per-chapter `references/` files added with `skill_manage` write_file", "per-chapter `references/` files"),
    ("`skill_manage` write_file", "`write_file`"),
    ('create one with `skill_manage` action="create"', "create one with `write_file`"),
    ("load it with `skill_view`, then", "read it, then"),
    ("`patch`", "`edit_file`"),
    ("skill_manage", "write_file"),
    ("skill_view", "read_file"),
)


def retarget_upstream_tools(text: str) -> str:
    """Map the corpus's illustrative tool references onto Pulse's registry."""
    text = _REFERENCE_BULLET_RE.sub(_PULSE_REFERENCE_BULLET, text, count=1)
    for src, dst in TOOL_EXAMPLE_REWRITES:
        text = text.replace(src, dst)
    return text


def _slug(text: str, limit: int = 48) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (cleaned[:limit].rstrip("-")) or "plan"


def plan_target_path(task: str = "", now: Optional[datetime.datetime] = None) -> str:
    """``.pulseai/plans/YYYY-MM-DD_HHMMSS-<slug>.md`` — same shape as upstream."""
    stamp = (now or datetime.datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    return f"{PLAN_DIR}/{stamp}-{_slug(task)}.md"


def build_plan_prompt(task: str = "", *, target_path: Optional[str] = None) -> str:
    """Build the plan-mode prompt for the live agent.

    ``task`` empty means "plan from the current conversation context" (the same
    contract upstream restored in #36821).
    """
    task = (task or "").strip()
    if task:
        task_block = f"Task to plan:\n{task}\n"
    else:
        task_block = (
            "No explicit task was given with /plan — infer the task from the "
            "current conversation context (the thing we have been discussing "
            "or working toward). If the conversation does not imply a task, "
            "ask a brief clarifying question.\n"
        )

    rules = guidance.PLAN_MODE_RULES.replace(".hermes/plans/", f"{PLAN_DIR}/")
    if target_path:
        rules = (
            rules
            .replace(
                "If the runtime provides a specific target path, use that exact path instead.",
                f"Write the plan to this exact path: {target_path}",
            )
        )
    return (
        "[/plan — plan mode]\n\n"
        + rules
        + "\n"
        + task_block
        + "\n"
        + guidance.PLAN_CRAFT
        # Pulse-specific surface contract, appended after the frozen corpus text for the same reason the
        # `.hermes/plans` -> `.pulseai/plans` swap is: upstream's rules are compared byte-for-byte against
        # `upstream_corpus.json`, and this is our UI, not theirs. In the CLI a plan is invisible until you
        # open the file (the turn shows a tool count and nothing else). The desktop panel has a PLAN
        # inspector that reads the graph's plan state, so a plan that lives only in a file paints `0
        # steps` -- an artifact the user cannot see is a worse plan. Mirror it once, after writing.
        + PLAN_SURFACE_CONTRACT
    )


PLAN_SURFACE_CONTRACT = (
    "\n"
    "## Surface contract\n\n"
    "After saving the plan file, call `plan_update` once with the SAME steps as\n"
    '`{"description": "...", "status": "pending"}` objects, in order, so the desktop\n'
    "plan inspector shows what you wrote. Write the file first, then mirror it; do not\n"
    "call `plan_update` before the file exists, and do not maintain two lists — the file\n"
    "is the plan, the list is its display.\n"
)


_LEARN_INTRO = (
    "[/learn] The user wants you to learn a reusable skill from the "
    "request below, and save it.\n\n"
)

_LEARN_REQUEST_FRAME = (
    "The request is open-ended and may mix two kinds of content, in any "
    "order: SOURCES to gather (directories, file paths, URLs, \"what we "
    "just did\", pasted notes) AND REQUIREMENTS that shape the skill "
    "(what to focus on, what to leave out, scope, naming, the angle to "
    "take). Treat EVERY part of the request as load-bearing. In "
    "particular, prose that comes after a path or link is NOT incidental "
    "— it is the user telling you what they want from that source. A "
    "request like `<url> focus on the auth flow, skip the deprecated "
    "endpoints` means: gather the URL AND honor \"focus on auth, skip "
    "deprecated\" as authoring requirements. Never fetch the first source "
    "and ignore the rest.\n\n"
)

_LEARN_DEFAULT_REQUEST = (
    "the workflow we just went through in this conversation — review "
    "the steps taken and distill them into a reusable skill"
)


def build_learn_prompt(
    user_request: str,
    *,
    valid_tool_names: Optional[Iterable[str]] = None,
) -> str:
    """Build the agent prompt for an open-ended ``/learn`` request.

    With upstream's skill tools bound the body is upstream's, verbatim except
    the documented rename map. Without them — the Pulse default, where skills
    are files the runtime reads rather than a model-facing tool — only the
    *save* step changes: the agent writes ``SKILL.md`` with ``write_file`` and
    nothing else is reworded.
    """
    req = (user_request or "").strip() or _LEARN_DEFAULT_REQUEST
    names = None if valid_tool_names is None else {str(t) for t in valid_tool_names}
    has_skill_tools = bool(names) and {"skill_manage", "skill_view"} <= (names or set())
    # With upstream's skill tools bound the body is upstream's bytes; without
    # them the illustrative tool references are retargeted at real Pulse tools.
    rewrite = (lambda value: value) if has_skill_tools else retarget_upstream_tools

    body = (
        _LEARN_INTRO
        + f"THE REQUEST:\n{req}\n\n"
        + _LEARN_REQUEST_FRAME
        + "Do this:\n"
        "1. Inventory every source the user named, using the tools you already "
        "have — `read_file`/`search_code` for local files or directories, "
        "`web_fetch` for URLs, the current conversation history if they "
        "referred to something you just did, and the text they pasted as-is. "
        "Gather a small source now. For a large source, inspect enough to map "
        "its chapters or major topics, but do not load the whole corpus into "
        "conversation context; process it incrementally in step 2b. "
        "If the request is ambiguous about scope, make a reasonable choice "
        "and note it; do not stall.\n"
        "1b. Apply every requirement, focus, and constraint in the request to "
        "the skill you author — these govern what the SKILL.md covers and "
        "emphasizes, not just which sources you read.\n"
    )

    if has_skill_tools:
        body += (
            "2. Save the skill with `skill_manage`. First check the available "
            "skills for one covering this source or topic. If one exists, load it "
            "with `skill_view`, then extend its SKILL.md with `skill_manage` patch "
            "(or edit for a necessary full rewrite) and add or update supporting "
            "files with `skill_manage` write_file. Only when no matching skill "
            "exists, create one with `skill_manage` action=\"create\" and pick a "
            "sensible category. If the procedure needs a non-trivial script, add "
            "it under the skill's `scripts/` with `skill_manage` write_file and "
            "reference it by relative path.\n"
        )
    else:
        body += (
            "2. Save the skill as a file. First check the skill index in your "
            "prompt for one covering this source or topic; if one exists, extend "
            "that file instead of creating a rival. Otherwise write "
            f"`{SKILL_DIR}/<category>/<name>/SKILL.md` with `write_file`, YAML "
            "frontmatter carrying `name`, `description` and `category`, and a "
            "procedure body a future session can follow without this "
            "conversation. If the procedure needs a non-trivial script, write it "
            f"under `{SKILL_DIR}/<category>/<name>/scripts/` and reference it by "
            "relative path.\n"
        )

    body += (
        "2b. Pick the shape by the source, not by habit: a workflow or small "
        "source gets ONE tight SKILL.md; a book, paper stack, spec, or large "
        "docs corpus gets the knowledge-base layout below — a lean SKILL.md "
        "index plus per-chapter `references/` files. If a single SKILL.md would "
        "force you to summarize away most of the material, that is the signal to "
        "go expansive. For this layout, create or load the skill after "
        "inventorying the source, then read, distill, and persist one "
        "chapter/topic at a time before reading the next; finish by reconciling "
        "the SKILL.md index with every reference file you wrote.\n\n"
        + rewrite(guidance.LEARN_SOURCE_HYGIENE)
        + "\n\n"
        + rewrite(guidance.LEARN_AUTHORING_STANDARDS)
        + "\n\n"
        + rewrite(guidance.LEARN_KNOWLEDGE_SKILL_STANDARDS)
        + "\n\n"
        "When done, tell the user the skill name, its category, a one-line "
        "summary of what it captured, and — for a knowledge-base skill — the "
        "list of reference files it can load on demand."
    )
    return body


__all__ = [
    "PLAN_DIR",
    "SKILL_DIR",
    "build_learn_prompt",
    "plan_target_path",
    "build_plan_prompt",
    "retarget_upstream_tools",
]
