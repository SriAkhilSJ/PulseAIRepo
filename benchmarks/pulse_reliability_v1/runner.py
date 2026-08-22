"""Pulse Reliability Benchmark v1 - runner wiring (PR 1D).

Deterministic, import-safe orchestration on top of the contract, evaluator
and fixture generator. No desktop execution, no model calls, no process
spawning, no network.

Operations (explicit CLI only; nothing runs on import):

- ``check``    - gate the suite + fixture manifests for a run
                 (fixture ids exist, roots match the manifest, every check
                 type is supported by the evaluator; optional completeness).
- ``generate`` - build every declared fixture into an explicit absolute
                 target root OUTSIDE the repository (never into Git).
- ``grade``    - evaluate a harness run record (optionally against a
                 baseline run) and write normalized result JSON + Markdown.

CLI::

    python -m benchmarks.pulse_reliability_v1.runner check --suite ... --fixtures ...
    python -m benchmarks.pulse_reliability_v1.runner check --suite ... --fixtures ... --require-complete
    python -m benchmarks.pulse_reliability_v1.runner generate --suite ... --fixtures ... --target-root C:/data/pulse-fixtures
    python -m benchmarks.pulse_reliability_v1.runner grade --suite ... --run run.json [--baseline base.json] [--out-dir results]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Sequence

from benchmarks.pulse_reliability_v1.contract import SuiteManifest, TaskManifest, load_suite
from benchmarks.pulse_reliability_v1.evaluator import (
    RunRecord,
    _CHECK_HANDLERS,
    evaluate_suite,
    render_markdown,
)
from benchmarks.pulse_reliability_v1.fixtures import (
    FixtureManifest,
    build_fixture,
    load_fixture_manifest,
    resolve_files,
)


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------

def check_suite_and_fixtures(suite: SuiteManifest, fixtures: FixtureManifest,
                             require_complete: bool = False) -> list[str]:
    """Return the list of blocking issues (empty = gate passes).

    - fixture ids must exist in the suite and be ordered (model-enforced);
    - each fixture root must match the manifest workspace fixture basename;
    - every manifest check type must have an evaluator handler;
    - optionally every manifest task must have a fixture.
    """
    issues: list[str] = []
    task_by_id = {task.id: task for task in suite.tasks}
    covered: set[str] = set()
    for spec in fixtures.fixtures:
        task = task_by_id.get(spec.task_id)
        if task is None:
            issues.append(f"fixture {spec.task_id} has no matching manifest task")
            continue
        covered.add(spec.task_id)
        expected = PurePosixPath(task.workspace.fixture).name
        if spec.root != expected:
            issues.append(
                f"fixture {spec.task_id}: root {spec.root!r} != manifest "
                f"{task.workspace.fixture!r}"
            )
    for task in suite.tasks:
        for check in task.checks:
            if check.type not in _CHECK_HANDLERS:
                issues.append(f"task {task.id} check {check.id}: unsupported type {check.type!r}")
    if require_complete:
        for task in suite.tasks:
            if task.id not in covered:
                issues.append(f"missing fixture for {task.id}")
    return issues


def check(suite_path: str | Path, fixtures_path: str | Path,
          require_complete: bool = False) -> list[str]:
    return check_suite_and_fixtures(
        load_suite(suite_path), load_fixture_manifest(fixtures_path),
        require_complete=require_complete,
    )


# ---------------------------------------------------------------------------
# External-target safety
# ---------------------------------------------------------------------------

def _find_repo_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def ensure_external_target(root: Path) -> None:
    """Guarantee a fixture target outside the repository and outside cwd."""
    if not root.is_absolute():
        raise ValueError("fixture target root must be an absolute path")
    resolved = root.resolve()
    cwd = Path.cwd().resolve()
    if resolved == cwd:
        raise ValueError("fixture target root must not be the current working directory")
    if (resolved / "benchmarks").exists():
        raise ValueError("fixture target root must not be a repository checkout")
    repo = _find_repo_root(cwd)
    if repo is not None:
        try:
            resolved.relative_to(repo.resolve())
            under_repo = True
        except ValueError:
            under_repo = False
        if under_repo:
            raise ValueError("fixture target root must be outside the repository")
    if (resolved / ".git").exists():
        raise ValueError("fixture target root must not be a git repository root")


# ---------------------------------------------------------------------------
# Generate + grade
# ---------------------------------------------------------------------------

def generate(suite_path: str | Path, fixtures_path: str | Path,
             target_root: str | Path) -> list[object]:
    """Validate, then build every fixture under an external absolute root."""
    issues = check(suite_path, fixtures_path)
    if issues:
        raise ValueError("fixture gate failed:\n  " + "\n  ".join(issues))
    root = Path(target_root)
    ensure_external_target(root)
    manifest = load_fixture_manifest(fixtures_path)
    builds = []
    for spec in manifest.fixtures:
        builds.append(build_fixture(spec, root / spec.root))
    return builds


def grade(suite_path: str | Path, run_path: str | Path,
          baseline_path: str | Path | None = None,
          out_dir: str | Path | None = None) -> tuple[object, str]:
    """Evaluate a harness run record and optionally persist JSON + Markdown."""
    suite = load_suite(suite_path)
    record = RunRecord.model_validate(
        json.loads(Path(run_path).read_text(encoding="utf-8"))
    )
    baseline = None
    if baseline_path is not None:
        baseline = RunRecord.model_validate(
            json.loads(Path(baseline_path).read_text(encoding="utf-8"))
        )
    result = evaluate_suite(suite, record, baseline)
    task = next((t for t in suite.tasks if t.id == result.task_id), None)
    markdown = render_markdown(result, task)
    if out_dir is not None:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{result.run_id}.json").write_text(
            json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (out / f"{result.run_id}.md").write_text(markdown, encoding="utf-8")
    return result, markdown


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_issues(issues: Sequence[str]) -> None:
    if issues:
        for issue in issues:
            print(f"  [gate] {issue}")
    else:
        print("  [gate] ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pulse Reliability Benchmark v1 runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="validate suite + fixture manifests")
    p_check.add_argument("--suite", required=True)
    p_check.add_argument("--fixtures", required=True)
    p_check.add_argument("--require-complete", action="store_true")

    p_gen = sub.add_parser("generate", help="generate fixtures into an external root")
    p_gen.add_argument("--suite", required=True)
    p_gen.add_argument("--fixtures", required=True)
    p_gen.add_argument("--target-root", required=True)

    p_grade = sub.add_parser("grade", help="grade a harness run record")
    p_grade.add_argument("--suite", required=True)
    p_grade.add_argument("--run", required=True)
    p_grade.add_argument("--baseline", default=None)
    p_grade.add_argument("--out-dir", default=None)

    args = parser.parse_args(argv)

    if args.command == "check":
        issues = check(args.suite, args.fixtures, require_complete=args.require_complete)
        _print_issues(issues)
        return 0 if not issues else 1

    if args.command == "generate":
        builds = generate(args.suite, args.fixtures, args.target_root)
        print(f"  generated {len(builds)} fixture(s) under {args.target_root}")
        for build in builds:
            print(f"    {build.root}: {build.entry_count} entries")
        return 0

    if args.command == "grade":
        result, markdown = grade(args.suite, args.run, args.baseline, args.out_dir)
        print(f"  task={result.task_id} outcome={result.outcome.value}")
        if args.out_dir:
            print(f"  wrote {args.out_dir}/{result.run_id}.json and .md")
        return 0

    return 2  # unreachable (subparsers required)
