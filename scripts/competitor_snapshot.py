#!/usr/bin/env python3
"""Competitive body-checkup snapshot — regenerates the comparison table.

Objective metrics only, pulled from the GitHub API (no marketing claims):

    stars / forks / last push          — traction + velocity
    files, tests, CI workflows         — engineering surface
    MCP file count + capability depth  — resources / elicitation / sampling /
                                         conformance / OAuth
    system-prompt byte sizes           — the dominant per-call cost driver
    reliability-keyword density        — retry / timeout / failover / compaction
                                         / telemetry / approval

Usage
-----
    gh auth status            # required: the API calls are authenticated
    python scripts/competitor_snapshot.py
    python scripts/competitor_snapshot.py --json > snapshot.json
    python scripts/competitor_snapshot.py --diff old.json   # week-over-week

Run it weekly; the delta column is the only honest "performance tracking" for
things you do not control.

Honesty contract: file counts and byte sizes are facts; keyword density is a
PROXY for engineering emphasis, not a quality score — it says "this repo talks
about retries a lot", not "this repo retries correctly". Prompt sizes are the
static instruction payload only: tool schemas, history and output are billed on
top and are called out separately in the report.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

COMPETITORS = {
    "OpenHands": "All-Hands-AI/OpenHands",
    "Codex CLI": "openai/codex",
    "Cline": "cline/cline",
    "goose": "block/goose",
    "gemini-cli": "google-gemini/gemini-cli",
    "aider": "Aider-AI/aider",
    "SWE-agent": "SWE-agent/SWE-agent",
}

# The systems whose static instruction payload we can measure from the repo
# (path -> how it is used). Missing paths are reported, never guessed.
PROMPT_SOURCES = {
    "Codex CLI": [("openai/codex", "codex-rs/core/gpt_5_1_prompt.md"),
                  ("openai/codex", "codex-rs/protocol/src/prompts/base_instructions/default.md")],
    "goose": [("block/goose", "crates/goose/src/prompts/system.md")],
    "gemini-cli": [("google-gemini/gemini-cli", "packages/core/src/prompts/promptProvider.ts")],
    "aider": [("Aider-AI/aider", "aider/coders/base_prompts.py")],
    "SWE-agent": [("SWE-agent/SWE-agent", "config/default.yaml")],
}

# One representative core module per project for reliability-keyword density.
CORE_SOURCES = {
    "Codex CLI": ("openai/codex", "codex-rs/core/src/client.rs"),
    "goose": ("block/goose", "crates/goose/src/agents/prompt_manager.rs"),
    "gemini-cli": ("google-gemini/gemini-cli", "packages/core/src/core/client.ts"),
    "aider": ("Aider-AI/aider", "aider/coders/base_coder.py"),
    "SWE-agent": ("SWE-agent/SWE-agent", "sweagent/agent/agents.py"),
}

MCP_FEATURES = {
    "resources": r"mcp.*resource|resource.*mcp|mcp-resources",
    "elicitation": r"elicitation",
    "sampling": r"mcp.*sampl|sampl.*mcp",
    "conformance": r"conformance",
    "oauth": r"mcp.*oauth|oauth.*mcp",
}

RELIABILITY = {
    "retry": r"\b(retry|retries|backoff|jitter)\b",
    "timeout": r"\b(timeout|deadline)\b",
    "failover": r"(circuit.?breaker|failover|fallback)",
    "compaction": r"(compact|compress|summariz)",
    "telemetry": r"(otel|opentelemetry|langfuse|tracing|telemetry)",
    "approval": r"(approval|permission|confirm)",
}


def gh(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"gh api {path}: {out.stderr.strip()[:200]}")
    return json.loads(out.stdout)


def fetch_repo(slug: str) -> dict:
    meta = gh(f"repos/{slug}")
    branch = meta.get("default_branch", "main")
    tree = gh(f"repos/{slug}/git/trees/{branch}?recursive=1")
    blobs = [(t["path"], t.get("size", 0)) for t in tree.get("tree", []) if t["type"] == "blob"]
    paths = [p for p, _ in blobs]
    return {
        "slug": slug,
        "stars": meta.get("stargazers_count"),
        "forks": meta.get("forks_count"),
        "language": meta.get("language"),
        "license": (meta.get("license") or {}).get("spdx_id"),
        "pushed_at": (meta.get("pushed_at") or "")[:10],
        "files": len(paths),
        "tests": sum(
            1 for p in paths
            if re.search(r"(^|/)(tests?|testing)/", p)
            or re.search(r"test_[^/]*\.py$|_test\.(go|py|rs)$|\.test\.(ts|tsx)$|\.spec\.(ts|tsx)$", p)
        ),
        "ci_workflows": sum(1 for p in paths if p.startswith(".github/workflows/")),
        "mcp_files": sum(1 for p in paths if "mcp" in p.lower()),
        "mcp_features": {k: sum(1 for p in paths if re.search(v, p, re.I)) for k, v in MCP_FEATURES.items()},
        "prompt_files": {p: s for p, s in blobs if re.search(r"prompt|instructions", p, re.I) and s > 1500},
    }


def fetch_prompt(slug: str, path: str) -> int | None:
    out = subprocess.run(
        ["gh", "api", f"repos/{slug}/contents/{path}", "--jq", ".content"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return None
    import base64

    try:
        return len(base64.b64decode(out.stdout).decode("utf-8", "replace"))
    except Exception:
        return None


def local_metrics() -> dict:
    src = REPO_ROOT / "src"
    py = list(src.rglob("*.py"))
    text = "\n".join(p.read_text(errors="replace") for p in py)
    tests = list((src / "tests").rglob("test_*.py"))
    return {
        "files": len(py),
        "loc": text.count("\n"),
        "tests": len(tests),
        "ci_workflows": len(list((REPO_ROOT / ".github" / "workflows").glob("*.yml"))),
        "mcp_files": len([p for p in py if "mcp" in p.name.lower()]),
        "reliability_hits": {k: len(re.findall(v, text, re.I)) for k, v in RELIABILITY.items()},
        # Apples-to-apples row: ONE core module, like the competitor rows.
        "core_hits": {
            k: len(re.findall(v, (src / "graphs" / "chat_graph.py").read_text(errors="replace"), re.I))
            for k, v in RELIABILITY.items()
        },
    }


def render(results: dict, mine: dict) -> str:
    lines = []
    lines.append("| Repo | ★ | pushed | files | tests | CI | MCP files | res/elicit/sampl/conf/oauth |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---|")
    for name, r in results.items():
        f = r["mcp_features"]
        feat = "/".join(str(f[k]) for k in ("resources", "elicitation", "sampling", "conformance", "oauth"))
        lines.append(
            f"| {name} | {r['stars']:,} | {r['pushed_at']} | {r['files']:,} | "
            f"{r['tests']:,} | {r['ci_workflows']} | {r['mcp_files']} | {feat} |"
        )
    lines.append(
        f"| **CrusorAI (this repo)** | — | — | {mine['files']:,} py | {mine['tests']:,} | "
        f"{mine['ci_workflows']} | {mine['mcp_files']} | 0/0/0/0/0 |"
    )
    lines.append("")
    lines.append("| Repo | retry | timeout | failover | compaction | telemetry | approval |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for name, r in results.items():
        h = r["reliability_hits"]
        if not h:
            lines.append(f"| {name} | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {name} | {h['retry']} | {h['timeout']} | {h['failover']} | "
            f"{h['compaction']} | {h['telemetry']} | {h['approval']} |"
        )
    h = mine["core_hits"]
    lines.append(
        f"| **CrusorAI (chat_graph.py)** | {h['retry']} | {h['timeout']} | {h['failover']} | "
        f"{h['compaction']} | {h['telemetry']} | {h['approval']} |"
    )
    h = mine["reliability_hits"]
    lines.append(
        f"| *CrusorAI (whole src/)* | {h['retry']} | {h['timeout']} | {h['failover']} | "
        f"{h['compaction']} | {h['telemetry']} | {h['approval']} |"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--diff", metavar="OLD_JSON", help="compare against a previous snapshot")
    ap.add_argument("--only", help="comma-separated subset, e.g. codex,cline")
    args = ap.parse_args(argv)

    wanted = COMPETITORS
    if args.only:
        keys = {k.strip().lower() for k in args.only.split(",")}
        wanted = {n: s for n, s in COMPETITORS.items()
                  if n.lower() in keys or s.split("/")[-1].lower() in keys}

    results = {}
    for name, slug in wanted.items():
        try:
            r = fetch_repo(slug)
        except RuntimeError as exc:
            print(f"[snapshot] {name}: {exc}", file=sys.stderr)
            continue
        r["reliability_hits"] = {}
        results[name] = r

    for name, (slug, path) in CORE_SOURCES.items():
        if name not in results:
            continue
        out = subprocess.run(
            ["gh", "api", f"repos/{slug}/contents/{path}", "--jq", ".content"],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            continue
        import base64

        try:
            text = base64.b64decode(out.stdout).decode("utf-8", "replace")
        except Exception:
            continue
        results[name]["core_file"] = {"path": path, "chars": len(text)}
        results[name]["reliability_hits"] = {
            k: len(re.findall(v, text, re.I)) for k, v in RELIABILITY.items()
        }

    for name, sources in PROMPT_SOURCES.items():
        if name not in results:
            continue
        sizes = {}
        for slug, path in sources:
            size = fetch_prompt(slug, path)
            if size is not None:
                sizes[path] = {"chars": size, "tokens_est": size // 4}
        results[name]["prompt_sizes"] = sizes

    mine = local_metrics()
    payload = {"competitors": results, "local": mine}

    delta = {}
    if args.diff:
        old = json.loads(Path(args.diff).read_text())
        # Snapshots written before 2026-10-31 wrapped the payload; accept both.
        old = old.get("payload", old)
        for name, r in results.items():
            prev = (old.get("competitors", {}).get(name) or {})
            if not prev:
                delta[name] = {"new": True}
                continue
            row = {}
            for field in ("stars", "forks", "files", "tests", "ci_workflows",
                          "mcp_files"):
                d = (r.get(field) or 0) - (prev.get(field) or 0)
                if d:
                    row[field] = d
            if (r.get("pushed_at") or "") != (prev.get("pushed_at") or ""):
                row["pushed_at"] = [prev.get("pushed_at"), r.get("pushed_at")]
            for feat, cur in (r.get("mcp_features") or {}).items():
                d = (cur or 0) - ((prev.get("mcp_features") or {}).get(feat) or 0)
                if d:
                    row[f"mcp_{feat}"] = d
            for key, cur in (r.get("reliability_hits") or {}).items():
                d = (cur or 0) - ((prev.get("reliability_hits") or {}).get(key) or 0)
                if d:
                    row[f"rel_{key}"] = d
            prev_prompts = prev.get("prompt_sizes") or {}
            for path, meta in (r.get("prompt_sizes") or {}).items():
                old_chars = (prev_prompts.get(path) or {}).get("chars")
                if old_chars is not None and old_chars != meta.get("chars"):
                    row[f"prompt_chars:{path}"] = meta.get("chars", 0) - old_chars
            if row:
                delta[name] = row
        payload["diff"] = delta
        payload["diff_against"] = args.diff

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(render(results, mine))

    if args.diff:
        print("\n### Since last snapshot")
        if not delta:
            print("  no changes")
        for name, row in sorted(delta.items()):
            bits = []
            for field, d in row.items():
                if field == "new":
                    bits.append("new in this comparison")
                elif isinstance(d, list):
                    bits.append(f"{field.split('_')[0]} {d[0]} -> {d[1]}")
                elif field.startswith("prompt_chars:"):
                    bits.append(f"{field.split(':', 1)[1]} {d:+,} chars")
                else:
                    bits.append(f"{field} {d:+,}")
            print(f"  {name}: " + " · ".join(bits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
