"""Dump the live Pulse system prompt tiers for a workspace — zero credits, no model call.

Runs the SAME code path the bridge/AG-UI turn uses (``view_from_config`` +
``build_system_prompt_parts``) so the bytes you read here are the bytes the provider
would have received, minus the user turn. Prints per-tier sizes and greps the joined
prompt for upstream brand tokens, which is the assertion the prompt port is built on.

Usage (repo root):
    python scripts/dump_pulse_prompt.py --workspace C:\\scratch\\pws
    python scripts/dump_pulse_prompt.py --workspace C:\\scratch\\pws --prompt-file prompts\\1.txt --out dump.json

Stdlib only; imports nothing from outside the repo.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # a script run by path gets its own folder on sys.path
    sys.path.insert(0, str(REPO_ROOT))

#: Upstream brand/vendor tokens that must never reach an emitted prompt. Filenames and
#: env-var names that legitimately mention them are not prompt text, so we only scan here.
_BRAND = re.compile(r"(?i)\bhermes\b|nous")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, prog="dump_pulse_prompt.py")
    ap.add_argument("--workspace", default=None, help="cwd the prompt should be built for")
    ap.add_argument("--prompt-file", default=None, help="task text (file), same as run_bridge_turn.py")
    ap.add_argument("--model", default=None, help="override settings.LLM_MODEL for this dump")
    ap.add_argument("--provider", default=None, help="override settings.LLM_PROVIDER for this dump")
    ap.add_argument("--surface", default=None, help="view.platform, e.g. ide | cli | bridge")
    ap.add_argument("--out", default=None, help="write the tiers as JSON here")
    args = ap.parse_args()

    from src.prompts.hermes.system_prompt import build_system_prompt_parts
    from src.prompts.hermes.view import view_from_config

    task = ""
    if args.prompt_file:
        task = pathlib.Path(args.prompt_file).read_text(encoding="utf-8")

    state: dict[str, str] = {}
    if args.workspace:
        state["workspace"] = args.workspace
    if args.model:
        state["model"] = args.model
    if args.provider:
        state["provider"] = args.provider
    if args.surface:
        state["surface"] = args.surface

    view = view_from_config(state=state, task=task)
    parts = build_system_prompt_parts(view)
    joined = "\n\n".join(parts.get(k, "") for k in ("stable", "context", "volatile"))

    print(f"model={view.model!r} provider={view.provider!r} platform={view.platform!r}")
    for key in ("stable", "context", "volatile"):
        body = parts.get(key, "")
        print(f"--- {key}: {len(body)} chars")
        print(body)
    hits = sorted(set(m.group(0).lower() for m in _BRAND.finditer(joined)))
    print(f"BRAND_HITS: {hits if hits else 'none'}")

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(parts, indent=2), encoding="utf-8")
        print(f"WROTE: {out}")
    return 0 if not hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
