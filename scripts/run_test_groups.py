#!/usr/bin/env python3
"""Execute the complete suite as process-isolated groups.

Identity comes from a pytest plugin (`scripts/collect_manifest.py`), never from
parsing console output. Every collected node ID belongs to exactly one group; the
aggregate fails if any group fails, times out, collects nothing, or loses its
report.

Why: one pytest process ran 51 minutes on a hosted runner and the runner was lost
before any result existed (run 43410282051). Isolation bounds the damage and makes
a timeout a reported status instead of a silent disappearance.

Modes
  default          run every group sequentially in this process
  --plan-only      write plan.json (deterministic assignment) and exit
  --only-group N   run exactly one planned group (for a CI matrix job)
  --only-modules   restrict the manifest (smoke tests only)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST_PLUGIN = "scripts.collect_manifest"

DEFAULT_HEAVY = [
    "src/tests/test_security_containment.py",
    "src/tests/test_desktop_renderer_architecture.py",
    "src/tests/test_hermes_browser_tools.py",
]


def pytest_cmd(wrapper: str) -> list[str]:
    return wrapper.split() if wrapper else [sys.executable, "-m", "pytest"]


def build_manifest(wrapper: str, modules: list[str], out: Path) -> list[dict]:
    env = dict(os.environ)
    env["CRUSOR_TEST_MANIFEST"] = str(out)
    cmd = pytest_cmd(wrapper) + [
        "--collect-only", "-q", "-p", MANIFEST_PLUGIN, "-p", "no:cacheprovider",
    ] + (modules or ["src/tests"])
    proc = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0 or not out.exists():
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])
        raise SystemExit(f"collection failed (exit {proc.returncode}); refusing to group")
    items = json.loads(out.read_text(encoding="utf-8"))
    if not items:
        raise SystemExit("collection produced zero tests")
    return items


def plan_groups(items: list[dict], groups: int, heavy: list[str], heavy_threshold: int):
    per_module = Counter(i["module"] for i in items)
    heavy_modules = [m for m in per_module if m in heavy or per_module[m] >= heavy_threshold]
    normal = [m for m in per_module if m not in heavy_modules]

    plan: list[dict] = []
    for m in sorted(heavy_modules):
        plan.append({"name": f"heavy-{Path(m).stem}", "modules": [m],
                     "tests": per_module[m], "heavy": True})

    slots = max(1, groups - len(plan))
    buckets: list[list[str]] = [[] for _ in range(slots)]
    load = [0] * slots
    for m in sorted(normal, key=lambda x: (-per_module[x], x)):
        i = load.index(min(load))
        buckets[i].append(m)
        load[i] += per_module[m]
    for i, b in enumerate(buckets):
        if b:
            plan.append({"name": f"group-{i:02d}", "modules": sorted(b),
                         "tests": sum(per_module[m] for m in b), "heavy": False})
    return plan, per_module


def terminate_tree(proc: subprocess.Popen) -> None:
    """Kill the whole process tree, not just the direct child.

    A group runs cold interpreters and sandbox helpers; killing only the parent
    leaves grandchildren alive, which is exactly the accumulation that made the
    single-process run unkillable. POSIX: kill the process group created by
    start_new_session. Windows: taskkill /T.
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass


