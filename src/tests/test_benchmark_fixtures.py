"""Deterministic tests for the Pulse Reliability Benchmark fixture generator.

Pure: generates tiny workspaces into pytest tmp_path only.
No network, no model calls, no process spawning, no desktop execution.

PR 1C + PR 1E: fixtures exist for all twelve tasks (PBR-001 .. PBR-012).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmarks.pulse_reliability_v1.contract import load_suite
from benchmarks.pulse_reliability_v1.fixtures import (
    FixtureFile,
    FixtureManifest,
    FixtureSpec,
    build_fixture,
    hash_tree,
    load_fixture_manifest,
    resolve_files,
)

SUITE_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "pulse_reliability_v1"
MANIFEST_PATH = SUITE_DIR / "manifest.json"
FIXTURES_PATH = SUITE_DIR / "fixtures.json"

ALL_TASK_IDS = [f"PBR-{i:03d}" for i in range(1, 13)]


def _manifest() -> FixtureManifest:
    return load_fixture_manifest(FIXTURES_PATH)


def _spec(task_id: str) -> FixtureSpec:
    return next(f for f in _manifest().fixtures if f.task_id == task_id)


@pytest.fixture(scope="session")
def built_large(tmp_path_factory) -> tuple[FixtureSpec, "object"]:
    """Build the 20k-entry fixture ONCE per test session (saves disk/inodes)."""
    spec = _spec("PBR-004")
    target = tmp_path_factory.mktemp("large-20k") / "large-20k"
    build = build_fixture(spec, target)
    return spec, build


# ---------------------------------------------------------------------------
# Manifest scope + join with the task manifest
# ---------------------------------------------------------------------------

def test_fixture_manifest_identity() -> None:
    m = _manifest()
    assert m.schema_id == "pulse-benchmark-fixtures/v1"
    assert m.suite_id == "pulse-reliability-v1"
    assert m.version == 1


def test_all_task_fixtures_ordered() -> None:
    ids = [f.task_id for f in _manifest().fixtures]
    assert ids == ALL_TASK_IDS


def test_every_task_has_a_fixture() -> None:
    suite = load_suite(MANIFEST_PATH)
    assert [t.id for t in suite.tasks] == ALL_TASK_IDS
    fixture_ids = {f.task_id for f in _manifest().fixtures}
    for task in suite.tasks:
        assert task.id in fixture_ids, f"missing fixture for {task.id}"


# ---------------------------------------------------------------------------
# Small fixture builds: exact file sets
# ---------------------------------------------------------------------------

def test_build_pbr001_empty_intent(tmp_path) -> None:
    spec = _spec("PBR-001")
    target = tmp_path / "no-folder"
    build = build_fixture(spec, target)
    assert target.is_dir()
    assert build.entry_count == 1  # only the DO_NOT_OPEN marker
    assert "DO_NOT_OPEN_README.txt" in build.files


@pytest.mark.parametrize("task_id", ["PBR-002", "PBR-003", "PBR-005", "PBR-006",
                                        "PBR-007", "PBR-008", "PBR-009", "PBR-010", "PBR-011"])
def test_build_small_fixtures_exact_file_sets(task_id: str, tmp_path) -> None:
    spec = _spec(task_id)
    target = tmp_path / spec.root
    build = build_fixture(spec, target)
    expected = set(resolve_files(spec).keys())
    assert set(build.files) == expected
    assert build.entry_count == len(expected)
    # every file exists on disk and matches the resolved content
    for rel, content in resolve_files(spec).items():
        on_disk = (target / rel).read_bytes().decode("utf-8")
        assert on_disk == content, rel


def test_pbr002_workspace_identity_marker() -> None:
    spec = _spec("PBR-002")
    content = next(f.content for f in spec.files if f.path == "workspace_proof.py")
    assert "workspace_proof.py-exact-root" in content
    assert "workspace_proof.py" in content


def test_pbr003_two_roots_with_markers() -> None:
    spec = _spec("PBR-003")
    roots = {f.path.split("/")[0] for f in spec.files}
    assert roots == {"root_a", "root_b"}


def test_pbr005_fixture_contains_failing_test() -> None:
    spec = _spec("PBR-005")
    test_content = next(f.content for f in spec.files if f.path == "tests/test_parser.py")
    assert "assert" in test_content
    # The generated test must actually fail against the generated implementation.
    impl = next(f.content for f in spec.files if f.path == "src/parser.py")
    assert "return raw" in impl and "strip" not in impl


def test_pbr006_bug_repairable_via_rule() -> None:
    spec = _spec("PBR-006")
    impl = next(f.content for f in spec.files if f.path == "src/parser.py")
    # buggy: hyphen -> underscore conversion is inverted
    assert "replace" in impl
    unrelated = next(f.content for f in spec.files if f.path == "src/util.py")
    assert "VALUE = 42" in unrelated


# ---------------------------------------------------------------------------
# Large generated fixture
# ---------------------------------------------------------------------------

def test_pbr004_generated_entry_count(built_large) -> None:
    spec, build = built_large
    assert spec.generated is not None
    assert spec.generated.count == 20_000
    expected = 20_000 + 1  # entries + README
    assert build.entry_count == expected
    assert set(build.files) == set(resolve_files(spec).keys())
    # deterministic naming + sorted, bounded content
    first = next(f for f in build.files if f.startswith("entries/e_"))
    assert re.fullmatch(r"entries/e_\d{5}\.txt", first), first


def test_generated_content_deterministic() -> None:
    spec = _spec("PBR-004")
    files = resolve_files(spec)
    sample = "entries/e_12345.txt"
    assert files[sample] == "entry 12345 PBR-004 generated fixture entry\n"


def test_pbr004_build_is_deterministic_across_roots(built_large, tmp_path) -> None:
    spec, a = built_large
    b = build_fixture(spec, tmp_path / "other-root")
    assert a.hashes == b.hashes
    assert a.files == b.files


def test_pbr004_hashes_match_disk(built_large) -> None:
    spec, build = built_large
    target = Path(build.root)
    assert hash_tree(target) == build.hashes


def test_pbr007_rename_target_wired() -> None:
    spec = _spec("PBR-007")
    impl = next(f.content for f in spec.files if f.path == "src/parser.py")
    assert "def parse_item" in impl
    service = next(f.content for f in spec.files if f.path == "src/service.py")
    assert "from src.parser import parse_item" in service
    tests = next(f.content for f in spec.files if f.path == "tests/test_parser.py")
    assert "from src.parser import parse_item" in tests


def test_pbr008_syntax_error_is_real() -> None:
    spec = _spec("PBR-008")
    content = next(f.content for f in spec.files if f.path == "src/rules.py")
    with pytest.raises(SyntaxError):
        compile(content, "src/rules.py", "exec")
    tests = next(f.content for f in spec.files if f.path == "tests/test_rules.py")
    assert "from src.rules import check" in tests


def test_pbr009_repairable_and_preexisting_distinct() -> None:
    spec = _spec("PBR-009")
    calc = next(f.content for f in spec.files if f.path == "src/calculator.py")
    assert "def divide" in calc and "return a + b" in calc  # buggy implementation
    calc_tests = next(f.content for f in spec.files if f.path == "tests/test_calculator.py")
    assert "divide(6, 2) == 3" in calc_tests  # test would fail against the bug
    legacy = next(f.content for f in spec.files if f.path == "src/legacy.py")
    assert "return False" in legacy  # pre-existing failure source
    legacy_tests = next(f.content for f in spec.files if f.path == "tests/test_legacy.py")
    assert "legacy_flag() is True" in legacy_tests  # would always fail


def test_pbr010_green_baseline_sources() -> None:
    spec = _spec("PBR-010")
    for f in spec.files:
        if f.path.endswith(".py"):
            compile(f.content, f.path, "exec")  # baseline is syntactically green
    impl = next(f.content for f in spec.files if f.path == "src/counter.py")
    assert "def bump" in impl
    main = next(f.content for f in spec.files if f.path == "src/main.py")
    assert "from src.counter import bump" in main
    tests = next(f.content for f in spec.files if f.path == "tests/test_counter.py")
    assert "bump" in tests


def test_pbr011_sleep_tree_present() -> None:
    spec = _spec("PBR-011")
    script = next(f.content for f in spec.files if f.path == "scripts/sleep_tree.py")
    compile(script, "scripts/sleep_tree.py", "exec")
    assert "subprocess.Popen" in script and "time.sleep(60)" in script


def test_pbr012_generated_2000_entries() -> None:
    spec = _spec("PBR-012")
    assert spec.generated is not None
    assert spec.generated.kind == "small-2k"
    assert spec.generated.count == 2000
    files = resolve_files(spec)
    assert len(files) == 2001  # 2000 entries + README
    assert files["entries/e_00001.txt"] == "entry 00001 PBR-012 generated fixture entry\n"


def test_small_2k_build_deterministic_and_hash_matches(tmp_path) -> None:
    spec = _spec("PBR-012")
    a = build_fixture(spec, tmp_path / "a")
    b = build_fixture(spec, tmp_path / "b")
    assert a.hashes == b.hashes
    assert hash_tree(Path(a.root)) == a.hashes
    assert a.entry_count == 2001


# ---------------------------------------------------------------------------
# Determinism regression for small fixtures too
# ---------------------------------------------------------------------------

def test_small_build_deterministic(tmp_path) -> None:
    spec = _spec("PBR-006")
    a = build_fixture(spec, tmp_path / "a")
    b = build_fixture(spec, tmp_path / "b")
    assert a.hashes == b.hashes
    assert a.files == b.files


# ---------------------------------------------------------------------------
# Validation + hygiene
# ---------------------------------------------------------------------------

def test_unsafe_paths_rejected() -> None:
    for bad in ("../escape.txt", "/abs.txt", "a/../../b.txt"):
        with pytest.raises(ValidationError):
            FixtureFile(path=bad, content="x")


def test_spec_requires_content() -> None:
    with pytest.raises(ValidationError):
        FixtureSpec(task_id="PBR-001", root="x", description="no content")


def test_fixture_content_is_ascii_only() -> None:
    m = _manifest()
    for spec in m.fixtures:
        for f in spec.files:
            f.content.encode("ascii")  # raises if non-ascii
            f.path.encode("ascii")
        if spec.generated:
            spec.generated.prefix.encode("ascii")


def test_no_secret_marker_in_fixture_content() -> None:
    patterns = (re.compile(r"ghp_[A-Za-z0-9]{20,}"), re.compile(r"sk-[A-Za-z0-9]{20,}"),
                re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"))
    m = _manifest()
    for spec in m.fixtures:
        for f in spec.files:
            for pat in patterns:
                assert not pat.search(f.content), f"{spec.task_id}/{f.path}"
