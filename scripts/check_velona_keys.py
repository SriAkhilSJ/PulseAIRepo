#!/usr/bin/env python3
"""Check that the configured Velona keys are real, and that the three models answer.

Why this exists: "the key is set" and "the key works" are different claims, and a
missing/wrong key fails deep inside a turn where it looks like a model bug. This
asks the question directly, in one command, before any run costs tokens.

What it proves, in order:

  1. PRESENT   a key is configured at all (CUSTOM_API_KEYS / CUSTOM_API_KEY /
               CRUSORAI_CHEAP_API_KEY), non-empty after trimming — a copied
               trailing newline is the classic "invalid header" bug.
  2. SHAPE     it looks like a Velona key (key_live_ prefix, plausible length,
               no whitespace). Never prints the key: only length + last 4.
  3. CATALOG   the key authenticates against the gateway (GET /gateway/v1/models)
               and the three models we care about are actually on offer.
  4. LIVE      each model completes a 1-token chat call (POST /v1/chat/completions).
               That is the only step that can distinguish "valid key" from
               "valid key, wrong model id, no credit".

Usage:
  export CUSTOM_API_KEY='...'          # or CUSTOM_API_KEYS='a,b'
  python scripts/check_velona_keys.py
  python scripts/check_velona_keys.py --json
  python scripts/check_velona_keys.py --offline     # 1+2 only, no network

Exit codes: 0 all green, 1 a check failed, 2 nothing to check (no key).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://velona.in/v1"
# The three models the last evaluation pinned (src/llm/capabilities.py) plus the
# auxiliary model the engine routes management calls to.
MODELS = [
    ("z-ai/glm-5.3-flash", "main"),
    ("deepseek/deepseek-v4.1-flash", "main"),
    ("qwen/qwen3.7-flash", "aux"),
]
# Velona's edge rejects the OpenAI SDK's default UA (Cloudflare); a browser UA works.
UA = os.environ.get(
    "CRUSORAI_HTTP_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
TIMEOUT = float(os.environ.get("VELONA_CHECK_TIMEOUT", "20"))


def mask(key: str) -> str:
    """A key's fingerprint without the key: length and last four."""
    return f"len={len(key)} …{key[-4:]}" if len(key) >= 4 else f"len={len(key)}"


def collect_keys() -> list[tuple[str, str]]:
    """(source, key) pairs, trimmed, de-duplicated, never logged raw."""
    found: list[tuple[str, str]] = []
    multi = os.environ.get("CUSTOM_API_KEYS", "")
    if multi.strip():
        for i, part in enumerate(multi.split(",")):
            # tolerate "name:key" as well as bare keys
            key = part.split(":")[-1].strip() if ":" in part else part.strip()
            if key:
                found.append((f"CUSTOM_API_KEYS[{i}]", key))
    for src in ("CUSTOM_API_KEY", "CRUSORAI_CHEAP_API_KEY"):
        raw = os.environ.get(src, "")
        if raw.strip():
            found.append((src, raw.strip()))
    seen, unique = set(), []
    for src, key in found:
        if key not in seen:
            seen.add(key)
            unique.append((src, key))
    return unique


def check_shape(key: str) -> tuple[bool, str]:
    if key != key.strip():
        return False, "leading/trailing whitespace (a copied newline breaks the header)"
    if re.search(r"\s", key):
        return False, "contains whitespace"
    if not key.startswith("key_live_"):
        return False, "does not start with key_live_ (is this a Velona key?)"
    if len(key) < 20:
        return False, f"implausibly short ({len(key)} chars) for a live key"
    return True, "key_live_*, no whitespace"


def extract_model_ids(body: object) -> list[str]:
    """Model ids from any catalog shape.

    The gateway answered 200 with a payload this code could not read, which made
    "is the model on offer" unanswerable while looking like an empty catalog. So:
    walk whatever shape arrives and collect anything that names a model. A wrong
    guess here now yields ids, not a silent zero.
    """
    ids: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key in ("id", "model", "model_id", "name"):
                value = node.get(key)
                if isinstance(value, str) and value.strip() and ("/" in value or len(value) > 3):
                    ids.append(value.strip())
                    break
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body)
    seen, unique = set(), []
    for mid in ids:
        if mid not in seen:
            seen.add(mid)
            unique.append(mid)
    return unique[:500]


def describe_shape(body: object) -> str:
    """Top-level structure only — never values, so this is safe to print."""
    if isinstance(body, dict):
        return "object with keys: " + ", ".join(list(body)[:12])
    if isinstance(body, list):
        return f"list of {len(body)}" + ("" if not body else f"; first is {type(body[0]).__name__}")
    return type(body).__name__


def _get(url: str, key: str) -> tuple[int, dict | str, float]:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": UA,
        "Accept": "application/json",
    })
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace")), time.time() - started
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        return exc.code, body, time.time() - started
    except Exception as exc:  # DNS, TLS, timeout, egress blocked
        return 0, f"{type(exc).__name__}: {exc}"[:300], time.time() - started


