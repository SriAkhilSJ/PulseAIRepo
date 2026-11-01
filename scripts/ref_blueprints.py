"""Reference-implementation blueprints — the same body, five other ways.

Field 2026-11-01. Rather than repeat blog claims, each repo was downloaded from
codeload.github.com and the numbers below were read out of its source. Every
entry names the file the constant came from, so the claim is checkable:

    Aider-AI/aider      main    prompts.py + coders/*_prompts.py + repomap.py
    anomalyco/opencode  dev     core/src/session/compaction.ts + plugin/system-prompt/
    openai/codex        main    codex-rs/core/*.md + core/src/tools/ + utils/pty
    voideditor/void     main    contrib/void/common/prompt/prompts.ts
    Twigpine/openclaude main    src/constants/prompts.ts + services/compact/*

Token counts are chars/4 — the same estimator this repo uses everywhere else, so
our numbers and theirs are computed the same way and are directly comparable.

    python scripts/ref_blueprints.py   -> docs/ref_blueprints.svg + .html
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_core_blueprint import (  # noqa: E402
    ACCENT,
    BAD,
    BG,
    CARD,
    INK,
    LINE,
    MUTED,
    NODE_H,
    NODE_W,
    OK,
    SOURCE,
    WARN,
    Flow,
    esc,
    measure,
)

TOK = lambda chars: chars // 4  # noqa: E731

# ── our own measured numbers, for the comparison column ────────────────────
OURS = {
    "name": "CrusorAI (ours)",
    "system": 6151,  # system_persona() default, 24,606 chars / 17 sections
    "system_auto": 430,  # system_persona(autonomous=True)
    "tools_sent": 36,
    "tools_defined": 68,
    "tools": 36,
    "schema_tok": 7509,
    "repomap": 0,
    "tool_result_tok": 3000,  # 12,000 chars
    "tool_result": "12,000 chars (~3,000 tok)",
    "compact": 1,
    "compact_levels": 1,
    "cache_stable": "no — compaction rewrites the prefix",
    "cache": "gateway implicit only; 39–53%",
    "repomap_note": "chunk retrieval, unranked",
    "compact_note": "1 strategy, rewrites the prefix",
    "steal": "n/a — this is us",
    "system_note": "6,151 desktop · 430 autonomous",
    "cycle_budget": 45,
    "money_cap": "off by default",
    "cost_per_completed": "236k tok (~$0.036)",
    "budget": "45 cycles; money leg off",
    "verdict": "correct, stable, unaffordable: 45% of every cycle is fixed preamble",
}

# ── the five, measured from source ────────────────────────────────────────
REFS = [
    {
        "name": "Aider",
        "repo": "Aider-AI/aider",
        "lang": "Python",
        "source": "aider/prompts.py, aider/coders/*_prompts.py, aider/repomap.py",
        "system": 264,
        "system_note": "264–420 tok depending on edit format (editblock 264, patch 277, context 420)",
        "tools": 0,
        "schema_tok": 0,
        "repomap": 1024,
        "repomap_note": "map_tokens=1024 default, binary-searched to fit; PageRank over tree-sitter tags",
        "tool_result": "in-chat /add only",
        "compact": 1,
        "compact_note": "ChatSummary recursive summarisation of older turns",
        "cache": "n/a — no tool preamble to cache",
        "budget": "max_reflections, /tokens control",
        "verdict": "cheapest possible loop: 0 tool schemas, ~300 tok of instructions, 1k repo map",
        "steal": "the repo map. 1–4k tokens buys whole-repo awareness instead of 8 file dumps",
    },
    {
        "name": "OpenCode",
        "repo": "anomalyco/opencode",
        "lang": "TypeScript · 223k★",
        "source": "core/src/session/compaction.ts, core/src/plugin/system-prompt/*.txt",
        "system": 643,
        "system_note": "per model family: anthropic 75 · gpt 643 · kimi 2,175 · meta 1,963",
        "tools": "plugin",
        "schema_tok": None,
        "repomap": 0,
        "repomap_note": "LSP + file reads; no symbol map",
        "tool_result": "2,000-char clip per end when summarising",
        "compact": 5,
        "compact_note": "5 graded levels: whole → outputs clipped → outputs removed → user-only → omitted",
        "cache": "background precompute at 85% of ceiling, tail 30k–25%",
        "budget": "steps per agent (config)",
        "verdict": "best compaction in the set — it degrades the transcript instead of rewriting it",
        "steal": "graded compaction levels + background summarisation before you hit the wall",
    },
    {
        "name": "Codex CLI",
        "repo": "openai/codex",
        "lang": "Rust · 9.8k files",
        "source": "codex-rs/core/*prompt.md, core/src/compact.rs, utils/pty/src/lib.rs",
        "system": 1661,
        "system_note": "model-tuned: codex 1,661–1,897 tok; generic 5,413 tok",
        "tools": 6,
        "schema_tok": None,
        "repomap": 0,
        "repomap_note": "AGENTS.md only, capped by project_doc_max_bytes (truncated)",
        "tool_result": "1 MiB pty cap + delta streaming (DEFAULT_OUTPUT_BYTES_CAP)",
        "compact": 3,
        "compact_note": "auto + remote v2 + mid-turn; compact prompt is 106 tok",
        "cache": "provider implicit; stable prefix by design",
        "budget": "max turns; 20k token cap on the compaction user message",
        "verdict": "smallest surface: ~6 structured tools, one 1.7k prompt, hard byte caps",
        "steal": "byte-capped tool output as a FIRST-CLASS constant, not a suggestion",
    },
    {
        "name": "Void",
        "repo": "voideditor/void",
        "lang": "TypeScript · VS Code fork",
        "source": "contrib/void/common/prompt/prompts.ts",
        "system": 380,
        "system_note": "9.5k tok of prompt TEXT total, but per-task: regex-edit 378, commit 197",
        "tools": 0,
        "schema_tok": 0,
        "repomap": 0,
        "repomap_note": "context-gathering service pulls files on demand",
        "tool_result": "editor diff applied in-editor",
        "compact": 1,
        "compact_note": "thread-level history, no graded condenser",
        "cache": "in-editor apply; no re-send of file bodies",
        "budget": "per-request caps",
        "verdict": "applies edits in the editor instead of round-tripping file contents",
        "steal": "task-scoped prompts (378 tok for an edit) instead of one 6k persona for everything",
    },
    {
        "name": "openclaude",
        "repo": "Twigpine/openclaude",
        "lang": "TypeScript · 34k★",
        "source": "src/constants/prompts.ts, src/services/compact/*.ts, src/tools/",
        "system": 7000,
        "system_note": "55kB of composed sections; getSystemPromptSection cache",
        "tools": 56,
        "schema_tok": None,
        "repomap": 0,
        "repomap_note": "RepoMapTool exists (opt-in)",
        "tool_result": "20k token cap on the summary; micro-compaction of tool history",
        "compact": 8,
        "compact_note": "auto / micro / snip / reactive / sessionMemory / apiMicro — 8 modules",
        "cache": "AUTOCOMPACT_BUFFER 30k, floor 13k, warning 20k, failure cooldown 10s",
        "budget": "maxTurns (configurable)",
        "verdict": "closest to us in prompt size, furthest ahead in compaction machinery",
        "steal": "compaction is a family of strategies with explicit token buffers, not one function",
    },
]

ROWS = [
    ("System message (tok)", lambda r: f"{r['system']:,}"),
    ("Tool schemas (tok/cycle)", lambda r: f"{r['schema_tok']:,}" if r["schema_tok"] else (
        "0" if r["tools"] == 0 else "plugin/none")),
    ("Tools sent", lambda r: str(r["tools"])),
    ("Repo map (tok)", lambda r: f"{r['repomap']:,}" if r["repomap"] else "—"),
    ("Tool result cap", lambda r: r["tool_result"]),
    ("Compaction strategies", lambda r: str(r["compact"])),
    ("Cache strategy", lambda r: r["cache"]),
    ("Steal this", lambda r: r["steal"]),
]


def render() -> str:
    m = measure()
    row_h = 112
    top = 196
    W = 1600
    # height: the five reference rows, our row, then the three-differences block
    H = top + len(REFS) * (row_h + 26) + (row_h + 40) + (row_h + 40) + 200
    f = Flow(W, H)
    f.grid()

    f.add(f'<text x="40" y="46" fill="{INK}" font-size="26" font-weight="700">'
          f'REFERENCE BLUEPRINTS — the same body, five other ways</text>')
    f.add(f'<text x="40" y="72" fill="{MUTED}" font-size="12.5">'
          f'Every number read from the repo\u2019s own source via codeload.github.com, '
          f'tokens = chars/4 (same estimator as ours)</text>')
    f.add(f'<text x="40" y="94" fill="{ACCENT}" font-size="12">'
          f'ours: system {OURS["system"]:,} tok + tool schema {OURS["schema_tok"]:,} tok = '
          f'{(OURS["system"] + OURS["schema_tok"]) * 100 // 30051}% of a '
          f'{sum(t for _, t in SOURCE["tok_per_cycle"]) // len(SOURCE["tok_per_cycle"]):,}-token cycle</text>')

    y = top
    for r in REFS:
        f.add(f'<rect x="36" y="{y}" width="{W - 72}" height="{row_h + 8}" rx="14" '
              f'fill="{CARD}" stroke="{LINE}"/>')
        f.add(f'<text x="58" y="{y + 32}" fill="{INK}" font-size="17" font-weight="700">'
              f'{esc(r["name"])}</text>')
        f.add(f'<text x="58" y="{y + 52}" fill="{MUTED}" font-size="10.5">'
              f'{esc(r["repo"])} · {esc(r["lang"])}</text>')
        f.add(f'<text x="58" y="{y + 70}" fill="{ACCENT}" font-size="10">'
              f'system {r["system"]:,} tok · tools {r["tools"]}</text>')
        f.add(f'<text x="58" y="{y + 86}" fill="{MUTED}" font-size="9.5">'
              f'{esc(r["system_note"][:46])}</text>')
        f.add(f'<text x="58" y="{y + 100}" fill="{MUTED}" font-size="9.5">'
              f'{esc(r["compact_note"][:48])}</text>')

        # four n8n-style mini-nodes: prompt → context → loop → tools
        nx = 470
        nw = 250  # 4 nodes must fit inside x=470..1560
        ny = y + 14
        nodes = [
            ("PROMPT", f"{r['system']:,} tok", "system message", ACCENT if r["system"] < 2000 else WARN),
            ("CONTEXT", (f"map {r['repomap']:,}" if r["repomap"] else "on demand"),
             r["repomap_note"][:26], OK),
            ("LOOP", f"{r['compact']} compact lvls", r["cache"][:26], WARN if r["compact"] < 2 else OK),
            ("TOOLS", (f"{r['tools']} schemas" if r["tools"] else "no schemas"),
             r["tool_result"][:26], OK if not r["tools"] or r["tools"] != 56 else WARN),
        ]
        for i, (title, metric, sub, colour) in enumerate(nodes):
            x = nx + i * (nw + 26)
            f.add(f'<rect x="{x}" y="{ny}" width="{nw}" height="{NODE_H}" rx="10" '
                  f'fill="#0f1620" stroke="{colour}" stroke-width="1.5"/>')
            f.add(f'<text x="{x + 14}" y="{ny + 22}" fill="{MUTED}" font-size="9.5">{title}</text>')
            f.add(f'<text x="{x + 14}" y="{ny + 44}" fill="{INK}" font-size="12.5" '
                  f'font-weight="700">{esc(metric)}</text>')
            f.add(f'<text x="{x + 14}" y="{ny + 64}" fill="{MUTED}" font-size="9.5">'
                  f'{esc(sub)}</text>')
            f.add(f'<text x="{x + 14}" y="{ny + 88}" fill="{colour}" font-size="9">'
                  f'{esc(r["verdict"][:30])}</text>' if i == 0 else "")
            f.add(f'<circle cx="{x}" cy="{ny + NODE_H // 2}" r="4.5" fill="{BG}" stroke="{LINE}"/>')
            f.add(f'<circle cx="{x + nw}" cy="{ny + NODE_H // 2}" r="4.5" fill="{BG}" stroke="{LINE}"/>')
            if i < 3:
                x2 = nx + (i + 1) * (nw + 26)
                f.add(f'<path d="M {x + nw} {ny + NODE_H // 2} C {x + nw + 13} {ny + NODE_H // 2}, '
                      f'{x2 - 13} {ny + NODE_H // 2}, {x2} {ny + NODE_H // 2}" fill="none" '
                      f'stroke="{LINE}" stroke-width="1.6"/>')
                f.add(f'<polygon points="{x2 - 8},{ny + NODE_H // 2 - 4} {x2 - 8},{ny + NODE_H // 2 + 4} '
                      f'{x2},{ny + NODE_H // 2}" fill="{LINE}"/>')
        y += row_h + 26

    # ── ours, same four nodes, for the eye to compare
    y += 10
    f.add(f'<rect x="36" y="{y}" width="{W - 72}" height="{row_h + 8}" rx="14" '
          f'fill="#1a1013" stroke="{BAD}"/>')
    f.add(f'<text x="58" y="{y + 32}" fill="{BAD}" font-size="17" font-weight="700">CrusorAI (ours)</text>')
    f.add(f'<text x="58" y="{y + 52}" fill="{MUTED}" font-size="10.5">measured, run 41290247998</text>')
    f.add(f'<text x="58" y="{y + 70}" fill="{ACCENT}" font-size="10">'
          f'system {OURS["system"]:,} tok · tools {OURS["tools_sent"]} sent</text>')
    f.add(f'<text x="58" y="{y + 86}" fill="{MUTED}" font-size="9.5">6,151 desktop · 430 autonomous</text>')
    f.add(f'<text x="58" y="{y + 100}" fill="{MUTED}" font-size="9.5">84% of spend discarded</text>')
    ours_nodes = [
        ("PROMPT", f"{OURS['system']:,} tok", "system_persona()", BAD),
        ("CONTEXT", "no map", "chunk retrieval", WARN),
        ("LOOP", "1 compact strategy", "rewrites prefix", BAD),
        ("TOOLS", f"{OURS['schema_tok']:,} tok schema", "36-48 sent", BAD),
    ]
    nx, ny, nw = 470, y + 14, 250
    for i, (title, metric, sub, colour) in enumerate(ours_nodes):
        x = nx + i * (nw + 26)
        f.add(f'<rect x="{x}" y="{ny}" width="{nw}" height="{NODE_H}" rx="10" '
              f'fill="#1a1013" stroke="{colour}" stroke-width="2"/>')
        f.add(f'<text x="{x + 14}" y="{ny + 22}" fill="{MUTED}" font-size="9.5">{title}</text>')
        f.add(f'<text x="{x + 14}" y="{ny + 44}" fill="{INK}" font-size="12.5" '
              f'font-weight="700">{esc(metric)}</text>')
        f.add(f'<text x="{x + 14}" y="{ny + 64}" fill="{MUTED}" font-size="9.5">{esc(sub)}</text>')
        if i < 3:
            x2 = nx + (i + 1) * (nw + 26)
            f.add(f'<path d="M {x + nw} {ny + NODE_H // 2} C {x + nw + 13} {ny + NODE_H // 2}, '
                  f'{x2 - 13} {ny + NODE_H // 2}, {x2} {ny + NODE_H // 2}" fill="none" '
                  f'stroke="{LINE}" stroke-width="1.6"/>')
            f.add(f'<polygon points="{x2 - 8},{ny + NODE_H // 2 - 4} {x2 - 8},{ny + NODE_H // 2 + 4} '
                  f'{x2},{ny + NODE_H // 2}" fill="{LINE}"/>')

    y += row_h + 40
    f.add(f'<text x="58" y="{y}" fill="{INK}" font-size="13" font-weight="700">'
          f'THE THREE STRUCTURAL DIFFERENCES</text>')
    lines = [
        ("1. Fixed preamble", "Aider 264–420 · OpenCode 75–2,175 · Codex 1,661 · ours 6,151 + 7,509 schema",
         "ours spends 45% of every cycle re-sending instructions and tool JSON"),
        ("2. Context shape", "Aider ranks the repo into 1k tokens · Codex caps AGENTS.md bytes",
         "we dump retrieved chunks and 12k-char tool results, then re-pay for them"),
        ("3. Compaction", "OpenCode 5 graded levels · openclaude 8 modules · ours 1",
         "they degrade the transcript; we rewrite it and destroy the cache"),
    ]
    yy = y + 16
    for head, detail, ours in lines:
        f.add(f'<text x="58" y="{yy + 16}" fill="{ACCENT}" font-size="11.5" font-weight="700">{esc(head)}</text>')
        f.add(f'<text x="300" y="{yy + 16}" fill="{INK}" font-size="11">{esc(detail)}</text>')
        f.add(f'<text x="300" y="{yy + 32}" fill="{BAD}" font-size="10.5">▼ {esc(ours)}</text>')
        yy += 44

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">'
            + "".join(f.parts) + "</svg>")


def render_html(svg: str) -> str:
    head = "".join(f"<th>{esc(name)}</th>" for name, _ in ROWS)
    body = ""
    for label, _ in ROWS:
        pass
    rows = ""
    for label, fn in ROWS:
        rows += f"<tr><td class='lbl'>{esc(label)}</td>"
        rows += f"<td class='ours'>{esc(fn(OURS))}</td>"
        for r in REFS:
            rows += f"<td>{esc(fn(r))}</td>"
        rows += "</tr>"
    head = "<th>Metric</th><th class='ours'>ours</th>" + "".join(
        f"<th>{esc(r['name'])}</th>" for r in REFS
    )
    verdicts = "".join(
        f"<tr><td class='lbl'>{esc(r['name'])}</td><td>{esc(r['verdict'])}</td>"
        f"<td class='steal'>{esc(r['steal'])}</td></tr>"
        for r in REFS
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Reference blueprints</title><style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; background:{BG}; color:{INK}; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
 .wrap {{ max-width:1640px; margin:0 auto; padding:26px 20px 90px; }}
 h1 {{ font-size:24px; margin:0 0 8px; }}
 .lede {{ color:{MUTED}; font-size:12.5px; line-height:1.65; margin-bottom:20px; }}
 .svgbox {{ overflow-x:auto; border:1px solid {LINE}; border-radius:12px; }}
 h2 {{ color:{ACCENT}; font-size:16px; margin:34px 0 10px; }}
 table {{ width:100%; border-collapse:collapse; font-size:12px; }}
 th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid {LINE}; vertical-align:top; }}
 th {{ color:{MUTED}; font-size:10.5px; text-transform:uppercase; letter-spacing:.06em; }}
 td.lbl {{ color:{MUTED}; white-space:nowrap; }}
 td.ours {{ color:{BAD}; }}
 td.steal {{ color:{OK}; }}
 .note {{ background:{CARD}; border:1px solid {LINE}; border-radius:10px; padding:14px 16px; margin-top:22px;
          color:{MUTED}; font-size:12px; line-height:1.7; }}
</style></head><body><div class="wrap">
<h1>Reference blueprints — how five strong harnesses shape the same loop</h1>
<div class="lede">Source downloaded from codeload.github.com and read, not summarised from READMEs.
Tokens = chars/4, the same estimator ours uses, so the columns are directly comparable.
Files read per repo are listed under each name in the diagram.</div>
<div class="svgbox">{svg}</div>

<h2>Measured comparison</h2>
<table><tr>{head}</tr>{rows}</table>

<h2>Verdict and what to steal</h2>
<table><tr><th>Harness</th><th>Verdict</th><th>Steal this</th></tr>{verdicts}</table>

<div class="note">
<b>The single sentence:</b> every one of the five keeps the fixed preamble small (0–2.2k tokens,
or 5.4k at Codex's largest) and spends its context on <i>ranked structure</i>; we keep 13,660 tokens
of preamble and spend the rest on <i>unranked content</i>. That is the whole cost gap, and it is a
design choice, not a model limitation.
</div>
</div></body></html>"""


def main() -> int:
    svg = render()
    (ROOT / "docs" / "ref_blueprints.svg").write_text(svg, encoding="utf-8")
    (ROOT / "docs" / "ref_blueprints.html").write_text(render_html(svg), encoding="utf-8")
    print(f"wrote docs/ref_blueprints.svg ({len(svg):,} bytes) and .html")
    for r in REFS:
        print(f"  {r['name']:<12} system {r['system']:>5,} tok · tools {str(r['tools']):<7} "
              f"· compact {r['compact']} strategies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
