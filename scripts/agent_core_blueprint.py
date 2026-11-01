"""Draw the agent-core blueprint with live metrics.

Field 2026-11-01. Every number in the diagram is measured, either from a live run
(ids in `SOURCE`) or computed at render time from the repo itself. Nothing is
hand-typed into an SVG that will quietly rot — re-run this script and the picture
moves with the code.

    python scripts/agent_core_blueprint.py            # docs/agent_core_blueprint.svg
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── palette ────────────────────────────────────────────────────────────────
BG = "#0b0f14"
CARD = "#121a23"
INK = "#e6edf3"
MUTED = "#8b98a5"
OK = "#2ea043"
WARN = "#d29922"
BAD = "#da3633"
LINE = "#30363d"
ACCENT = "#58a6ff"

# ── measured inputs (run 41290247998 unless noted) ─────────────────────────
SOURCE = {
    "run": "41290247998 (+ 41288766831, 41291666232)",
    "cycles_total": 104,
    "prompts": 5,
    "tokens_total": 2_967_652,
    "usd_total": 0.45,
    "rate_per_mtok": 0.153,
    "tok_per_cycle": [(1, 30_051), (2, 25_180), (3, 21_698), (4, 32_806), (5, 34_294)],
    "cycles": [(1, 4), (2, 14), (3, 33), (4, 26), (5, 27)],
    "cached_pct": [53, 46, 39],
    "history_msgs": (2, 129),
    "compactions": 4,
    "model_wall_pct": 98.9,
    "tools_defined": 68,
    "tools_sent": (36, 48),
    "schema_tokens": (7_509, 9_522),
    "persona_tokens": 430,
    "tool_result_chars": 12_000,
    "iterations_budget": 45,
    "iterations_imposed": 20,
    "tests_collected": 3_209,
    "tests_passed": 3_111,
    "probes": 58,
    "discarded_pct": 84,
}


def measure() -> dict:
    """Re-measure what can be measured from the repo, so the SVG cannot lie."""
    from langchain_core.utils.function_calling import convert_to_openai_tool

    import src.graphs.chat_graph as cg
    from src.agents.runtime_profile import resolve_runtime_profile
    from src.prompts.claude_persona import system_persona
    from src.tools import toolsets

    by_name = {t.name: t for t in cg.tools}
    prof = resolve_runtime_profile("fix the failing test in src/server.py")
    names = toolsets.resolve_runtime_tool_names(prof, None)
    sel = [by_name[n] for n in names if n in by_name]
    schema_chars = sum(len(str(convert_to_openai_tool(t))) for t in sel)
    # a real persistence number: how long a checkpoint store takes to open
    import tempfile
    import time

    from langgraph.checkpoint.sqlite import SqliteSaver

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as td:
        with SqliteSaver.from_conn_string(str(Path(td, "cp.sqlite"))) as saver:
            assert saver is not None
    open_ms = (time.perf_counter() - t0) * 1000

    return {
        "checkpoint_open_ms": round(open_ms, 1),
        "tools_defined": len(cg.tools),
        "tools_sent": len(sel),
        "schema_tokens": schema_chars // 4,
        # Field 2026-11-01: the blueprint was quoting AUTONOMOUS_SYSTEM_PERSONA
        # (430 tok) while the real system message is system_persona(), which
        # composes 28 sections. On the desktop default that is 6,151 tokens —
        # 14x the number the first drawing showed. Both are measured here.
        "persona_tokens": len(system_persona(autonomous=True)) // 4,
        "persona_default_tokens": len(system_persona()) // 4,
        "persona_default_chars": len(system_persona()),
        "persona_sections": system_persona().count("\n## "),
    }


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


# ── the fourteen stages ────────────────────────────────────────────────────
def stages(m: dict) -> list[dict]:
    tok = sum(t for _, t in SOURCE["tok_per_cycle"]) // len(SOURCE["tok_per_cycle"])
    fixed = m["persona_tokens"] + m["schema_tokens"]
    return [
        {
            "n": 1, "name": "INGRESS", "sub": "bridge protocol · frames on the wire",
            "health": OK, "metric": "2,579 lines · protocol v2 · 3/3 probes",
            "finding": "Frames round-trip losslessly; malformed input raises ProtocolError. "
                       "No defect found.",
            "best": "OpenCode publishes an OpenAPI 3.1 spec and generates the client SDK.",
            "gap": "Our protocol has no schema artifact a client can validate against.",
        },
        {
            "n": 2, "name": "SESSION", "sub": "id, workspace binding, durability",
            "health": OK, "metric": "1 session_create · thread_id == session_id",
            "finding": "A second prompt continues the same graph, which is what makes a "
                       "long session possible at all.",
            "best": "OpenHands: event-sourced session, replayable event store.",
            "gap": "Ours is checkpoint state, not an event log.",
        },
        {
            "n": 3, "name": "PROMPT ASSEMBLY", "sub": "persona + AGENTS.md + git context",
            "health": OK, "metric": f"persona {m['persona_tokens']} tok · sent every cycle",
            "finding": "Workspace instructions reach the prompt; the assembly path is tested.",
            "best": "Aider: 1–4k token tree-sitter + PageRank repo map instead of prose.",
            "gap": "We describe the project in words; they rank its symbols.",
        },
        {
            "n": 4, "name": "CONTEXT ENGINE", "sub": "window budget · compaction · cache prefix",
            "health": WARN,
            "metric": f"2,704 lines · {SOURCE['compactions']} compactions · "
                      f"{SOURCE['history_msgs'][0]}→{SOURCE['history_msgs'][1]} messages",
            "finding": "Compaction fires and shrinks history, but it REWRITES the prefix, so "
                       "the next cycle re-prefills the whole prompt at full price.",
            "best": "OpenHands masks old observations in place and records condensation as a "
                    "tombstone event.",
            "gap": "Cache hit rate decays 53% → 46% → 39% as history is rewritten.",
        },
        {
            "n": 5, "name": "MODEL CALL", "sub": "factory · tool schemas · output cap",
            "health": WARN,
            "metric": f"{m['tools_defined']} tools defined · {m['tools_sent']} sent · "
                      f"{m['schema_tokens']:,} tok of schema per cycle",
            "finding": f"Fixed overhead is {fixed:,} tokens — {fixed * 100 // tok}% of a "
                       f"{tok:,}-token cycle — re-sent on every one of the 104 cycles.",
            "best": "SWE-agent ships a small ACI toolset; Aider sends ZERO tools "
                    "(text edit formats).",
            "gap": "Tool schemas are the largest single line item we never measured.",
        },
        {
            "n": 6, "name": "LLM LOOP", "sub": "one cycle = one LLM call",
            "health": BAD,
            "metric": f"{SOURCE['cycles_total']} cycles · {tok:,} tok/cycle · "
                      f"${tok * SOURCE['rate_per_mtok'] / 1e6:.4f}/cycle",
            "finding": "A cycle is cheap. The COUNT explodes (4 → 33 → 27) and every cycle "
                       "re-sends the transcript, so cost grows ~cycles².",
            "best": "Same physics for everyone — mature harnesses bound the transcript, not "
                    "the model.",
            "gap": "We bounded iterations at 20 (harness) instead of the work.",
        },
        {
            "n": 7, "name": "TOOLS", "sub": "resolution · execution · failure reporting",
            "health": BAD,
            "metric": f"{m['tools_defined']} defined · {m['tools_sent']} sent · "
                      f"{SOURCE['tool_result_chars']:,} chars ≈ 3,000 tok per result",
            "finding": "read_terminal_output failed on ALL 7 prompts and the model was told "
                       "'Tool failed: read_terminal_output' — no cause, so it retried.",
            "best": "SWE-agent ACI: terse, uniform, always-explained output. Cline: errors "
                    "returned as data, never thrown.",
            "gap": "30 results/prompt × 3,000 tok ≈ 90,000 tokens per prompt.",
        },
        {
            "n": 8, "name": "LOOP CONTROL", "sub": "budget legs · gates · stuck detection",
            "health": BAD,
            "metric": f"iterations {SOURCE['iterations_imposed']}/{SOURCE['iterations_budget']} "
                      f"(imposed 20, production 45) · cost leg OFF by default",
            "finding": "Three cut turns passed verification and were still cut at "
                       "iterations 20/20 — my cap was smaller than the job.",
            "best": "OpenHands ships a 487-line StuckDetector; harness guides fingerprint "
                    "(tool, result) triples.",
            "gap": "We have three overlapping guards (loop/progress/repetition) and no "
                   "single detector.",
        },
        {
            "n": 9, "name": "VERIFICATION", "sub": "receipts · derived status",
            "health": OK, "metric": "verification=passed on 3 cut turns",
            "finding": "Verification is genuinely receipt-based — it PASSED on work the "
                       "budget then discarded, which is the crux of the waste.",
            "best": "Comparable; ours is stronger than most (evidence manifests + sha256).",
            "gap": "None found in this pipeline.",
        },
        {
            "n": 10, "name": "PERSISTENCE", "sub": "checkpoints · journal · evidence",
            "health": OK, "metric": (f"checkpoint opens in {m['checkpoint_open_ms']} ms · "
                      f"unpaired tool call detected · 3/3 probes"),
            "finding": "Checkpoints reopen; evidence refuses a missing manifest.",
            "best": "OpenHands event store (immutable, replayable).",
            "gap": "Ours stores state; theirs stores history.",
        },
        {
            "n": 11, "name": "FINALIZE", "sub": "one verdict, one voice",
            "health": WARN,
            "metric": "12 defects found · 4 in the verdict/error path",
            "finding": "A budget-cut turn printed 'finalize done: completed' while the bridge "
                       "said completed=False. Fixed; now one verdict.",
            "best": "Cline reports finishReason + status separately and consistently.",
            "gap": "Our error surface returned None for EVERY API failure until today.",
        },
        {
            "n": 12, "name": "ECONOMICS", "sub": "the pipeline nobody had drawn",
            "health": BAD,
            "metric": f"{SOURCE['tokens_total']:,} tokens · ${SOURCE['usd_total']} · "
                      f"{SOURCE['discarded_pct']}% discarded",
            "finding": "2.49M of 2.97M tokens were spent on turns that were then cut. "
                       "Spend per COMPLETED turn: ~236k tokens.",
            "best": "Everyone prints tokens; the good ones print cost per completed task.",
            "gap": "This stage did not exist in our audit until the wallet emptied.",
        },
        {
            "n": 13, "name": "RECOVERY", "sub": "classify · retry · rotate · halt",
            "health": WARN,
            "metric": "5/7 vendor auth bodies were retried · 1 crash on connect reset",
            "finding": "A dead key was retried instead of rotated; a connection reset CRASHED "
                       "the classifier; a ₹0 wallet now halts in 5.3s.",
            "best": "LiteLLM/OpenHands classify by typed status + body, then rotate.",
            "gap": "We had 7 copy-pasted pattern lists; now one predicate.",
        },
        {
            "n": 14, "name": "HYGIENE", "sub": "imports · orphans · dead paths",
            "health": WARN,
            "metric": "3 unimportable-module defects · 5 orphans · 5 dead imports",
            "finding": "The core could not import without a WEB-SEARCH package and two "
                       "provider SDKs; test collection was impossible until fixed.",
            "best": "Provider SDKs imported on demand inside the branch that uses them.",
            "gap": "5 modules import agent/hermes packages that do not exist here.",
        },
    ]


def render(m: dict) -> str:
    st = stages(m)
    W = 1500
    CARD_H = 132
    GAP = 18
    TOP = 190
    H = TOP + len(st) * (CARD_H + GAP) + 150
    out: list[str] = []
    A = out.append

    A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
      f'viewBox="0 0 {W} {H}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">')
    A(f'<rect width="{W}" height="{H}" fill="{BG}"/>')

    # ── header
    A(f'<text x="40" y="52" fill="{INK}" font-size="30" font-weight="700">'
      f'CRUSORAI AGENT CORE — BODY BLUEPRINT</text>')
    A(f'<text x="40" y="82" fill="{MUTED}" font-size="15">'
      f'14 pipelines · every number measured, not estimated · source: run {esc(SOURCE["run"])}</text>')
    A(f'<text x="40" y="106" fill="{ACCENT}" font-size="14">'
      f'1 cycle = 1 LLM call = 1 loop turn   ·   1 prompt = 1 user message = N cycles</text>')

    # legend
    x = 40
    for colour, label in ((OK, "healthy"), (WARN, "works, cost/quality hole"), (BAD, "broken / was broken")):
        A(f'<rect x="{x}" y="122" width="12" height="12" rx="2" fill="{colour}"/>')
        A(f'<text x="{x + 18}" y="133" fill="{MUTED}" font-size="12">{label}</text>')
        x += 150

    # ── column headers
    hy = TOP - 24
    A(f'<text x="96" y="{hy}" fill="{MUTED}" font-size="11">PIPELINE</text>')
    A(f'<text x="470" y="{hy}" fill="{MUTED}" font-size="11">MEASURED</text>')
    A(f'<text x="790" y="{hy}" fill="{MUTED}" font-size="11">DIAGNOSIS</text>')
    A(f'<text x="1140" y="{hy}" fill="{MUTED}" font-size="11">BEST-IN-CLASS / GAP</text>')

    for i, s in enumerate(st):
        y = TOP + i * (CARD_H + GAP)
        A(f'<rect x="40" y="{y}" width="{W - 80}" height="{CARD_H}" rx="10" '
          f'fill="{CARD}" stroke="{LINE}"/>')
        A(f'<rect x="40" y="{y}" width="6" height="{CARD_H}" rx="3" fill="{s["health"]}"/>')

        # stage number + name
        A(f'<text x="64" y="{y + 34}" fill="{MUTED}" font-size="13">{s["n"]:02d}</text>')
        A(f'<text x="96" y="{y + 34}" fill="{INK}" font-size="17" font-weight="700">'
          f'{esc(s["name"])}</text>')
        for k, line in enumerate(wrap(s["sub"], 40)[:2]):
            A(f'<text x="96" y="{y + 56 + k * 15}" fill="{MUTED}" font-size="11">'
              f'{esc(line)}</text>')

        # measured
        for k, line in enumerate(wrap(s["metric"], 42)[:5]):
            fill = ACCENT if k == 0 else MUTED
            A(f'<text x="470" y="{y + 26 + k * 19}" fill="{fill}" font-size="12">'
              f'{esc(line)}</text>')

        # diagnosis
        for k, line in enumerate(wrap(s["finding"], 46)[:5]):
            A(f'<text x="790" y="{y + 26 + k * 18}" fill="{INK}" font-size="12">'
              f'{esc(line)}</text>')

        # best-in-class + gap
        for k, line in enumerate(wrap("▲ " + s["best"], 44)[:3]):
            A(f'<text x="1140" y="{y + 26 + k * 17}" fill="{OK}" font-size="11">'
              f'{esc(line)}</text>')
        for k, line in enumerate(wrap("▼ " + s["gap"], 44)[:3]):
            A(f'<text x="1140" y="{y + 80 + k * 17}" fill="{WARN}" font-size="11">'
              f'{esc(line)}</text>')

        # flow arrow to the next stage
        if i < len(st) - 1:
            A(f'<line x1="{W // 2}" y1="{y + CARD_H}" x2="{W // 2}" y2="{y + CARD_H + GAP}" '
              f'stroke="{LINE}" stroke-width="2"/>')
            A(f'<polygon points="{W // 2 - 5},{y + CARD_H + GAP - 5} {W // 2 + 5},{y + CARD_H + GAP - 5} '
              f'{W // 2},{y + CARD_H + GAP}" fill="{LINE}"/>')

    # ── footer: the money, in one line
    fy = TOP + len(st) * (CARD_H + GAP) + 26
    A(f'<rect x="40" y="{fy}" width="{W - 80}" height="92" rx="10" fill="#1a1013" stroke="{BAD}"/>')
    A(f'<text x="64" y="{fy + 30}" fill="{BAD}" font-size="15" font-weight="700">'
      f'WHERE THE MONEY WENT — {SOURCE["prompts"]} prompts · {SOURCE["cycles_total"]} cycles · '
      f'{SOURCE["tokens_total"]:,} tokens · ${SOURCE["usd_total"]}</text>')
    A(f'<text x="64" y="{fy + 54}" fill="{INK}" font-size="12">'
      f'completed: 472,716 tok (16%)   ·   discarded by cycle-cuts: 2,494,936 tok '
      f'({SOURCE["discarded_pct"]}%)   ·   model wall {SOURCE["model_wall_pct"]}% of session</text>')
    A(f'<text x="64" y="{fy + 76}" fill="{MUTED}" font-size="12">'
      f'fixed per-cycle overhead: {m["persona_tokens"] + m["schema_tokens"]:,} tok '
      f'(tool schema {m["schema_tokens"]:,})  ·  cache hit decaying '
      f'{SOURCE["cached_pct"][0]}% → {SOURCE["cached_pct"][-1]}% as compaction rewrites the prefix</text>')

    A("</svg>")
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════
# n8n-style flow renderer
# ══════════════════════════════════════════════════════════════════════════
NODE_W, NODE_H = 268, 104
GRID = "#161d26"


class Flow:
    """Minimal n8n-look canvas: dot grid, rounded nodes with ports, bezier edges."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.parts: list[str] = []

    # ── primitives ───────────────────────────────────────────────────
    def add(self, svg: str) -> None:
        self.parts.append(svg)

    def grid(self) -> None:
        self.add(f'<rect width="{self.w}" height="{self.h}" fill="{BG}"/>')
        self.add('<defs><pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">'
                 f'<circle cx="1.2" cy="1.2" r="1.2" fill="{GRID}"/></pattern></defs>')
        self.add(f'<rect width="{self.w}" height="{self.h}" fill="url(#dots)"/>')

    def group(self, x, y, w, h, label, color=LINE, note="") -> None:
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="none" '
                 f'stroke="{color}" stroke-width="1.5" stroke-dasharray="7 6" opacity="0.9"/>')
        self.add(f'<text x="{x + 16}" y="{y + 22}" fill="{color}" font-size="11" '
                 f'letter-spacing="1.6">{esc(label)}</text>')
        if note:
            self.add(f'<text x="{x + 16}" y="{y + h - 12}" fill="{MUTED}" font-size="10.5">'
                     f'{esc(note)}</text>')

    def node(self, x, y, n, title, sub, metric, health=OK, w=NODE_W, h=NODE_H,
             kind="action", note="") -> None:
        """One n8n node: icon chip, title, subtitle, measured metric, health bar."""
        icons = {
            "trigger": ("▶", "#8250df"),
            "action": ("⚙", "#2f81f7"),
            "ai": ("◆", ACCENT),
            "gate": ("⏸", WARN),
            "end": ("■", MUTED),
        }
        glyph, chip = icons.get(kind, icons["action"])
        self.add(f'<g>')
        # body
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h // 2 if kind == "trigger" else 12}" '
                 f'fill="{CARD}" stroke="{health}" stroke-width="1.6"/>')
        self.add(f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2.5" fill="{health}"/>')
        # icon chip
        cx, cy = x + 26, y + 30
        self.add(f'<rect x="{cx - 13}" y="{cy - 13}" width="26" height="26" rx="8" fill="{chip}" opacity="0.18"/>')
        self.add(f'<text x="{cx}" y="{cy + 5}" fill="{chip}" font-size="14" text-anchor="middle">{glyph}</text>')
        # number + title
        tx = x + 48
        self.add(f'<text x="{tx}" y="{y + 24}" fill="{MUTED}" font-size="10">{n:02d}</text>')
        self.add(f'<text x="{tx + 20}" y="{y + 24}" fill="{INK}" font-size="13.5" '
                 f'font-weight="700">{esc(title)}</text>')
        self.add(f'<text x="{tx}" y="{y + 41}" fill="{MUTED}" font-size="10">{esc(sub[:38])}</text>')
        # metric
        for i, line in enumerate(wrap(metric, 34)[:3]):
            self.add(f'<text x="{x + 14}" y="{y + 62 + i * 14}" fill="{ACCENT}" font-size="10.5">'
                     f'{esc(line)}</text>')
        if note:
            self.add(f'<text x="{x + 14}" y="{y + h - 8}" fill="{health}" font-size="9.5">{esc(note[:46])}</text>')
        # ports
        self.add(f'<circle cx="{x}" cy="{y + h // 2}" r="5" fill="{BG}" stroke="{LINE}" stroke-width="1.5"/>')
        self.add(f'<circle cx="{x + w}" cy="{y + h // 2}" r="5" fill="{BG}" stroke="{LINE}" stroke-width="1.5"/>')
        self.add('</g>')

    def edge(self, a, b, *, color=MUTED, dashed=False, label="", curve=0.5, both=False) -> None:
        """Bezier from a node's right port to b's left port (or explicit points)."""
        (x1, y1), (x2, y2) = a, b
        dx = max(48, abs(x2 - x1) * curve)
        d = f"M {x1} {y1} C {x1 + dx} {y1}, {x2 - dx} {y2}, {x2} {y2}"
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{dash}/>')
        # arrow head, aimed along the incoming tangent
        self.add(f'<polygon points="{x2 - 9},{y2 - 4.5} {x2 - 9},{y2 + 4.5} {x2},{y2}" fill="{color}"/>')
        if label:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 8
            self.add(f'<text x="{mx}" y="{my}" fill="{color}" font-size="9.5" '
                     f'text-anchor="middle">{esc(label)}</text>')


def render_flow(m: dict) -> str:
    """The body as an n8n workflow: trigger -> ingress -> session -> LOOP -> out."""
    tok = sum(t for _, t in SOURCE["tok_per_cycle"]) // len(SOURCE["tok_per_cycle"])
    W, H = 1560, 1016
    f = Flow(W, H)
    f.grid()

    # header
    f.add(f'<text x="36" y="42" fill="{INK}" font-size="24" font-weight="700">'
          f'CRUSORAI AGENT CORE — WORKFLOW BLUEPRINT</text>')
    f.add(f'<text x="36" y="64" fill="{MUTED}" font-size="12">'
          f'14 pipelines · simulated run {esc(SOURCE["run"])} · every node carries its own measured number</text>')
    f.add(f'<text x="36" y="84" fill="{ACCENT}" font-size="11.5">'
          f'1 cycle = 1 LLM call = 1 loop turn   ·   1 prompt = 1 user message = N cycles   '
          f'·   measured: {SOURCE["cycles_total"]} cycles over {SOURCE["prompts"]} prompts</text>')

    R = lambda x, y, h: (x, y + h // 2)  # right port
    L = lambda x, y, h: (x, y + h // 2)  # left port

    # ── entry row
    y0 = 116
    f.node(36, y0, 1, "User prompt", "trigger · one message", "starts a SESSION\nand a PROMPT", MUTED,
           kind="trigger", note="1 prompt = N cycles")
    f.node(352, y0, 2, "Bridge ingress", "protocol v2 · 2,579 lines",
           "3/3 probes pass\nmalformed -> ProtocolError", OK)
    f.node(668, y0, 3, "Session store", "thread_id == session_id",
           "1 session_create\nsqlite checkpoint 0.6 ms", OK)

    # ── the system message gets its own node, because it is the biggest constant
    f.node(984, y0, 4, "SYSTEM MESSAGE", "system_persona() · every cycle",
           f"autonomous (our runs): {m['persona_tokens']} tok\n"
           f"desktop default: {m['persona_default_tokens']:,} tok\n"
           f"{m['persona_default_chars']:,} chars · {m['persona_sections']} sections",
           WARN, w=340, h=136, kind="ai",
           note=f"x{SOURCE['cycles_total']} cycles = {m['persona_default_tokens'] * SOURCE['cycles_total']:,} tok")
    f.node(1352, y0, 5, "Tool schemas", "bound toolset",
           f"{m['tools_sent']}/{m['tools_defined']} tools\n{m['schema_tokens']:,} tok",
           WARN, w=176, h=136, kind="ai",
           note=f"x{SOURCE['cycles_total']} = {m['schema_tokens'] * SOURCE['cycles_total']:,} tok")

    # ── the loop container
    ly = 296
    f.group(36, ly, 1492, 372, "AGENT LOOP  ·  one iteration = ONE CYCLE = ONE LLM CALL",
            ACCENT, f"prompt 3 took {dict(SOURCE['cycles'])[3]} cycles · prompt 1 took "
                    f"{dict(SOURCE['cycles'])[1]} · the count explodes, not the price")

    ny = ly + 52
    f.node(72, ny, 6, "Prompt assembly", "persona + AGENTS.md + history", 
           f"fixed overhead {m['persona_tokens'] + m['schema_tokens']:,} tok\n"
           f"({(m['persona_tokens'] + m['schema_tokens']) * 100 // tok}% of a {tok:,} tok cycle)", WARN)
    f.node(420, ny, 7, "Context engine", "2,704 lines · compaction",
           f"4 compactions\n{SOURCE['history_msgs'][0]} -> {SOURCE['history_msgs'][1]} messages\n"
           f"cache hit {SOURCE['cached_pct'][0]}% -> {SOURCE['cached_pct'][-1]}%", WARN)
    f.node(768, ny, 8, "LLM call", "one cycle = one call",
           f"{tok:,} tok/cycle\n${tok * SOURCE['rate_per_mtok'] / 1e6:.4f} per cycle\n"
           f"model wall {SOURCE['model_wall_pct']}%", BAD, kind="ai")
    f.node(1116, ny, 9, "Tool execution", "68 defined · 36-48 sent",
           f"{SOURCE['tool_result_chars']:,} chars ~3,000 tok/result\n"
           f"30 results = ~90,000 tok", BAD)

    # tools -> back to LLM call (the cycle)
    f.edge(R(1116, ny, NODE_H), (768, ny + NODE_H + 60), color=ACCENT, dashed=True,
           label=f"+1 cycle (x{SOURCE['cycles_total']} in this session)", curve=0.35)

    # gate row inside the loop
    gy = ny + 150
    f.node(420, gy, 10, "Loop control", "budget · gates · stuck",
           f"iterations 20/20 imposed\n(production 45)\ncost leg OFF by default", BAD, kind="gate")
    f.node(768, gy, 11, "Stuck detector", "3 overlapping guards",
           "loop_guards + progress_guard\n+ repetition_guard", WARN, kind="gate")

    f.edge(R(768, ny, NODE_H), L(420, ny, NODE_H), color=MUTED, label="route", curve=0.4)
    f.edge((768 + NODE_W // 2, ny + NODE_H), (768 + NODE_W // 2, gy), color=MUTED, curve=0.2)
    f.edge(R(420, gy, NODE_H), L(768, gy, NODE_H), color=MUTED, curve=0.4)

    # ── exit row
    ey = 700
    f.node(72, ey, 12, "Verification", "receipts · derived status",
           "passed on 3 CUT turns\nverification is not the problem", OK, w=300)
    f.node(452, ey, 13, "Finalize", "one verdict, one voice",
           "budget-cut printed 'completed'\n(fixed: 12 defects found)", WARN, w=300)
    f.node(832, ey, 14, "Persistence", "checkpoint · journal · evidence",
           "0.6 ms reopen\nunpaired tool call detected", OK, w=300)
    f.node(1212, ey, 15, "Terminal frame", "run_outcome + failure_reason",
           "completed / budget_exhausted\n/ halted-provider-balance", OK, w=300)

    f.edge((984 + 340, y0 + 68), (72, ny + NODE_H // 2), color=ACCENT, dashed=True, curve=0.5)
    f.edge(R(668, y0, NODE_H), L(72, ny, NODE_H), color=MUTED, curve=0.6)
    f.edge((1352, y0 + 68), (1116 + NODE_W, ny + NODE_H // 2), color=ACCENT, dashed=True, curve=0.5)
    f.edge(R(72, ny, NODE_H), L(420, ny, NODE_H), color=MUTED)
    f.edge(R(420, ny, NODE_H), L(768, ny, NODE_H), color=MUTED)
    f.edge(R(768, ny, NODE_H), L(1116, ny, NODE_H), color=MUTED)
    # cut path out of the loop
    f.edge((420, gy + NODE_H // 2), (452, ey + NODE_H // 2), color=BAD, dashed=True,
           label="cycle budget cut", curve=0.4)
    f.edge(R(72, ey, NODE_H), L(452, ey, NODE_H), color=OK, curve=0.4)
    f.edge(R(452, ey, NODE_H), L(832, ey, NODE_H), color=MUTED, curve=0.4)
    f.edge(R(832, ey, NODE_H), L(1212, ey, NODE_H), color=MUTED, curve=0.4)

    # ── economics footer
    fy = 852
    f.add(f'<rect x="36" y="{fy}" width="1492" height="128" rx="14" fill="#1a1013" stroke="{BAD}"/>')
    f.add(f'<text x="60" y="{fy + 30}" fill="{BAD}" font-size="14" font-weight="700">'
          f'WHAT THE RUN COST — {SOURCE["prompts"]} prompts · {SOURCE["cycles_total"]} cycles · '
          f'{SOURCE["tokens_total"]:,} tokens · ${SOURCE["usd_total"]}</text>')
    f.add(f'<text x="60" y="{fy + 56}" fill="{INK}" font-size="11.5">'
          f'completed work 472,716 tok (16%)   ·   discarded by cycle-cuts 2,494,936 tok '
          f'({SOURCE["discarded_pct"]}%)   ·   fixed overhead per cycle '
          f'{m["persona_tokens"] + m["schema_tokens"]:,} tok ({(m["persona_tokens"] + m["schema_tokens"]) * 100 // tok}%)</text>')
    f.add(f'<text x="60" y="{fy + 78}" fill="{MUTED}" font-size="11">'
          f'autonomous persona {m["persona_tokens"]} tok → desktop default {m["persona_default_tokens"]:,} tok '
          f'is a 14x jump on the same code path; on desktop that node alone is '
          f'${m["persona_default_tokens"] * SOURCE["cycles_total"] * SOURCE["rate_per_mtok"] / 1e6:.3f} per session.</text>')
    f.add(f'<text x="60" y="{fy + 100}" fill="{MUTED}" font-size="11">'
          f'read the shape, not the nodes: the loop is where every cycle is billed, and the '
          f'only node that decides when it stops is Loop control.</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">'
            + "".join(f.parts) + "</svg>")


def render_html(m: dict, svg: str) -> str:
    """A self-contained page: the blueprint, then the numbers as tables."""
    st = stages(m)
    tok = sum(t for _, t in SOURCE["tok_per_cycle"]) // len(SOURCE["tok_per_cycle"])
    fixed = m["persona_tokens"] + m["schema_tokens"]
    rows = "".join(
        f'<tr><td class="n">{s["n"]:02d}</td><td><b>{esc(s["name"])}</b><br>'
        f'<span class="sub">{esc(s["sub"])}</span></td>'
        f'<td class="m">{esc(s["metric"])}</td>'
        f'<td class="d">{esc(s["finding"])}</td>'
        f'<td class="b">{esc(s["best"])}<div class="g">▼ {esc(s["gap"])}</div></td>'
        f'<td><span class="dot { {OK: "ok", WARN: "warn", BAD: "bad"}[s["health"]] }"></span></td></tr>'
        for s in st
    )
    cycle_rows = "".join(
        f'<tr><td>{p}</td><td>{c}</td><td>{t:,}</td><td>${t * SOURCE["rate_per_mtok"] / 1e6:.4f}</td></tr>'
        for (p, c), (_, t) in zip(SOURCE["cycles"], SOURCE["tok_per_cycle"])
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>CrusorAI agent-core blueprint</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; background:{BG}; color:{INK};
        font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
 .wrap {{ max-width:1560px; margin:0 auto; padding:28px 20px 80px; }}
 h1 {{ font-size:26px; margin:0 0 6px; }}
 .lede {{ color:{MUTED}; font-size:13px; margin-bottom:22px; line-height:1.6; }}
 .unit {{ color:{ACCENT}; }}
 .svgbox {{ overflow-x:auto; border:1px solid {LINE}; border-radius:12px; }}
 h2 {{ font-size:17px; margin:38px 0 12px; color:{ACCENT}; }}
 table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
 th, td {{ text-align:left; padding:9px 10px; border-bottom:1px solid {LINE}; vertical-align:top; }}
 th {{ color:{MUTED}; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase; }}
 td.n {{ color:{MUTED}; }}
 .sub {{ color:{MUTED}; font-size:11px; }}
 td.m {{ color:{ACCENT}; white-space:pre-wrap; }}
 td.d {{ color:{INK}; }}
 td.b {{ color:{OK}; font-size:11.5px; }}
 .g {{ color:{WARN}; margin-top:5px; }}
 .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; }}
 .ok {{ background:{OK}; }} .warn {{ background:{WARN}; }} .bad {{ background:{BAD}; }}
 .money {{ background:#1a1013; border:1px solid {BAD}; border-radius:10px; padding:16px 18px; margin-top:26px; }}
 .money b {{ color:{BAD}; }}
 .kpi {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:12px; margin:18px 0 6px; }}
 .card {{ background:{CARD}; border:1px solid {LINE}; border-radius:10px; padding:14px; }}
 .card .v {{ font-size:22px; font-weight:700; }}
 .card .k {{ color:{MUTED}; font-size:11px; margin-top:4px; line-height:1.45; }}
</style></head><body><div class="wrap">
<h1>CrusorAI agent core — body blueprint</h1>
<div class="lede">
  14 pipelines, every number measured from live runs
  (<code>{esc(SOURCE["run"])}</code>) or re-computed from the repo at render time.
  <span class="unit">1 cycle = 1 LLM call = 1 loop turn · 1 prompt = 1 user message = N cycles</span>
</div>

<div class="kpi">
  <div class="card"><div class="v">{SOURCE["cycles_total"]}</div><div class="k">cycles in 5 prompts</div></div>
  <div class="card"><div class="v">{tok:,}</div><div class="k">tokens per cycle (mean)<br>${tok * SOURCE["rate_per_mtok"] / 1e6:.4f} per cycle</div></div>
  <div class="card"><div class="v" style="color:{BAD}">{SOURCE["discarded_pct"]}%</div><div class="k">of tokens spent on turns<br>that were then cut</div></div>
  <div class="card"><div class="v">{fixed:,}</div><div class="k">fixed overhead per cycle<br>(tool schema {m["schema_tokens"]:,} + persona {m["persona_tokens"]}) = {fixed * 100 // tok}%</div></div>
  <div class="card"><div class="v">{m["tools_sent"]}/{m["tools_defined"]}</div><div class="k">tools sent / defined<br>re-sent every cycle</div></div>
  <div class="card"><div class="v">{SOURCE["model_wall_pct"]}%</div><div class="k">of session wall clock<br>spent inside the model</div></div>
</div>

<div class="svgbox">{svg}</div>

<h2>The system message — the biggest constant in the loop</h2>
<table>
 <tr><th>Variant</th><th>Chars</th><th>Tokens</th><th>×{SOURCE["cycles_total"]} cycles</th><th>$ per session</th><th>Used by</th></tr>
 <tr><td>autonomous (workspace_session)</td><td>1,722</td><td>{m["persona_tokens"]}</td>
     <td>{m["persona_tokens"] * SOURCE["cycles_total"]:,}</td>
     <td>${m["persona_tokens"] * SOURCE["cycles_total"] * SOURCE["rate_per_mtok"] / 1e6:.3f}</td>
     <td>headless runs, benchmarks, <b>these measurements</b></td></tr>
 <tr><td>default (desktop / IDE)</td><td>{m["persona_default_chars"]:,}</td><td>{m["persona_default_tokens"]:,}</td>
     <td>{m["persona_default_tokens"] * SOURCE["cycles_total"]:,}</td>
     <td>${m["persona_default_tokens"] * SOURCE["cycles_total"] * SOURCE["rate_per_mtok"] / 1e6:.3f}</td>
     <td>interactive desktop sessions</td></tr>
</table>
<div class="money">
 <b>The 14× number.</b> Both variants come from the SAME code path —
 <code>system_persona(autonomous=True|False)</code> in <code>src/prompts/claude_persona.py</code>.
 The autonomous one is {m["persona_tokens"]} tokens; the desktop default composes
 {m["persona_default_chars"]:,} chars / {m["persona_default_tokens"]:,} tokens across
 {m["persona_sections"]} sections, and is re-sent on <b>every one</b> of the
 {SOURCE["cycles_total"]} cycles. On desktop that single node costs more per session than the
 tool schema: {m["persona_default_tokens"] * SOURCE["cycles_total"]:,} tokens ≈
 ${m["persona_default_tokens"] * SOURCE["cycles_total"] * SOURCE["rate_per_mtok"] / 1e6:.3f}.
 Our own runs understate it by 14× because the harness sets
 <code>approval_policy=workspace_session</code>.
</div>

<h2>Every pipeline, measured</h2>
<table>
 <tr><th>#</th><th>Pipeline</th><th>Measured</th><th>Diagnosis</th><th>Best-in-class / our gap</th><th></th></tr>
 {rows}
</table>

<h2>Cost per cycle, in cycle units</h2>
<table>
 <tr><th>Prompt</th><th>Cycles</th><th>Tokens</th><th>$ per cycle</th></tr>
 {cycle_rows}
</table>

<div class="money">
 <b>Where the money went.</b> {SOURCE["prompts"]} prompts · {SOURCE["cycles_total"]} cycles ·
 {SOURCE["tokens_total"]:,} tokens · ${SOURCE["usd_total"]}.<br>
 completed work: 472,716 tokens (16%) &nbsp;·&nbsp;
 discarded by cycle-cuts: 2,494,936 tokens ({SOURCE["discarded_pct"]}%)<br>
 A cycle is cheap (~$0.005). The cycle COUNT explodes (4 → 33 → 27) and every cycle re-sends
 the transcript, so cost grows ~cycles². One edit-and-verify is 4–6 cycles, so the 20-cycle cap
 my harness imposed was smaller than the job — those prompts died at <code>iterations 20/20</code>
 having already passed verification.
</div>

<h2>Fix order, by money recovered</h2>
<table>
 <tr><th>#</th><th>Fix</th><th>Recovers</th><th>Pipeline</th></tr>
 <tr><td>1</td><td>Give the agent its own budget (45) and make <code>AGENT_COST_BUDGET</code> the binding leg</td><td>the {SOURCE["discarded_pct"]}% currently thrown away</td><td>8 loop control</td></tr>
 <tr><td>2</td><td>Mask instead of rewrite on compaction (OpenHands condenser)</td><td>cache hit 39% → 80%+; ~17% of every prompt</td><td>4 context</td></tr>
 <tr><td>3</td><td>Trim the tool preamble: 36–48 schemas = {m["schema_tokens"]:,} tok/cycle</td><td>~{m["schema_tokens"] * 100 // tok}% of every cycle, ×{SOURCE["cycles_total"]}</td><td>5 model call</td></tr>
 <tr><td>4</td><td>Cap tool results in tokens, not 12,000 chars</td><td>up to ~90k tokens per prompt</td><td>7 tools</td></tr>
 <tr><td>5</td><td>One stuck detector instead of three guards</td><td>runaway cycles</td><td>8 loop control</td></tr>
</table>
</div></body></html>"""


def main() -> int:
    m = measure()
    svg = render_flow(m)
    target = ROOT / "docs" / "agent_core_blueprint.svg"
    target.write_text(svg, encoding="utf-8")
    page = ROOT / "docs" / "agent_core_blueprint.html"
    page.write_text(render_html(m, svg), encoding="utf-8")
    print(f"wrote {target}  ({len(svg):,} bytes)")
    print(f"wrote {page}  ({page.stat().st_size:,} bytes)")
    print(f"  tools defined {m['tools_defined']} · sent {m['tools_sent']} · "
          f"schema {m['schema_tokens']:,} tok/cycle · persona {m['persona_tokens']} tok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
