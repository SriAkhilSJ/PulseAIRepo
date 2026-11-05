"""
test_file_range_ingestion.py - Comprehensive Verification for Phase 9.2.2.2.

Validates:
1. Existing path-only read compatibility
2. Valid line-range read
3. Inclusive end-line behavior
4. Byte-offset read
5. Byte-limit read
6. Invalid negative offsets rejection
7. Invalid line ranges & exclusivity rejection
8. Unicode multi-byte handling
9. CRLF file handling
10. Empty file handling
11. Multi-megabyte file handling
12. Large individual lines handling
13. Path traversal rejection
14. Symlink protection & resolution
15. Concurrent file modification detection
16. Context-residency cache hit behavior
17. Cache invalidation on file mutation
18. Full-file SHA-256 consistency
19. Truncation reporting
20. Tool schema & invocation compatibility
21. Single-pass disk I/O verification (no redundant reads)
"""

import hashlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from src.tools.file_tools import read_file
from src.tools.read_cache import HardenedReadCache, _MAX_FULL_READ_BYTES
from src.runtime.run_state_ledger import AgentRunState


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "test_workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def config(workspace):
    return {"configurable": {"workspace": str(workspace), "thread_id": "test_thread"}}


# 1. Existing path-only read compatibility
def test_01_path_only_read_compatibility(workspace, config):
    test_file = workspace / "sample.py"
    test_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    result = read_file.func("sample.py", config=config)
    assert result == "def hello():\n    return 'world'\n"
    assert "File:" not in result  # Raw text without range header for standard small files


# 2. Valid line-range read
def test_02_valid_line_range_read(workspace, config):
    test_file = workspace / "lines.txt"
    lines = [f"Line {i}\n" for i in range(1, 11)]
    test_file.write_text("".join(lines), encoding="utf-8")

    result = read_file.func("lines.txt", start_line=3, end_line=5, config=config)
    assert "Range: Lines 3–5" in result
    assert "Total lines: 10" in result
    assert "Line 3\nLine 4\nLine 5" in result
    assert "Line 1" not in result
    assert "Line 6" not in result


# 3. Inclusive end-line behavior
def test_03_inclusive_end_line_behavior(workspace, config):
    test_file = workspace / "inclusive.txt"
    test_file.write_text("Alpha\nBeta\nGamma\nDelta\n", encoding="utf-8")

    result = read_file.func("inclusive.txt", start_line=2, end_line=3, config=config)
    assert "Range: Lines 2–3" in result
    assert "Beta\nGamma\n" in result
    assert "Alpha" not in result
    assert "Delta" not in result


# 4. Byte-offset read
def test_04_byte_offset_read(workspace, config):
    test_file = workspace / "bytes.txt"
    test_file.write_text("0123456789ABCDEF", encoding="utf-8")

    result = read_file.func("bytes.txt", offset=5, config=config)
    assert "Range: Bytes 5–16" in result
    assert "Total bytes: 16" in result
    assert "56789ABCDEF" in result
    assert "01234" not in result


# 5. Byte-limit read
def test_05_byte_limit_read(workspace, config):
    test_file = workspace / "bytes_limit.txt"
    test_file.write_text("0123456789ABCDEF", encoding="utf-8")

    result = read_file.func("bytes_limit.txt", offset=2, limit=6, config=config)
    assert "Range: Bytes 2–8" in result
    assert "Total bytes: 16" in result
    assert "Bytes returned: 6" in result
    assert "234567" in result


# 6. Invalid negative offsets
def test_06_invalid_negative_offsets(workspace, config):
    test_file = workspace / "dummy.txt"
    test_file.write_text("hello", encoding="utf-8")

    res1 = read_file.func("dummy.txt", offset=-1, config=config)
    assert "Error: offset must be >= 0" in res1

    res2 = read_file.func("dummy.txt", limit=-5, config=config)
    assert "Error: limit must be >= 0" in res2


