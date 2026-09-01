"""Print the prompt-cache plan for a request shape — zero credits, no provider call.

The live round's Phase 2.4 gate is about the ROUTE GATE (part-level markers on `role: tool` are dropped on
LiteLLM-shaped routes), and the numbers people compare are not the same numbers: the plan's own stats report
the breakpoints it allocates, while the wire-visible count is what the provider actually receives. This prints
both, for a tool-less turn and a tool round-trip, so the relation is checkable instead of arguable.

Usage (repo root, cache flags on for a realistic plan):
    PULSEAI_PROMPT_CACHE=1 PULSEAI_PROMPT_CACHE_CUSTOM=1 \
        python3 scripts/dump_cache_plan.py --base-url https://api.sarvam.ai/v1 --model sarvam-105b
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.context.prompt_cache_plan import _count_cache_markers, build_prompt_cache_plan  # noqa: E402


def _mark_count(messages) -> int:
    """How many messages actually carry an ephemeral marker, wherever it sits."""

    def walk(node) -> str:
        if isinstance(node, dict):
            return str(node.get("cache_control")) + "".join(walk(v) for v in node.values())
        if isinstance(node, list):
            return "".join(walk(v) for v in node)
        return ""

    return sum("ephemeral" in walk(m) for m in messages)


def main() -> int:
    ap = argparse.ArgumentParser(prog="dump_cache_plan.py")
    ap.add_argument("--provider", default="custom")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--prefix-file", default=None, help="stable prefix bytes (default: a stand-in)")
    args = ap.parse_args()

    static_prefix = pathlib.Path(args.prefix_file).read_text(encoding="utf-8") if args.prefix_file else "STABLE"
    sysmsg = {"role": "system", "content": static_prefix + "\n\nCONTEXT"}
    shapes = {
        "no-tool turn": [sysmsg, {"role": "user", "content": "hi"}],
        "tool round-trip": [
            sysmsg,
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "1", "name": "read_file", "args": {}}]},
            {"role": "tool", "tool_call_id": "1", "content": "file"},
        ],
    }
    tools = [{"type": "function", "function": {"name": "read_file"}}]

    # None = the route-derived path the engine actually uses; False/True are the
    # explicit overrides, so a reader can see the gate DO the work rather than infer it.
    for flag in (None, False, True):
        for label, messages in shapes.items():
            planned, stats = build_prompt_cache_plan(
                messages, provider=args.provider, model=args.model, base_url=args.base_url,
                static_system_prefix=static_prefix, tools=tools, direct_native_tool_cache=True,
                tool_part_markers=flag,
            )
            print(json.dumps({
                "tool_part_markers_arg": flag,
                "derived_from_route": flag is None,
                "shape": label,
                "enabled": stats.get("enabled"),
                "reason": stats.get("reason"),
                "stats_markers": stats.get("markers"),
                "wire_markers": _count_cache_markers(planned),
                "messages_carrying_marker": _mark_count(planned),
                "stats_tool_part_markers": stats.get("tool_part_markers"),
            }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
