#!/usr/bin/env python3
"""Crusor Skills Hub CLI — search, install, list, remove community skills.

Same pipeline as the agent tools (src/agents/skills_hub.py), callable from a
terminal — handy for setup scripts and for verifying a catalog entry without
starting the engine.

Examples:
    python scripts/skills_hub_cli.py search "security review"
    python scripts/skills_hub_cli.py install frontend-design
    python scripts/skills_hub_cli.py install owner/repo@<full-commit-sha>
    python scripts/skills_hub_cli.py list
    python scripts/skills_hub_cli.py remove frontend-design
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Crusor Skills Hub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_search = sub.add_parser("search", help="search the curated catalog")
    p_search.add_argument("query")
    p_search.add_argument("--category", default="")

    p_install = sub.add_parser("install", help="install a skill")
    p_install.add_argument("source", help="catalog name, owner/repo, or owner/repo@sha[:subdir]")
    p_install.add_argument("--pick", default="", help="which skill when the source hosts several")

    sub.add_parser("list", help="list hub-installed skills")
    p_remove = sub.add_parser("remove", help="remove a hub-installed skill")
    p_remove.add_argument("name")
    p_update = sub.add_parser("update", help="update hub-installed skills to the catalog-pinned SHA")
    p_update.add_argument("name", nargs="?", default="", help="one skill (omit to update all)")
    p_all = sub.add_parser("all", help="list every installed skill (any origin), UI rows")
    p_toggle = sub.add_parser("toggle", help="enable/disable any installed skill")
    p_toggle.add_argument("name")
    p_toggle.add_argument("state", nargs="?", default="on", help="on|off (default on)")

    args = parser.parse_args()

    from src.agents import skills_hub as hub

    if args.cmd == "search":
        cat = hub.load_catalog()
        if not cat.get("ok"):
            print(f"error: {cat.get('error')}", file=sys.stderr)
            return 1
        res = hub.search_catalog(cat, args.query, args.category)
        if not res["results"]:
            print("no matches. categories:", ", ".join(hub.catalog_categories(cat)))
            return 0
        for e in res["results"]:
            print(f"{e['name']}  [{e['category'] or 'general'}] ({e['trust']})")
            print(f"    {e['description']}")
        return 0

    if args.cmd == "install":
        res = hub.install_skill(args.source, pick=args.pick)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if args.cmd == "list":
        res = hub.list_hub()
        rows = res.get("installed", [])
        if not rows:
            print("no hub-installed skills yet")
            return 0
        for r in rows:
            upd = "  [update available]" if r.get("update_available") else ""
            print(f"{r['name']}  {r['repo']} @ {r['sha'][:12]} [{r['trust']}]{upd}")
        return 0

    if args.cmd == "update":
        res = hub.update_hub_skill(args.name) if args.name else None
        if res is None:
            installed = hub.list_hub().get("installed", [])
            if not installed:
                print("no hub-installed skills yet")
                return 0
            targets = [r for r in installed if r.get("update_available")]
            if not targets:
                print(f"{len(installed)} installed, all at the catalog-pinned versions")
                return 0
            for r in targets:
                res = hub.update_hub_skill(str(r["name"]))
                print(json.dumps(res, indent=2))
            return 0
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if args.cmd == "all":
        res = hub.handle_hub_op("all")
        for r in res.get("skills", []):
            flags = []
            if not r["enabled"]:
                flags.append("disabled")
            if r["state"] != "active":
                flags.append(r["state"])
            print(f"{r['name']}  [{r['origin']}]{' [' + ','.join(flags) + ']' if flags else ''}  uses:{r['use_count']}")
            if r["description"]:
                print(f"    {r['description']}")
        return 0 if res.get("ok") else 1

    if args.cmd == "toggle":
        res = hub.handle_hub_op("toggle", frame={"name": args.name, "enabled": args.state})
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    if args.cmd == "remove":
        res = hub.uninstall_skill(args.name)
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