# 7. Invalid line ranges & exclusivity
def test_07_invalid_line_ranges_and_exclusivity(workspace, config):
    test_file = workspace / "dummy.txt"
    test_file.write_text("hello\nworld\n", encoding="utf-8")

    res1 = read_file.func("dummy.txt", start_line=0, config=config)
    assert "Error: start_line must be >= 1" in res1

    res2 = read_file.func("dummy.txt", end_line=-2, config=config)
    assert "Error: end_line must be >= 1" in res2

    res3 = read_file.func("dummy.txt", start_line=5, end_line=3, config=config)
    assert "cannot be greater than end_line" in res3

    # Mutual exclusivity between line and byte range
    res4 = read_file.func("dummy.txt", start_line=1, offset=0, config=config)
    assert "Cannot specify both line-range" in res4


# 8. Unicode content
def test_08_unicode_content(workspace, config):
    test_file = workspace / "unicode.txt"
    content = "Line 1: 🚀 Rocket\nLine 2: 日本語テキスト\nLine 3: Été café\n"
    test_file.write_text(content, encoding="utf-8")

    result = read_file.func("unicode.txt", start_line=2, end_line=3, config=config)
    assert "日本語テキスト" in result
    assert "Été café" in result
    assert "Rocket" not in result


# 9. CRLF files
def test_09_crlf_line_handling(workspace, config):
    test_file = workspace / "crlf.txt"
    test_file.write_bytes(b"CRLF 1\r\nCRLF 2\r\nCRLF 3\r\n")

    result = read_file.func("crlf.txt", start_line=2, end_line=2, config=config)
    assert "CRLF 2" in result
    assert "CRLF 1" not in result
    assert "CRLF 3" not in result


# 10. Empty files
def test_10_empty_file(workspace, config):
    test_file = workspace / "empty.txt"
    test_file.write_bytes(b"")

    # Path-only read
    res_full = read_file.func("empty.txt", config=config)
    assert res_full == ""

    # Line range read
    res_range = read_file.func("empty.txt", start_line=1, end_line=10, config=config)
    assert "Total lines: 0" in res_range


# 11. Multi-megabyte files
def test_11_multi_megabyte_file(workspace, config):
    test_file = workspace / "large_2mb.txt"
    chunk = "A" * 1023 + "\n"  # 1024 bytes per line
    total_lines = 2048  # ~2 MB
    test_file.write_text(chunk * total_lines, encoding="utf-8")

    # Read lines 100 to 105
    res = read_file.func("large_2mb.txt", start_line=100, end_line=105, config=config)
    assert "Range: Lines 100–105" in res
    assert "Total lines: 2048" in res
    assert "Truncated: true" in res


# 12. Large individual lines
def test_12_large_individual_lines(workspace, config):
    test_file = workspace / "long_line.txt"
    long_content = "X" * 100_000
    test_file.write_text(long_content, encoding="utf-8")

    res = read_file.func("long_line.txt", offset=500, limit=200, config=config)
    assert "Range: Bytes 500–700" in res
    assert "Bytes returned: 200" in res
    assert "X" * 200 in res


# 13. Path traversal rejection
def test_13_path_traversal_rejection(workspace, config):
    with pytest.raises(ValueError, match="Path escapes workspace"):
        read_file.func("../../secret.txt", config=config)


# 14. Symlink protection & resolution
def test_14_symlink_handling(workspace, config):
    target_file = workspace / "target.txt"
    target_file.write_text("symlink target content", encoding="utf-8")

    link_file = workspace / "link.txt"
    try:
        link_file.symlink_to(target_file)
        res = read_file.func("link.txt", config=config)
        assert "symlink target content" in res
    except (OSError, NotImplementedError):
        # On Windows without SeCreateSymbolicLinkPrivilege, symlinks might not be permitted
        pytest.skip("Symlink creation not permitted in current OS privileges")


# 15. Concurrent file modification
def test_15_concurrent_file_modification(workspace, config):
    test_file = workspace / "mod.txt"
    test_file.write_text("v1 content", encoding="utf-8")

    res1 = read_file.func("mod.txt", config=config)
    assert res1 == "v1 content"

    # Mutate
    test_file.write_text("v2 content modified", encoding="utf-8")
    res2 = read_file.func("mod.txt", config=config)
    assert res2 == "v2 content modified"


