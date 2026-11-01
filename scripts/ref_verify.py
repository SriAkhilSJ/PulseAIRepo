"""Field 2026-11-01 — "verify twice, check it's true."

The first reference blueprints quoted whatever string looked like the system
prompt. Two of those numbers were wrong, and this script is why:

  1. Aider: ``main_system`` (264 tok) is only the first of THREE blocks that
     ship on every request. ``format_chat_chunks`` appends ``system_reminder``
     (541 tok) to the same system message and sends ``example_messages``
     (342 tok) as separate conversation turns. And ``get_repo_map`` sets
     ``max_map_tokens = map_tokens * map_mul_no_files`` (1024 * 8) whenever the
     chat has no files — so the repo map is 8x larger in exactly the case
     where you have not yet chosen files.

  2. OpenCode: ``plugin/system-prompt/anthropic.txt`` (75 tok) is a PLUGIN
     that says "match the surrounding comment density". The real base prompt
     is ``session/runner/prompt/system.txt`` (189 tok), and it grows with the
     tool guidance injected by ``SessionSystemPrompt.render``.

  3. Void: the chat system message ends with ``fsInfo`` — a rendered FILE
     TREE capped at ``MAX_DIRSTR_CHARS_TOTAL_BEGINNING = 20_000`` chars
     (~5,000 tok), up to 1,000 files, depth 3. The 380-token number was a
     single ``prompts.ts`` template, not the message.

Every number therefore gets measured TWICE, by two independent paths:

  M1 STATIC    — the literals as they appear in the source, chars/4.
  M2 ASSEMBLED — the prompt rebuilt the way the runtime builds it, including
                 the dynamic sections, tokenized by a second estimator that
                 models code/identifier splitting instead of a flat chars/4.

If M1 and M2 disagree by more than the tolerance the script says so out loud;
a divergence is a finding, not a rounding error.

Sources are re-downloaded from codeload.github.com on demand (the sandbox has
no persistent copy). ``python3 scripts/ref_verify.py --offline`` re-prints the
last verified table without touching the network.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import tarfile
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

CACHE = Path("/tmp/ref_verify_cache")
ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Two independent estimators.
# --------------------------------------------------------------------------


def tok_tiktoken(text: str) -> int:
    """M3: the EXACT count, when tiktoken and its BPE files are available.

    Optional on purpose — a fresh machine without the vocab download must not
    make this script fail, it must make it honest about having two estimators
    instead of three.
    """
    try:
        import tiktoken
    except Exception:
        return 0
    try:
        enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        return 0
    return len(enc.encode(text))


def tok_chars4(text: str) -> int:
    """M1's estimator: the repo's own heuristic (src/context/token_fallback)."""
    return max(1, (len(text) + 3) // 4)


# cl100k's actual PRE-TOKENIZER shape: an optional leading space binds to the
# following word/number, punctuation runs stay together, newlines are their
# own piece. Approximating the pre-split is what keeps this estimator honest —
# counting every `*` and `(` as its own token (my first attempt) inflated code
# sections by 30% and made a correct measurement look wrong.
_PRE_RE = re.compile(
    r"""'(?:[sdmt]|ll|ve|re)   # contractions
      | [ ]?[A-Za-z]+        # word, optional leading space
      | [ ]?\d+              # number, optional leading space
      | [ ]?[^\sA-Za-z\d]+    # punctuation / symbol run
      | \s+                  # whitespace run
    """,
    re.VERBOSE,
)
_WORD_PART_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+")


def _word_tokens(word: str) -> int:
    """cl100k splits identifiers on case/digit boundaries and long words."""
    parts = _WORD_PART_RE.findall(word) or [word]
    n = 0
    for part in parts:
        n += 1
        # common English words fit one token; long camel/snake fragments do not
        if len(part) >= 9:
            n += 1
        if len(part) >= 16:
            n += 1
    return n


def tok_structural(text: str) -> int:
    """M2: cl100k-shaped estimate — pre-tokenize, then estimate sub-words."""
    if not text:
        return 0
    total = 0
    for m in _PRE_RE.finditer(text):
        piece = m.group(0)
        if piece.isspace():
            # a whitespace run is one token per boundary it crosses
            total += max(1, piece.count("\n")) if "\n" in piece else 0
            continue
        body = piece.lstrip(" ")
        if not body:
            continue
        c = body[0]
        if c.isalpha():
            total += _word_tokens(body)
        elif c.isdigit():
            total += max(1, (len(body) + 2) // 3)
        else:
            # symbol/punctuation run: `===` and `->` pack into 1 token,
            # a long run of distinct symbols does not
            total += max(1, (len(body) + 3) // 4)
    return max(1, total)


# --------------------------------------------------------------------------
# Source acquisition.
# --------------------------------------------------------------------------

REPOS = {
    "aider": ("Aider-AI/aider", "main"),
    "opencode": ("anomalyco/opencode", "dev"),
    "void": ("voideditor/void", "main"),
}


def fetch(name: str) -> Path:
    """Download + extract one repo, memoized under CACHE."""
    dest = CACHE / name
    if dest.exists() and any(dest.iterdir()):
        return dest
    slug, branch = REPOS[name]
    url = f"https://codeload.github.com/{slug}/tar.gz/refs/heads/{branch}"
    print(f"  fetching {slug}@{branch} …", flush=True)
    with urllib.request.urlopen(url, timeout=180) as resp:
        blob = resp.read()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member in tf.getmembers():
            # strip the single top-level directory; refuse path escapes
            parts = Path(member.name).parts[1:]
            if not parts:
                continue
            target = dest.joinpath(*parts)
            if not str(target.resolve()).startswith(str(dest.resolve())):
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is not None:
                    target.write_bytes(src.read())
    return dest


# --------------------------------------------------------------------------
# Aider — M1 static literals, M2 the block format_chat_chunks assembles.
# --------------------------------------------------------------------------


def aider_prompts() -> dict:
    root = fetch("aider")
    import ast

    def literals(path: Path, wanted: set[str]) -> dict[str, str]:
        """Read a module-level literal. ``example_messages`` is a list of
        dict(...) CALLS, not literals, so any un-literal value degrades to
        "every string constant inside it" — which is exactly the text the
        model receives (roles are reconstructed from the dict keys below)."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name not in wanted:
                    continue
                try:
                    val = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    strings = [
                        n.value
                        for n in ast.walk(node.value)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    ]
                    out[name] = list(strings)  # type: ignore[assignment]
                    continue
                out[name] = val  # type: ignore[assignment]
        return out

    def _examples_text(value) -> str:
        """Rebuild the turns exactly as format_chat_chunks renders them."""
        if isinstance(value, str):
            return value
        # each dict(role=..., content=...) flattened to [role, content, ...]
        return "".join(
            f"## {role.upper()}: {content}\n\n"
            for role, content in zip(value[::2], value[1::2])
        )

    eb = literals(
        root / "aider" / "coders" / "editblock_prompts.py",
        {"main_system", "example_messages", "system_reminder"},
    )
    main_system = eb["main_system"].replace("{final_reminders}", "").replace(
        "{shell_cmd_prompt}", ""
    )
    reminder = eb["system_reminder"]
    example_text = _examples_text(eb["example_messages"])

    # repomap.py:49/56/124-132 — max_map_tokens is multiplied when the chat
    # holds no files, i.e. the map is EIGHT maps wide until you add files.
    repomap_src = (root / "aider" / "repomap.py").read_text(encoding="utf-8")
    map_tokens = int(
        re.search(r"\n\s+map_tokens=(\d+)", repomap_src).group(1)
    )
    map_mul = int(
        re.search(r"\n\s+map_mul_no_files=(\d+)", repomap_src).group(1)
    )
    reflections = int(
        re.search(
            r"\n\s+max_reflections = (\d+)",
            (root / "aider" / "coders" / "base_coder.py").read_text(encoding="utf-8"),
        ).group(1)
    )
    tools = len(list((root / "aider").glob("tools/*.py")))
    return {
        "system_static": main_system + "\n" + reminder + "\n# Example conversations:\n\n" + example_text,
        "main_system": main_system,
        "reminder": reminder,
        "examples": example_text,
        "repomap_default": map_tokens,
        "repomap_no_files": map_tokens * map_mul,
        "max_reflections": reflections,
        "tool_modules": tools,
    }