def _post(url: str, key: str, payload: dict) -> tuple[int, dict | str, float]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {key}",
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="POST")
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace")), time.time() - started
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        return exc.code, body, time.time() - started
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"[:300], time.time() - started


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=os.environ.get("CUSTOM_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--offline", action="store_true", help="presence and shape only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    gateway_root = base[:-3] if base.endswith("/v1") else base

    keys = collect_keys()
    report: dict = {
        "base": base,
        "keys": [],
        "models": [m for m, _role in MODELS],
        "ok": False,
        "verdict": "",
    }
    if not keys:
        report["verdict"] = (
            "no key configured: set CUSTOM_API_KEY (or CUSTOM_API_KEYS) — "
            "nothing to test"
        )
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"FAIL  no key found. Looked for CUSTOM_API_KEYS, CUSTOM_API_KEY, "
                  f"CRUSORAI_CHEAP_API_KEY.\n      base: {base}")
        return 2

    catalog_ok = False
    for src, key in keys:
        entry: dict = {"source": src, "fingerprint": mask(key)}
        shape_ok, shape_note = check_shape(key)
        entry["shape"] = {"ok": shape_ok, "note": shape_note}
        if not shape_ok or args.offline:
            entry["catalog"] = {"skipped": True}
            report["keys"].append(entry)
            continue

        status, body, secs = _get(f"{gateway_root}/gateway/v1/models", key)
        ids = extract_model_ids(body) if status == 200 else []
        # No catalog parsed => we know nothing. Never report "offered" on a guess.
        offered = {m: (m in ids if ids else None) for m, _r in MODELS}
        catalog_ok = catalog_ok or (status == 200)
        entry["catalog"] = {
            "status": status,
            "ok": status == 200,
            "seconds": round(secs, 2),
            "model_count": len(ids),
            "catalog_shape": describe_shape(body) if status == 200 else None,
            "offered": offered,
            "note": None if status == 200 else str(body)[:200],
        }

        entry["live"] = []
        for model, role in MODELS:
            st, payload, took = _post(f"{base}/chat/completions", key, {
                "model": model,
                "messages": [{"role": "user", "content": "reply with the single word: ok"}],
                "max_tokens": 1,
                "stream": False,
            })
            text = ""
            if isinstance(payload, dict):
                try:
                    text = payload["choices"][0]["message"]["content"] or ""
                except Exception:
                    text = ""
            entry["live"].append({
                "model": model,
                "role": role,
                "status": st,
                "ok": st == 200,
                "seconds": round(took, 2),
                "warm": text.strip()[:16],
                "note": None if st == 200 else str(payload)[:200],
            })
        report["keys"].append(entry)

    if args.offline:
        shapes_ok = all(k["shape"]["ok"] for k in report["keys"])
        report["ok"] = shapes_ok
        report["verdict"] = ("presence and shape checked; network not touched"
                             if shapes_ok else "a configured key is malformed")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for k in report["keys"]:
                print(f"key {k['source']:22s} {k['fingerprint']}")
                print(f"  shape   {'ok  ' if k['shape']['ok'] else 'FAIL'} {k['shape']['note']}")
            print(f"\nVERDICT: {report['verdict']}")
        return 0 if shapes_ok else 1

    live = [c for k in report["keys"] for c in k.get("live", [])]
    report["ok"] = catalog_ok and bool(live) and all(c["ok"] for c in live)
    if report["ok"]:
        report["verdict"] = f"all {len(live)} model calls answered; key authenticates"
    elif not catalog_ok and live:
        report["verdict"] = "catalog probe failed — key, egress, or base URL is wrong"
    elif live:
        bad = [c["model"] for c in live if not c["ok"]]
        report["verdict"] = f"{len(bad)}/{len(live)} model calls failed: {', '.join(bad)}"
    else:
        report["verdict"] = "shape checked only (offline or no usable key)"

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for k in report["keys"]:
            print(f"key {k['source']:22s} {k['fingerprint']}")
            print(f"  shape   {'ok  ' if k['shape']['ok'] else 'FAIL'} {k['shape']['note']}")
            cat = k.get("catalog") or {}
            if cat.get("skipped"):
                print("  catalog skipped")
            else:
                print(f"  catalog {'ok  ' if cat.get('ok') else 'FAIL'} "
                      f"HTTP {cat.get('status')} in {cat.get('seconds')}s, "
                      f"{cat.get('model_count')} models"
                      + (f" ({cat['catalog_shape']})" if cat.get("catalog_shape") else "")
                      + ("" if cat.get("ok") else f" — {cat.get('note')}"))
                for model, present in (cat.get("offered") or {}).items():
                    mark = "?" if present is None else ("✓" if present else "✗")
                    suffix = "catalog unreadable" if present is None else "offered"
                    print(f"    {mark} {model} {suffix}")
            for c in k.get("live", []):
                print(f"  live    {'ok  ' if c['ok'] else 'FAIL'} {c['model']:30s} "
                      f"HTTP {c['status']} {c['seconds']}s"
                      + ("" if c["ok"] else f" — {c['note']}"))
        print(f"\nVERDICT: {report['verdict']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