# 16. Context-residency cache hit behavior
def test_16_context_residency_cache_hit(workspace):
    test_file = workspace / "resident.py"
    test_file.write_text("def resident_func(): pass\n", encoding="utf-8")

    state = AgentRunState(session_id="test_sess_range")
    cache = HardenedReadCache(run_state=state)

    # 1st read: miss
    content1, hit1 = cache.execute_read(test_file, active_prompt_text="")
    assert hit1 is False
    assert "def resident_func" in content1

    # 2nd read with filename in active context: hit
    active_prompt = "Earlier we inspected resident.py in this turn."
    receipt, hit2 = cache.execute_read(test_file, active_prompt_text=active_prompt)
    assert hit2 is True
    assert "[CONTENT RESIDENT]" in receipt
    assert "resident.py" in receipt


# 17. Cache invalidation on mutation
def test_17_cache_invalidation_on_mutation(workspace):
    test_file = workspace / "inv.py"
    test_file.write_text("initial code", encoding="utf-8")

    state = AgentRunState(session_id="test_sess_inv")
    cache = HardenedReadCache(run_state=state)

    cache.execute_read(test_file, active_prompt_text="")
    active_prompt = "Earlier we inspected inv.py"

    # Hit
    _, hit = cache.execute_read(test_file, active_prompt_text=active_prompt)
    assert hit is True

    # Mutate disk
    test_file.write_text("mutated code", encoding="utf-8")
    content, hit_after_mutation = cache.execute_read(test_file, active_prompt_text=active_prompt)
    assert hit_after_mutation is False
    assert "mutated code" in content


# 18. Full-file SHA-256 consistency
def test_18_full_file_sha256_consistency(workspace, config):
    test_file = workspace / "sha.txt"
    raw_bytes = b"deterministic content for sha verification\n"
    test_file.write_bytes(raw_bytes)
    expected_sha = hashlib.sha256(raw_bytes).hexdigest()

    res = read_file.func("sha.txt", start_line=1, end_line=1, config=config)
    assert f"SHA-256: {expected_sha}" in res


# 19. Truncation reporting
def test_19_truncation_reporting(workspace, config):
    test_file = workspace / "trunc.txt"
    test_file.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n", encoding="utf-8")

    # Range that stops before EOF -> Truncated: true
    res1 = read_file.func("trunc.txt", start_line=1, end_line=3, config=config)
    assert "Truncated: true" in res1

    # Range that reaches EOF -> Truncated: false
    res2 = read_file.func("trunc.txt", start_line=1, end_line=5, config=config)
    assert "Truncated: false" in res2

    # Byte range that stops before EOF -> Truncated: true
    res3 = read_file.func("trunc.txt", offset=0, limit=10, config=config)
    assert "Truncated: true" in res3


# 20. Tool schema & invocation compatibility
def test_20_tool_schema_and_invocation(workspace, config):
    test_file = workspace / "tool_test.py"
    test_file.write_text("print('invoked via tool')\n", encoding="utf-8")

    assert "start_line" in read_file.args
    assert "end_line" in read_file.args
    assert "offset" in read_file.args
    assert "limit" in read_file.args

    # Invoke via LangChain tool interface
    res = read_file.invoke(
        {"path": "tool_test.py", "start_line": 1, "end_line": 1},
        config=config,
    )
    assert "print('invoked via tool')" in res


# 21. Single-pass disk I/O verification (no redundant reads)
def test_21_single_pass_disk_io_verification(workspace, config):
    test_file = workspace / "io_check.txt"
    test_file.write_text("single pass i/o line 1\nsingle pass i/o line 2\n", encoding="utf-8")

    read_count = 0
    orig_open = open

    def tracked_open(*args, **kwargs):
        nonlocal read_count
        # Track open calls targeting io_check.txt
        if len(args) > 0 and "io_check.txt" in str(args[0]):
            read_count += 1
        return orig_open(*args, **kwargs)

    with patch("builtins.open", side_effect=tracked_open):
        result = read_file.func("io_check.txt", config=config)

    assert "single pass i/o line 1" in result
    # Physical disk read must occur EXACTLY ONCE
    assert read_count == 1, f"Expected exactly 1 disk read, but observed {read_count}"