def run_group(group: dict, out: Path, wrapper: str, timeout_s: int) -> dict:
    safe = group["name"]
    junit = out / f"{safe}.xml"
    log = out / f"{safe}.log"
    cmd = pytest_cmd(wrapper) + group["modules"] + [
        "-q", "--tb=short", "-p", "no:cacheprovider", f"--junitxml={junit}",
    ]
    started = time.monotonic()
    status = "ok"
    exit_code = None
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(
            cmd, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
        )
        try:
            exit_code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            terminate_tree(proc)
            status = "timeout"
    duration = round(time.monotonic() - started, 1)

    counts = None
    if junit.exists():
        try:
            root = ET.parse(junit).getroot()
            suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
            totals = Counter()
            for s in suites:
                for key in ("tests", "failures", "errors", "skipped"):
                    totals[key] += int(s.get(key, 0) or 0)
            counts = dict(totals)
        except ET.ParseError:
            counts = None

    if status == "ok":
        if exit_code == 0:
            status = "ok"
        elif exit_code == 2:
            status = "collection_error"
        elif exit_code in (1, 3, 4, 5):
            status = "test_failure"
        else:
            status = f"error_{exit_code}"
        if counts is None:
            status = "report_missing"

    return {
        "group": safe, "modules": group["modules"], "tests": group["tests"],
        "status": status, "exit": exit_code, "duration_s": duration,
        "junit": counts, "log": str(log), "report": str(junit) if junit.exists() else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=8)
    ap.add_argument("--out", default=".test-reports")
    ap.add_argument("--wrapper", default="bash scripts/run_tests.sh")
    ap.add_argument("--no-wrapper", action="store_true")
    ap.add_argument("--group-timeout", type=int, default=1200)
    ap.add_argument("--heavy-threshold", type=int, default=60)
    ap.add_argument("--heavy", default="")
    ap.add_argument("--only-modules", default="")
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--only-group", default="")
    args = ap.parse_args()
    wrapper = "" if args.no_wrapper else args.wrapper

    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)

    modules = [m.strip() for m in args.only_modules.split(",") if m.strip()]
    items = build_manifest(wrapper, modules, out / "manifest.json")
    ids = [i["nodeid"] for i in items]
    if len(ids) != len(set(ids)):
        raise SystemExit("manifest contains duplicate node ids")

    heavy = DEFAULT_HEAVY + [m.strip() for m in args.heavy.split(",") if m.strip()]
    plan, per_module = plan_groups(items, max(1, args.groups), heavy, args.heavy_threshold)

    seen: dict[str, str] = {}
    for g in plan:
        for m in g["modules"]:
            if m in seen:
                raise SystemExit(f"module assigned twice: {m}")
            seen[m] = g["name"]
    missing_modules = sorted(set(per_module) - set(seen))
    if missing_modules:
        raise SystemExit(f"modules missing from the plan: {missing_modules[:5]}")

    total_tests = len(items)
    (out / "plan.json").write_text(json.dumps({
        "manifest_tests": total_tests,
        "manifest_modules": len(per_module),
        "groups": plan,
    }, indent=2), encoding="utf-8")

    print(f"manifest {total_tests} tests / {len(per_module)} modules -> {len(plan)} groups")
    for g in plan:
        print(f"  {g['name']:34s} {len(g['modules']):3d} modules {g['tests']:5d} tests")

    if args.plan_only:
        return 0

    selected = [g for g in plan if g["name"] == args.only_group] if args.only_group else plan
    if args.only_group and not selected:
        print(f"no such group: {args.only_group}", flush=True)
        return 2

    results = [run_group(g, out, wrapper, args.group_timeout) for g in selected]
    for r in results:
        print(f"[{r['group']}] {r['status']} ({r['duration_s']}s) {r['junit'] or ''}", flush=True)

    bad = [r for r in results if r["status"] != "ok"]
    covered = sum(r["tests"] for r in results)
    complete = covered == total_tests

    (out / "summary.json").write_text(json.dumps({
        "manifest_tests": total_tests,
        "groups_run": len(results),
        "covered_tests": covered,
        "complete": complete,
        "bad_groups": len(bad),
        "results": results,
    }, indent=2), encoding="utf-8")

    print(f"\ncovered {covered}/{total_tests} | bad groups {len(bad)}/{len(results)}")
    if args.only_group:
        # Matrix mode: one job runs one group. Coverage is proved by the plan and
        # by the aggregate job, not by a single shard; exit reflects this group.
        return 1 if bad else 0
    if not complete:
        print("INCOMPLETE: this invocation did not cover the manifest", flush=True)
        return 3
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