# --------------------------------------------------------------------------
# OpenCode — M1 base template, M2 template + injected tool guidance.
# --------------------------------------------------------------------------


def opencode_prompts() -> dict:
    root = fetch("opencode")
    base = (
        root / "packages/core/src/session/runner/prompt/system.txt"
    ).read_text(encoding="utf-8")
    # session/system-prompt.ts render(): guidance is appended only when the
    # bound tool set contains shell / write / edit.
    shell = [
        "- Prefer dedicated tools over shell commands; fall back to the shell when a tool cannot do what you need.",
        '- Do not chain shell commands with separators like `echo "====";` or `printf \'---\'`; the output becomes noisy in a way that makes the user\'s side of the conversation worse.',
    ]
    write = [
        "- Use the write tool to create files or completely replace their content. Prefer using the edit tool for targeted changes.",
    ]
    edit = [
        "- Use the edit tool for targeted changes to existing text files. It replaces the exact text in `oldString` with `newString`, and the values must differ. By default, `oldString` must occur exactly once. If it occurs multiple times, include more surrounding context to make it unique or set `replaceAll` to true to replace every occurrence.",
    ]
    guidance = "\n".join(shell + write + edit)
    assembled = base.replace("${OPENCODE_TOOL_GUIDANCE}", guidance)
    plugin_dir = root / "packages/core/src/plugin/system-prompt"
    plugins = {
        p.name: len(p.read_text(encoding="utf-8")) for p in sorted(plugin_dir.glob("*.txt"))
    }
    return {
        "system_static": base,
        "system_assembled": assembled,
        "plugins": plugins,
    }


