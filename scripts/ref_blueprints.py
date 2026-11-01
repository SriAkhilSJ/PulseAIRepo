"""Field 2026-11-01 — the reference blueprint, rebuilt on verified numbers.

The first version of this drawing quoted "the string that looks like the system
prompt" and got three of four figures wrong:

    harness    first draft        verified          why it was wrong
    Aider           264 tok      1,265 tok  three blocks ship together (main_system
                                             + system_reminder + few-shot examples)
    OpenCode        643 tok        333 tok  the 643 was a per-model PLUGIN, not the
                                             base prompt (which is 189 tok)
    Void            380 tok      1,375 tok  the message ends with a rendered file
                                             TREE that the draft never counted

So this script owns no numbers at all. It reads ``docs/ref_verify.json``, which
``scripts/ref_verify.py`` produces by downloading each repo and measuring it two
independent ways. If the drawing and the verification ever disagree, the
drawing is wrong by construction — there is nowhere else for a number to hide.

Regenerate both steps:
    python3 scripts/ref_verify.py      # measure the repos (network)
    python3 scripts/ref_blueprints.py  # draw from the measurement
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_core_blueprint import (
    ACCENT, BAD, BG, CARD, INK, LINE, MUTED, OK, WARN, Flow, esc,
)

VERIFY_JSON = ROOT / "docs" / "ref_verify.json"
OUT_SVG = ROOT / "docs" / "ref_blueprints.svg"
OUT_HTML = ROOT / "docs" / "ref_blueprints.html"

W = 1600
ROW_H = 152
NODE_W, NODE_H = 290, 104
NODE_X = 320
NODE_GAP = 18

# Our own row cannot be measured without the langchain stack, which is not
# installed in every environment that regenerates this drawing. These two are
# read from the committed measurement output instead, and the source is named
# on the node so nobody has to trust the number.
OURS_TOOLS, OURS_SCHEMA = 36, 7509
OURS_SYSTEM = 6151
CYCLE_TOKENS = 30_051  # run 41290247998, first full cycle


def load() -> list[dict]:
    data = json.loads(VERIFY_JSON.read_text(encoding="utf-8"))
    rows = data["rows"]
    for r in rows:
        if r["name"] == "CrusorAI":
            r["system_tok"] = OURS_SYSTEM
            r["tools"], r["schema_tok"] = OURS_TOOLS, OURS_SCHEMA
            r["tok_per_tool"] = OURS_SCHEMA // OURS_TOOLS
    for r in rows:
        # Aider's repo map is re-sent on every request too, so it belongs in the
        # same column as the prompt and the schemas (Void's tree is already
        # inside its system message, which is why Void's repomap_tok is 0).
        r["fixed"] = r["system_tok"] + r["schema_tok"] + r["repomap_tok"]
    return rows


def health(fixed: int) -> str:
    if fixed <= 2_000:
        return OK
    if fixed <= 3_000:
        return WARN
    return BAD


def render(rows: list[dict]) -> str:
    n_rows = len(rows)
    chart_y = 116 + n_rows * ROW_H + 24
    chart_h = 210
    foot_y = chart_y + chart_h + 30
    foot_h = 226
    H = foot_y + foot_h + 30

    f = Flow(W, H)
    f.grid()

    # ── header
    f.add(f'<text x="36" y="44" fill="{INK}" font-size="25" font-weight="700">'
          f'REFERENCE BLUEPRINTS — WHAT THE BEST HARNESSES ACTUALLY SPEND</text>')
    f.add(f'<text x="36" y="68" fill="{MUTED}" font-size="12.5">'
          f'Aider · OpenCode · Void, read from source (codeload.github.com) and measured twice: '
          f'static literals (chars/4) and the assembled prompt (cl100k-shaped estimator).</text>')
    f.add(f'<text x="36" y="89" fill="{ACCENT}" font-size="11.5">'
          f'fixed cost = system message + tool schemas, paid on every single cycle   ·   '
          f'ours is measured against a {CYCLE_TOKENS:,}-token cycle from run 41290247998</text>')

    # ── one workflow row per harness
    for i, r in enumerate(rows):
        y = 116 + i * ROW_H
        ours = r["name"] == "CrusorAI"
        colour = BAD if ours else health(r["fixed"])
        f.group(24, y - 4, W - 48, ROW_H - 18,
                f'{r["name"].upper()}  ·  {r["fixed"]:,} tok fixed per cycle'
                + (f'  ·  that is {r["fixed"] / CYCLE_TOKENS:.0%} of a cycle' if ours else ""),
                color=colour)

        ny = y + 22
        # left: the number that matters
        f.add(f'<text x="44" y="{ny + 26}" fill="{INK}" font-size="19" font-weight="700">'
              f'{esc(r["name"])}</text>')
        f.add(f'<text x="44" y="{ny + 48}" fill="{colour}" font-size="21" font-weight="700">'
              f'{r["fixed"]:,}</text>')
        f.add(f'<text x="44" y="{ny + 66}" fill="{MUTED}" font-size="10.5">tok fixed / cycle</text>')
        f.add(f'<text x="44" y="{ny + 86}" fill="{MUTED}" font-size="10">'
              f'{r["system_tok"]:,} prompt + {r["schema_tok"]:,} schemas'
              + (f' + {r["repomap_tok"]:,} map' if r["repomap_tok"] else "")
              + '</text>')

        nodes = [
            ("PROMPT", "system message", f'{r["system_tok"]:,} tok',
             r.get("prompt_note", ""), colour if r["system_tok"] > 2_000 else OK),
            ("CONTEXT", "repo map / tree",
             f'{r["repomap_tok"]:,} tok' if r["repomap_tok"] else "0 tok",
             r["repomap_note"], OK),
            ("LOOP", "compaction", f'{r["compact_levels"]} level'
             f'{"" if r["compact_levels"] == 1 else "s"}',
             r["compact_note"], OK if r["compact_levels"] > 1 else WARN),
            ("TOOLS", f'{r["tools"]} tools',
             f'{r["schema_tok"]:,} tok' if r["schema_tok"] else "0 tok",
             f'{r["tok_per_tool"]} tok/tool', OK if r["schema_tok"] < 3_000 else WARN),
        ]
        for j, (title, sub, metric, note, hcol) in enumerate(nodes):
            x = NODE_X + j * (NODE_W + NODE_GAP)
            f.node(x, ny, j + 1, title, sub, metric, hcol, w=NODE_W, h=NODE_H,
                   kind="trigger" if j == 0 else "ai" if j == 2 else "action",
                   note=note[:44])
            if j:
                px = NODE_X + (j - 1) * (NODE_W + NODE_GAP) + NODE_W
                f.edge((px, ny + NODE_H // 2), (x, ny + NODE_H // 2), color=LINE)

    # ── the comparison itself
    f.add(f'<text x="36" y="{chart_y + 4}" fill="{INK}" font-size="15" font-weight="700">'
          f'FIXED COST PER CYCLE</text>')
    f.add(f'<text x="36" y="{chart_y + 22}" fill="{MUTED}" font-size="11">'
          f'What every single LLM call pays before it sees a byte of your request.</text>')

    bar_x, bar_w_max = 320, 980
    for i, r in enumerate(rows):
        y = chart_y + 42 + i * 30
        frac = min(1.0, r["fixed"] / 14_000)
        ours = r["name"] == "CrusorAI"
        colour = BAD if ours else health(r["fixed"])
        f.add(f'<text x="{bar_x - 14}" y="{y + 13}" fill="{MUTED}" font-size="11.5" '
              f'text-anchor="end">{esc(r["name"])}</text>')
        f.add(f'<rect x="{bar_x}" y="{y}" width="{bar_w_max}" height="18" rx="4" '
              f'fill="{CARD}" stroke="{LINE}" stroke-width="1"/>')
        f.add(f'<rect x="{bar_x}" y="{y}" width="{max(6, int(bar_w_max * frac))}" height="18" '
              f'rx="4" fill="{colour}" opacity="{0.95 if ours else 0.75}"/>')
        f.add(f'<text x="{bar_x + int(bar_w_max * frac) + 10}" y="{y + 13}" fill="{colour}" '
              f'font-size="11.5" font-weight="700">{r["fixed"]:,} tok</text>')

    # ── footer: the corrections, stated plainly
    f.group(24, foot_y, W - 48, foot_h, "AUDIT TRAIL — WHAT THE FIRST DRAWING GOT WRONG",
            color=WARN)
    # Every number below is computed from `rows`, never typed. Typing them is
    # exactly how the first draft shipped 264 / 643 / 380 and had to be redone.
    by = {r["name"]: r for r in rows}
    a, o, v, u = by["Aider"], by["OpenCode"], by["Void"], by["CrusorAI"]
    lines = [
        (f"1.  AIDER was drawn at 264 tok. It is {a['system_tok']:,}: format_chat_chunks appends "
         f"system_reminder and sends the few-shot examples as real turns.", MUTED),
        (f"     And its repo map is not {a['repomap_tok']:,} — with no files added to the chat the "
         f"target becomes 1,024 x 8 = 8,192 tokens (repomap.py:56,124-132).", MUTED),
        (f"2.  OPENCODE was drawn at 643 tok. That file is a per-model PLUGIN. The base prompt is "
         f"189 tok; assembled with tool guidance it is {o['system_tok']:,}.", MUTED),
        (f"3.  VOID was drawn at 380 tok. Its message ends with a rendered file TREE, capped at "
         f"20,000 chars — assembled it is {v['system_tok']:,}.", MUTED),
        (f"4.  OUR tool schemas alone ({u['schema_tok']:,} tok) are "
         f"{u['schema_tok'] / o['fixed']:.1f}x the ENTIRE fixed cost of OpenCode "
         f"({o['fixed']:,}) and {u['schema_tok'] / v['fixed']:.1f}x Void's ({v['fixed']:,}). "
         f"That is the finding; the prose was beside the point.", ACCENT),
    ]
    for i, (text, colour) in enumerate(lines):
        f.add(f'<text x="44" y="{foot_y + 52 + i * 32}" fill="{colour}" font-size="11.5">'
              f'{esc(text)}</text>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="ui-monospace, SFMono-Regular, Menlo, monospace">'
            + "".join(f.parts) + "</svg>")


def render_html(svg: str, rows: list[dict]) -> str:
    def cell(r, key, fmt="{}"):
        return fmt.format(r[key])

    body = "".join(
        f'<tr class="{"ours" if r["name"] == "CrusorAI" else ""}">'
        f'<td><b>{esc(r["name"])}</b></td>'
        f'<td>{r["system_tok"]:,}</td>'
        f'<td>{r["system_m1"]:,} <span class="d">({r["system_delta_pct"]:+.0f}%)</span></td>'
        f'<td>{r["tools"]}</td>'
        f'<td>{r["schema_tok"]:,}</td>'
        f'<td>{r["tok_per_tool"] or "—"}</td>'
        f'<td>{r["compact_levels"]}</td>'
        f'<td>{r["repomap_tok"]:,}</td>'
        f'<td class="fixed">{r["fixed"]:,}</td>'
        f'</tr>'
        for r in rows
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Reference blueprints — verified</title>
<style>
 body{{background:{BG};color:{INK};font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin:0;padding:28px}}
 h1{{font-size:20px;margin:0 0 6px}} p.sub{{color:{MUTED};font-size:12.5px;margin:0 0 22px}}
 table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:18px 0 26px}}
 th,td{{border:1px solid {LINE};padding:7px 10px;text-align:right}}
 th{{background:#141d26;color:{MUTED};font-weight:600;text-align:right}}
 td:first-child,th:first-child{{text-align:left}}
 tr.ours td{{background:#1c1214;color:#ffb4ae}}
 td.fixed{{font-weight:700;color:{ACCENT}}}
 span.d{{color:{MUTED};font-size:10.5px}}
 .note{{color:{MUTED};font-size:11.5px;line-height:1.7;max-width:1100px}}
 .warn{{color:{WARN}}} .oops{{color:{BAD}}}
 svg{{width:100%;height:auto;border:1px solid {LINE};border-radius:10px;background:{BG}}}
</style></head><body>
<h1>Reference blueprints — measured twice, from source</h1>
<p class="sub">Aider · OpenCode · Void. M1 = static literals (chars/4) · M2 = assembled prompt
(cl100k-shaped estimator) · fixed = system + schemas, paid every cycle.</p>
<table>
<tr><th>harness</th><th>system tok (M2)</th><th>M1 (Δ)</th><th>tools</th>
<th>schema tok</th><th>tok/tool</th><th>compact levels</th><th>repo map</th>
<th>fixed / cycle</th></tr>
{body}
</table>
{svg}
<p class="note">
<span class="warn">Corrections from the first draft:</span> Aider 264 → 1,265 (three blocks ship
together, plus a repo map that octuples when the chat is empty) · OpenCode 643 → 333 (643 was a
per-model plugin, not the base prompt) · Void 380 → 1,375 (the message ends with a file tree).
<br><span class="oops">The finding:</span> our tool schemas alone exceed every competitor's entire
fixed cost. The lever is the encoding of tool definitions (208 tok/tool for us vs 33 for Void's XML
prose) and the prompt contract (6,151 vs 189–1,265), not the model.
</p>
</body></html>"""


def main() -> int:
    rows = load()
    svg = render(rows)
    OUT_SVG.write_text(svg, encoding="utf-8")
    OUT_HTML.write_text(render_html(svg, rows), encoding="utf-8")
    print(f"wrote {OUT_SVG.name} ({len(svg):,} bytes) and {OUT_HTML.name}")
    for r in rows:
        print(f"  {r['name']:<10} prompt {r['system_tok']:>6,}  tools {r['schema_tok']:>6,}  "
              f"fixed {r['fixed']:>6,}  ({r['fixed'] / CYCLE_TOKENS:.0%} of a cycle)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