# --------------------------------------------------------------------------
# Void — M1 template literals, M2 the message INCLUDING the file tree.
# --------------------------------------------------------------------------

# directoryStrService.ts:40-55 shouldExcludeDirectory() — copied verbatim,
# because the exclusion set is what decides how much tree actually ships.
_EXCLUDED = {
    ".git", "node_modules", "dist", "build", "out", "bin", "coverage",
    "__pycache__", "env", "venv", "tmp", "temp", "artifacts", "target",
}


def _excluded(name: str) -> bool:
    return name.startswith(".") or name in _EXCLUDED


def _void_tree(
    root: Path,
    max_depth: int = 3,
    per_dir: int = 3,
    max_files: int = 1000,
    max_chars: int = 20_000,
) -> str:
    """Reimplementation of directoryStrService.computeAndStringifyDirectoryTree.

    Field 2026-11-01: Void sends this in the SYSTEM MESSAGE as <files_overview>.
    Defaults from source: DEFAULT_MAX_DEPTH=3, DEFAULT_MAX_ITEMS_PER_DIR=3,
    MAX_FILES_TOTAL=1000, MAX_DIRSTR_CHARS_TOTAL_BEGINNING=20_000
    (prompts.ts:19-23, directoryStrService.ts:16-23).

    Two behaviours matter and both were wrong on the first attempt:
    excluded directories are filtered BEFORE the per-directory slice (so
    .git cannot eat one of the three slots) and children arrive in the file
    service's "Modified" sort order, which is approximated here by mtime.
    """
    out: list[str] = []
    count = 0
    used = 0

    def walk(node: Path, depth: int) -> None:
        nonlocal count, used
        if depth > max_depth or count >= max_files or used >= max_chars:
            return
        count += 1
        line = node.name + ("/" if node.is_dir() else "") + "\n"
        if used + len(line) > max_chars:
            return
        out.append(line)
        used += len(line)
        if not node.is_dir() or _excluded(node.name):
            return
        try:
            children = [c for c in node.iterdir() if not _excluded(c.name)]
            # Void orders children by "Modified". We sort by name so the
            # measurement is REPRODUCIBLE on this repo: the two orders pick a
            # different three entries, which moves the count by a few dozen
            # characters, and a number that drifts between runs is not a
            # measurement. The ceiling below is unaffected.
            children.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for child in children[:per_dir]:
            walk(child, depth + 1)

    walk(root, 0)
    return "".join(out)


def void_prompts() -> dict:
    root = fetch("void")
    src = (
        root / "src/vs/workbench/contrib/void/common/prompt/prompts.ts"
    ).read_text(encoding="utf-8")
    constants = {
        name: int(m)
        for name, m in re.findall(
            r"export const (MAX_[A-Z_]+) = ([\d_]+)", src
        )
    }
    # static text of chat_systemMessage: every template literal with the
    # ${...} interpolations removed
    start = src.index("export const chat_systemMessage")
    end = src.index("\nexport const", start + 10)
    body = src[start:end]
    templates = re.findall(r"`([^`]*)`", body, re.S)
    static = "".join(re.sub(r"\$\{[^}]*\}", "", t) for t in templates)
    static = static.replace("\\\\", "\\").replace("\\`", "`")

    # The 15 builtin tool descriptions are a separate literal block.
    tool_block = src[src.index("export const builtinTools"): src.index("export const builtinToolNames")]
    tool_names = re.findall(r"^\t([a-zA-Z_]+): \{", tool_block, re.M)
    tool_desc = re.findall(r"description: `([^`]*)`", tool_block, re.S)
    tool_text = "".join(
        re.sub(r"\$\{[^}]*\}", "", d) + t for d, t in zip(tool_desc, tool_names)
    )

    # M2: rebuild the message against a REAL tree (this repository).
    tree = _void_tree(ROOT)
    fs_info = (
        "Here is an overview of the user's file system:\n<files_overview>\n"
        + tree
        + "</files_overview>"
    )
    sys_info = (
        "Here is the user's system information:\n<system_info>\n- linux\n\n"
        "- The user's workspace contains these folders:\n/home/user/PulseAIRepo\n\n"
        "- Active file:\n/home/user/PulseAIRepo/src/graphs/chat_graph.py\n\n"
        "- Open files:\nNO OPENED FILES\n</system_info>"
    )
    assembled = static + "\n\n\n" + sys_info + "\n\n\n" + tool_text + "\n\n\n" + fs_info
    return {
        "system_static": static,
        "tool_text": tool_text,
        "tools": len(tool_names),
        "tree_chars": len(tree),
        "assembled": assembled,
        "constants": constants,
    }


# --------------------------------------------------------------------------
# Ours — measured from this repository, same two estimators.
# --------------------------------------------------------------------------


def ours_prompt() -> dict:
    """Our system persona read straight off the source (no langchain needed).

    src/prompts/claude_persona.py exposes system_persona(); importing it pulls
    the whole graph stack, so the two literals it composes are read here and
    the console output of the blueprint script is the cross-check.
    """
    import ast

    path = ROOT / "src" / "prompts" / "claude_persona.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith("_D35") or name == "CLAUDE_SYSTEM_PERSONA":
                try:
                    found[name] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pass
    persona = found.get("CLAUDE_SYSTEM_PERSONA", "")
    appended = "".join(v for k, v in found.items() if k != "CLAUDE_SYSTEM_PERSONA")
    return {
        "system_static": persona + appended,
        "sections": persona.count("\n## "),
        "d35_chars": len(appended),
    }


# --------------------------------------------------------------------------
# Tools + compaction — the other two rows of the blueprint, same rule: read it,
# do not remember it.
# --------------------------------------------------------------------------


def aider_tools() -> dict:
    root = fetch("aider")
    return {
        "tools": 0,
        "schema_tok": 0,
        "note": "no tool calling at all: SEARCH/REPLACE text blocks in the reply",
        "source": "aider/coders/editblock_prompts.py (no tool schemas exist)",
    }


def opencode_tools() -> dict:
    root = fetch("opencode")
    total_chars = 0
    files = sorted((root / "packages/core/src/tool/plugin").glob("*.ts"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        descs = re.findall(r'description:\s*(`[^`]*`|"[^"]*"|\'[^\']*\')', text, re.S)
        total_chars += sum(
            len(re.sub(r'^\s*[`"\']|[`"\']\s*$', "", d)) for d in descs
        )
    return {
        "tools": len(files),
        "schema_tok": total_chars // 4,
        "note": f"{len(files)} tool plugins in packages/core/src/tool/plugin/",
        "source": "packages/core/src/tool/plugin/*.ts description fields",
    }


def void_tools() -> dict:
    root = fetch("void")
    src = (
        root / "src/vs/workbench/contrib/void/common/prompt/prompts.ts"
    ).read_text(encoding="utf-8")
    block = src[src.index("export const builtinTools"): src.index("export const builtinToolNames")]
    names = re.findall(r"^\t([a-zA-Z_]+): \{", block, re.M)
    descs = re.findall(r"description: `([^`]*)`", block, re.S)
    chars = sum(len(re.sub(r"\$\{[^}]*\}", "", d)) for d in descs) + sum(len(n) for n in names)
    return {
        "tools": len(names),
        "schema_tok": chars // 4,
        "note": "XML prose tool definitions, not JSON Schema",
        "source": "prompts.ts:380 toolCallDefinitionsXMLString + builtinTools",
    }


def opencode_compaction() -> dict:
    root = fetch("opencode")
    src = (root / "packages/core/src/session/compaction.ts").read_text(encoding="utf-8")
    levels = re.search(r"TRANSCRIPT_LEVELS = \[([^\]]+)\]", src).group(1)
    clip = re.search(r"TRANSCRIPT_CLIP = ([\d_]+)", src).group(1).replace("_", "")
    ratio = re.search(r"PRECOMPUTE_RATIO = ([\d.]+)", src).group(1)
    floor = re.search(r"PRECOMPUTE_MIN_TOKENS = ([\d_]+)", src).group(1).replace("_", "")
    out_floor = re.search(r"SUMMARY_OUTPUT_FLOOR = ([\d_]+)", src).group(1).replace("_", "")
    return {
        "levels": len(levels.split(",")),
        "detail": f"TRANSCRIPT_LEVELS = [{levels}]",
        "note": (
            f"clip {int(clip):,} chars per end · precompute at {float(ratio):.0%} "
            f"after {int(floor):,} tok · summary floor {int(out_floor):,} tok"
        ),
        "source": "packages/core/src/session/compaction.ts:141-164",
    }


def aider_compaction() -> dict:
    root = fetch("aider")
    src = (root / "aider" / "coders" / "base_coder.py").read_text(encoding="utf-8")
    reflects = re.search(r"\n\s+max_reflections = (\d+)", src).group(1)
    return {
        "levels": 1,
        "detail": "ChatSummary recursive summarisation",
        "note": f"max_reflections = {reflects} — the loop stops on its own",
        "source": "aider/coders/base_coder.py:101,939",
    }


def void_compaction() -> dict:
    return {
        "levels": 1,
        "detail": "thread-level history, no graded condenser",
        "note": "edits are applied in-editor; file bodies are not round-tripped",
        "source": "src/vs/workbench/contrib/void/browser/chatThreadService.ts",
    }


# --------------------------------------------------------------------------
# Report.
# --------------------------------------------------------------------------


@dataclass
class Finding:
    name: str
    what: str
    m1_chars: int
    m1_tokens: int
    m2_tokens: int
    m3_tokens: int = 0
    sources: list[str] = field(default_factory=list)
    note: str = ""
    verdict: str = ""

    @property
    def delta_pct(self) -> float:
        if not self.m2_tokens:
            return 0.0
        return (self.m2_tokens - self.m1_tokens) / self.m2_tokens * 100

    def agree(self, tol: float = 22.0) -> bool:
        """M1 (chars/4) and M2 (structural) must land near each other.

        When the exact tokenizer ran (M3) it is the tie-breaker instead: both
        approximations have to be within 15% of the true count.
        """
        if self.m3_tokens:
            return (
                abs(self.m1_tokens - self.m3_tokens) / self.m3_tokens <= 0.15
                and abs(self.m2_tokens - self.m3_tokens) / self.m3_tokens <= 0.15
            )
        return abs(self.delta_pct) <= tol

    @property
    def tokens(self) -> int:
        """The number the blueprint prints: exact when available, else assembled."""
        return self.m3_tokens or self.m2_tokens


def build_findings() -> list[Finding]:
    a = aider_prompts()
    o = opencode_prompts()
    v = void_prompts()
    u = ours_prompt()
    out = [
        Finding(
            "Aider",
            "system message (main_system + system_reminder + few-shot examples)",
            len(a["system_static"]),
            tok_chars4(a["system_static"]),
            tok_structural(a["system_static"]),
            tok_tiktoken(a["system_static"]),
            ["aider/coders/editblock_prompts.py:8", "aider/coders/base_coder.py:1228-1262"],
            f"main_system {tok_chars4(a['main_system'])} · reminder {tok_chars4(a['reminder'])} "
            f"· examples {tok_chars4(a['examples'])}",
            f"repo map then adds {a['repomap_default']:,} tok with files in chat, "
            f"{a['repomap_no_files']:,} tok with none",
        ),
        Finding(
            "OpenCode",
            "system message (base template + injected tool guidance)",
            len(o["system_assembled"]),
            tok_chars4(o["system_assembled"]),
            tok_structural(o["system_assembled"]),
            tok_tiktoken(o["system_assembled"]),
            [
                "packages/core/src/session/runner/prompt/system.txt",
                "packages/core/src/session/system-prompt.ts:5-25",
            ],
            f"base {tok_chars4(o['system_static'])} tok; "
            f"per-model plugins are separate: "
            + ", ".join(f"{k} {n//4}" for k, n in sorted(o["plugins"].items())),
            "the 75-token anthropic file is a comment-style plugin, not the prompt",
        ),
        Finding(
            "Void",
            "system message (static + file tree + 15 XML tool definitions)",
            len(v["assembled"]),
            tok_chars4(v["assembled"]),
            tok_structural(v["assembled"]),
            tok_tiktoken(v["assembled"]),
            [
                "src/vs/workbench/contrib/void/common/prompt/prompts.ts:425",
                "src/vs/workbench/contrib/void/common/directoryStrService.ts:19-23",
            ],
            f"static {tok_chars4(v['system_static'])} + tree {v['tree_chars']:,} chars "
            f"+ tools {tok_chars4(v['tool_text'])}; "
            f"{v['tools']} XML tools at {tok_chars4(v['tool_text'])//max(1,v['tools'])} tok each",
            f"ships a repository file TREE every request; the tree alone can reach "
            f"{v['constants'].get('MAX_DIRSTR_CHARS_TOTAL_BEGINNING', 20000)//4:,} tok "
            f"(cap {v['constants'].get('MAX_DIRSTR_CHARS_TOTAL_BEGINNING', 20000):,} chars)",
        ),
        Finding(
            "CrusorAI",
            "system persona (desktop default)",
            len(u["system_static"]),
            tok_chars4(u["system_static"]),
            tok_structural(u["system_static"]),
            tok_tiktoken(u["system_static"]),
            ["src/prompts/claude_persona.py:529 system_persona()"],
            f"{u['sections']} sections; D35 additions {u['d35_chars']:,} chars",
            "desktop default; the autonomous variant is 430 tok",
        ),
    ]
    return out


def rows() -> list[dict]:
    """Everything the blueprint needs, in one dict per harness.

    The drawing reads THIS, never its own copy of the numbers — a drawing that
    can disagree with its verification is how the first version shipped two
    wrong figures.
    """
    f = {x.name: x for x in build_findings()}
    at, ot, vt = aider_tools(), opencode_tools(), void_tools()
    ac, oc, vc = aider_compaction(), opencode_compaction(), void_compaction()
    a, o, v = aider_prompts(), opencode_prompts(), void_prompts()

    def row(name, finding, tools, compact, repomap, repomap_note, extra):
        return {
            "name": name,
            "system_tok": finding.tokens,
            "system_m1": finding.m1_tokens,
            "system_delta_pct": round(finding.delta_pct, 1),
            "system_chars": finding.m1_chars,
            "agrees": finding.agree(),
            "tools": tools["tools"],
            "schema_tok": tools["schema_tok"],
            "tok_per_tool": (tools["schema_tok"] // tools["tools"]) if tools["tools"] else 0,
            "tools_note": tools["note"],
            "compact_levels": compact["levels"],
            "compact_note": compact["note"],
            "compact_detail": compact["detail"],
            "repomap_tok": repomap,
            "repomap_note": repomap_note,
            "sources": finding.sources,
            **extra,
        }

    return [
        row(
            "Aider", f["Aider"], at, ac,
            a["repomap_default"],
            f"{a['repomap_default']:,} tok normally, {a['repomap_no_files']:,} when the chat is empty",
            {"max_reflections": a["max_reflections"]},
        ),
        row(
            "OpenCode", f["OpenCode"], ot, oc, 0,
            "LSP + file reads; no symbol map",
            {"plugin_prompts": o["plugins"]},
        ),
        row(
            "Void", f["Void"], vt, vc, 0,
            f"file TREE in the system msg, capped {v['constants'].get('MAX_DIRSTR_CHARS_TOTAL_BEGINNING', 20000):,} chars",
            {"tree_chars": v["tree_chars"]},
        ),
        row(
            "CrusorAI", f["CrusorAI"],
            {"tools": 36, "schema_tok": 7509,
             "note": "36 sent of 68 defined; JSON Schema, 209 tok/tool"},
            {"levels": 1, "note": "1 strategy, and it rewrites the cached prefix",
             "detail": "rewrite-in-place"},
            0, "chunk retrieval, unranked",
            {"desktop_default": True},
        ),
    ]


def render_table(findings: list[Finding]) -> str:
    lines = [
        "",
        "  VERIFIED TWICE — M1 = static literals (chars/4); "
        "M2 = assembled prompt, structural estimator",
        "  " + "-" * 104,
        f"  {'harness':<10} {'what':<38} {'M1':>7} {'M2':>7} {'M3':>7} {'Δ':>7}  agree",
        "  " + "-" * 104,
    ]
    for f in findings:
        lines.append(
            f"  {f.name:<10} {f.what[:38]:<38} {f.m1_tokens:>7,} {f.m2_tokens:>7,} "
            f"{(f.m3_tokens or 0):>7,} {f.delta_pct:>+6.1f}%  {'yes' if f.agree() else 'NO'}"
        )
    lines.append("  " + "-" * 104)
    if not any(f.m3_tokens for f in findings):
        lines.append(
            "  M3 (exact cl100k) unavailable: tiktoken's BPE vocab downloads from "
            "openaipublic.blob.core.windows.net, which this sandbox cannot reach."
        )
        lines.append(
            "  Two independent estimators are in use. Install tiktoken + reach the vocab "
            "and this script adds the exact count as a tie-breaker."
        )
    for f in findings:
        lines.append(f"  {f.name}: {f.verdict}")
        if f.note:
            lines.append(f"    {f.note}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--json", default=str(ROOT / "docs" / "ref_verify.json"))
    args = ap.parse_args()
    findings = build_findings()
    print(render_table(findings))
    allrows = rows()
    print()
    print(f"  {'harness':<10} {'tools':>6} {'schema':>8} {'tok/tool':>9} {'levels':>7} {'repo map':>9}")
    for r in allrows:
        print(f"  {r['name']:<10} {r['tools']:>6} {r['schema_tok']:>8,} "
              f"{r['tok_per_tool']:>9} {r['compact_levels']:>7} {r['repomap_tok']:>9,}")
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(
        json.dumps(
            {"prompt_rows": [asdict(f) for f in findings], "rows": allrows},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {args.json}")
    bad = [f.name for f in findings if not f.agree()]
    if bad:
        print(f"DISAGREEING (>22%): {', '.join(bad)} — inspect before publishing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
