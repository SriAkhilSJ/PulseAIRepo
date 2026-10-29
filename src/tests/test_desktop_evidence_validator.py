"""Machine-gate regressions for the rejected b22d6efc desktop package."""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

from scripts.validate_agent_core_desktop_evidence import (
    EXPECTED_IMPLEMENTATION,
    EXPECTED_RENDERER_STAMP,
    EXPECTED_SOURCES_HASH,
    REQUIRED_SCREENSHOTS,
    SCENARIO_SCREENSHOTS,
    validate_evidence,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REJECTED_PACKAGE = (
    REPO_ROOT / "diagnostics" / "desktop-evidence" / "agent-core-b22d6efc"
)


def test_submitted_package_is_rejected_from_raw_artifacts() -> None:
    result = validate_evidence(REJECTED_PACKAGE)
    codes = {issue.code for issue in result.errors}

    assert result.valid is False
    assert {
        "PROHIBITED_WORKSPACE",
        "SCREENSHOT_MISSING",
        "ENGINE_LOG_MISSING",
        "SESSION_SCENARIO_MISSING",
        "SCENARIO_C_WRITE_MISSING",
        "SCENARIO_F_EXECUTION_CANCELLED",
        "SCENARIO_F_NOT_FINALIZED",
        "SYNTHETIC_DESKTOP_SUBSTITUTE",
        "H_AUDIT_FINALIZATION_CONTRADICTION",
        "H_CACHE_CONTRADICTION",
    } <= codes


def test_validator_detects_the_b_and_e_report_count_defect() -> None:
    result = validate_evidence(REJECTED_PACKAGE)
    mismatches = [
        issue.message
        for issue in result.errors
        if issue.code == "REPORT_EXECUTION_COUNT_MISMATCH"
    ]

    assert len(mismatches) == 2
    assert any("Scenario B" in message and "trace has 1" in message for message in mismatches)
    assert any("Scenario E" in message and "trace has 1" in message for message in mismatches)


def test_valid_marker_hash_is_not_misreported_as_a_raw_marker_leak() -> None:
    result = validate_evidence(REJECTED_PACKAGE)
    codes = {issue.code for issue in result.errors}

    # The committed hash receipt is internally valid.  I is rejected because it
    # has no desktop session/trace/screenshot, not because its one-way hash leaks
    # the deterministically derived raw marker.
    assert "I_MARKER_HASH_MISMATCH" not in codes
    assert "I_MARKER_LENGTH_MISMATCH" not in codes
    assert "I_RAW_MARKER_LEAK" not in codes


def _png_bytes(seed: int, width: int = 640, height: int = 360) -> bytes:
    """Create a small but structurally valid, scenario-distinct RGB PNG."""
    color = bytes(((seed * 37) % 256, (seed * 71) % 256, (seed * 109) % 256))
    raw = b"".join(b"\x00" + color * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _tool(name: str, status: str, args: str, output: str = "") -> dict:
    return {
        "name": name,
        "status": status,
        "args_summary": args,
        "output_preview": output,
    }


def _append_turn(
    rows: list[dict],
    session_id: str,
    calls: list[dict],
    user_ask: str,
) -> None:
    proposed = [{**call, "status": "proposed", "output_preview": ""} for call in calls]
    rows.extend(
        [
            {
                "session_id": session_id,
                "step_index": len(rows) + 1,
                "node_name": "ai",
                "tool_calls": proposed,
                "user_ask": user_ask,
                "diagnostics": [],
            },
            {
                "session_id": session_id,
                "step_index": len(rows) + 2,
                "node_name": "tools",
                "tool_calls": calls,
                "user_ask": user_ask,
                "diagnostics": [],
            },
            {
                "session_id": session_id,
                "step_index": len(rows) + 3,
                "node_name": "finalize",
                "tool_calls": [],
                "user_ask": user_ask,
                "diagnostics": ["FINAL_VERDICT: completed"],
            },
        ]
    )


def _write_file(path: Path, text: str, *args, **kwargs) -> None:
    path.write_bytes(text.encode("utf-8"))


def _make_consistent_package(root: Path) -> None:
    for directory in ("screenshots", "traces", "reports", "sqlite", "logs"):
        (root / directory).mkdir(parents=True, exist_ok=True)

    workspace = "/home/tester/AgentCoreEvidence/b22d6efc-20261025-010203"
    session_ids = {
        "A": "session-a",
        "B": "session-b",
        "C": "session-cg",
        "D": "session-d",
        "E": "session-e",
        "F": "session-f",
        "G": "session-cg",
        "I": "session-i",
    }
    calls = {
        "A": [_tool("terminal", "success", '{"command":"python --version"}', "Python 3.11\nExit code: 0")],
        "B": [_tool("check_target_toolchains", "success", '{"target":"android"}', "Android SDK unavailable")],
        "C": [
            _tool("write_file", "success", '{"path":"scratch/interest_probe.py","content":{"__omitted__":true,"reason":"tool_body","size":20}}', "File written"),
            _tool("terminal", "success", '{"command":"python scratch/interest_probe.py"}', "interest-ok\nExit code: 0"),
        ],
        "D": [_tool("terminal", "failed", '{"command":"python -c sys.exit(3)"}', "failure-probe\nExit code: 3")],
        "E": [_tool("verify_target_app", "failed", '{"target":"android"}', "TARGET VERIFICATION UNAVAILABLE")],
        "F": [
            _tool("write_file", "success", '{"path":"scratch/cleanup_probe.py","content":{"__omitted__":true,"reason":"tool_body","size":20}}', "File written"),
            _tool("terminal", "success", '{"command":"python scratch/cleanup_probe.py"}', "cleanup-ok\nExit code: 0"),
            _tool("terminal", "success", '{"command":"rm scratch/cleanup_probe.py"}', "absent\nExit code: 0"),
        ],
        "G": [_tool("read_file", "success", '{"path":"scratch/interest_probe.py"}', 'print("interest-ok")')],
        "I": [
            _tool("write_file", "success", '{"path":"scratch/credential_probe.txt","content":{"__omitted__":true,"reason":"tool_body","size":58}}', "File written: 58 bytes"),
            _tool("terminal", "success", '{"command":"rm scratch/credential_probe.txt"}', "absent\nExit code: 0"),
        ],
    }

    trace_paths: dict[str, str] = {}
    for scenario in "ABDEFI":
        rows: list[dict] = []
        _append_turn(rows, session_ids[scenario], calls[scenario], f"Scenario {scenario} prompt")
        relative = f"traces/{scenario}.jsonl"
        trace_paths[scenario] = relative
        _write_file((root / relative), 
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )

    cg_rows = [
        {
            "session_id": session_ids["C"],
            "step_index": 1,
            "node_name": "ai",
            "tool_calls": [],
            "user_ask": "hello",
            "diagnostics": [],
        },
        {
            "session_id": session_ids["C"],
            "step_index": 2,
            "node_name": "finalize",
            "tool_calls": [],
            "user_ask": "hello",
            "diagnostics": ["FINAL_VERDICT: completed"],
        },
    ]
    _append_turn(cg_rows, session_ids["C"], calls["C"], "Create scratch/interest_probe.py")
    _append_turn(cg_rows, session_ids["G"], calls["G"], "Read scratch/interest_probe.py")
    cg_trace_text = "".join(
        json.dumps(row, separators=(",", ":")) + "\n" for row in cg_rows
    )
    _write_file((root / "traces/CG.jsonl"), cg_trace_text, encoding="utf-8")
    cg_prefix_hash = hashlib.sha256(
        b"".join(cg_trace_text.encode("utf-8").splitlines(keepends=True)[:5])
    ).hexdigest()
    trace_paths["C"] = trace_paths["G"] = "traces/CG.jsonl"

    report_paths: dict[str, str] = {}
    for scenario in "ABCDEFGI":
        count = len(calls[scenario])
        report = (
            f"# Scenario {scenario} report\n"
            f"| **Task verdict** | `completed` |\n"
            f"| **Verification status** | `unverified` |\n"
            f"| **Current-turn executed tool records** | {count} |\n"
            f"| **Current-task failed steps** | 0 |\n"
            f"| **Prompt Cache Hit Rate** | **42.0%** (42 cached) |\n"
            f"Runtime score: 90 / 100\n"
        )
        relative = f"reports/{scenario}.md"
        report_paths[scenario] = relative
        _write_file((root / relative), report, encoding="utf-8")

    sessions = []
    for scenario in "ABCDEFGI":
        entry = {
            "scenario": scenario,
            "session_id": session_ids[scenario],
            "workspace": workspace,
            "trace": trace_paths[scenario],
            "report": report_paths[scenario],
            "screenshots": list(SCENARIO_SCREENSHOTS[scenario]),
            "started_at": f"2026-10-25T0{ord(scenario) % 9}:00:00-07:00",
            "ended_at": f"2026-10-25T0{ord(scenario) % 9}:05:00-07:00",
        }
        if scenario == "G":
            entry["mode"] = "resumed"
        else:
            entry["fresh"] = True
        sessions.append(entry)
    _write_file((root / "sessions.json"), json.dumps(sessions, indent=2) + "\n", encoding="utf-8")

    screenshot_lines = ["# Screenshot manifest", ""]
    for index, filename in enumerate(REQUIRED_SCREENSHOTS, 1):
        data = _png_bytes(index)
        (root / "screenshots" / filename).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        screenshot_lines.append(
            f"- {filename} | SHA-256 {digest} | 2026-10-25T01:{index:02d}:00-07:00 | "
            f"scenario {filename.split('-', 1)[0]} | session attributable | desktop chrome"
        )
    _write_file((root / "screenshots/README.md"), "\n".join(screenshot_lines) + "\n", encoding="utf-8")

    result_rows = []
    scenario_names = {
        "A": "Quoted action + completed verdict",
        "B": "Negated mutation",
        "C": "Greeting replacement + sanitized write",
        "D": "Exit code 3",
        "E": "Verification-only execution",
        "F": "Temporary write + cleanup + turn isolation",
        "G": "Real restart hydration",
        "H": "Report honesty/coverage",
        "I": "Synthetic credential typed omission",
    }
    for scenario in "ABCDEFGHI":
        screenshots = ", ".join(f"screenshots/{name}" for name in SCENARIO_SCREENSHOTS[scenario])
        evidence = "reports/H-report-audit.md" if scenario == "H" else f"{trace_paths[scenario]}, {report_paths[scenario]}"
        result_rows.append(
            f"| {scenario} | {scenario_names[scenario]} | PASS | {screenshots} | {evidence} | sqlite/runtime_events_extract.json | Raw receipts agree. |"
        )
    result_rows_text = "\n".join(result_rows)
    results = f"""Branch: arena/test
Corrective implementation commit: {EXPECTED_IMPLEMENTATION}
Evidence-base HEAD before capture: a18ec6ba73b849766047c20ef1c150b9828891b2
OS: Linux desktop
Build commands and exit codes: npm ci (exit code 0); npx gulp compile (exit code 0); emitter (exit code 0)
Launch command: ./scripts/code.sh
Provider/model (or UNAVAILABLE): test/model
Disposable workspace: {workspace}
Workspace first-created timestamp: 2026-10-25T01:02:03-07:00
Session IDs: {', '.join(session_ids.values())}
Start/end local time with timezone: 2026-10-25T01:00:00-07:00 / 2026-10-25T02:00:00-07:00
Renderer source stamp: {EXPECTED_RENDERER_STAMP}
Renderer emitted stamp: {EXPECTED_RENDERER_STAMP}
Recomputed/committed source hash: {EXPECTED_SOURCES_HASH} / {EXPECTED_SOURCES_HASH}
Visible renderer stale state: NOT STALE
Application-code files modified: NONE

# Results

| ID | Scenario | Result | Screenshot(s) | Trace/report | SQLite/log evidence | Exact notes |
|---|---|---|---|---|---|---|
{result_rows_text}
"""
    _write_file((root / "RESULTS.md"), results, encoding="utf-8")

    provenance = f"""Target implementation: {EXPECTED_IMPLEMENTATION}
TypeScript renderer source stamp: {EXPECTED_RENDERER_STAMP}
Emitted JavaScript renderer stamp: {EXPECTED_RENDERER_STAMP}
SOURCES_HASH: {EXPECTED_SOURCES_HASH}
Recomputed source-manifest SHA-256: {EXPECTED_SOURCES_HASH}
Disposable workspace: {workspace}
Initial recursive directory listing: EMPTY
npm ci exit code 0
"""
    _write_file((root / "provenance.txt"), provenance, encoding="utf-8")

    events = []
    sequence = 1
    for scenario in "ABCDEFGI":
        for index, call in enumerate(calls[scenario]):
            call_id = f"{scenario.lower()}-{index}"
            args: dict = {"summary": call["args_summary"]}
            path_match = None
            if "interest_probe.py" in call["args_summary"]:
                path_match = "scratch/interest_probe.py"
            elif "cleanup_probe.py" in call["args_summary"]:
                path_match = "scratch/cleanup_probe.py"
            elif "credential_probe.txt" in call["args_summary"]:
                path_match = "scratch/credential_probe.txt"
            if call["name"] == "write_file" and path_match:
                size = 58 if scenario == "I" else 20
                args = {
                    "path": path_match,
                    "content": {"__omitted__": True, "reason": "tool_body", "size": size, "unit": "characters"},
                }
            events.extend(
                [
                    {
                        "seq": sequence,
                        "event_type": "tool.intent",
                        "session_id": session_ids[scenario],
                        "tool_call_id": call_id,
                        "payload": {"tool_name": call["name"], "args": args},
                    },
                    {
                        "seq": sequence + 1,
                        "event_type": "tool.result",
                        "session_id": session_ids[scenario],
                        "tool_call_id": call_id,
                        "payload": {"tool_name": call["name"], "status": "ok", "content": call["output_preview"]},
                    },
                ]
            )
            sequence += 2
    _write_file((root / "sqlite/runtime_events_extract.json"), json.dumps(events, indent=2) + "\n", encoding="utf-8")
    _write_file((root / "sqlite/verification_events_extract.json"), "[]\n", encoding="utf-8")
    _write_file((root / "sqlite/sessions_extract.json"), "[]\n", encoding="utf-8")
    _write_file((root / "sqlite/README.md"), 
        ".tables\nPRAGMA table_info(runtime_events);\nSELECT seq,event_type,session_id,turn_id,tool_call_id,payload_json\n"
        "SELECT id,created_at,session_id,workspace,command,kind,scope,status,exit_code,output\n",
        encoding="utf-8",
    )

    audit_header = (
        "| Scenario | Session ID | Report SHA-256 | Authoritative Task Verdict | Verification Status | "
        "Executed Tools | Failed Steps | Proposals | Finalization | Denominator | Measured duration | "
        "Runtime dimensions | Cache numerator | Cache denominator | Cache display | Cache treatment |\n"
    )
    audit_rows = []
    for scenario in "ABCDEFGI":
        report = (root / report_paths[scenario]).read_bytes().replace(b"\r\n", b"\n")
        digest = hashlib.sha256(report).hexdigest()
        audit_rows.append(
            f"| {scenario} | {session_ids[scenario]} | {digest} | completed | unverified | "
            f"{len(calls[scenario])} | 0 | {len(calls[scenario])} | present | / 100 | complete | 4/4 | 42 | 100 | 42.0% | scored |"
        )
    _write_file((root / "reports/H-report-audit.md"), 
        "# H audit\n\n" + audit_header + "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(audit_rows) + "\n",
        encoding="utf-8",
    )

    before_receipt = (
        "Trace line count: 5\nMaximum step index: 5\nReport step count: 5\n"
        f"Trace prefix SHA-256: {cg_prefix_hash}\nProcess state: stopped\n"
    )
    after_receipt = (
        "Trace line count: 8\nMaximum step index: 8\nReport step count: 8\n"
        f"Trace prefix SHA-256: {cg_prefix_hash}\nProcess state: relaunched\n"
    )
    _write_file((root / "logs/G-before-restart.txt"), before_receipt, encoding="utf-8")
    _write_file((root / "logs/G-after-restart.txt"), after_receipt, encoding="utf-8")
    nonce = "agent-core-omission-0123456789abcdef0123456789abcdef"
    marker = "SYNTHETIC_ONLY_DO_NOT_USE_" + hashlib.sha256(nonce.encode()).hexdigest()[:32]
    marker_hash = hashlib.sha256(marker.encode()).hexdigest()
    _write_file((root / "logs/I-marker-hash.txt"), 
        f"Nonce: {nonce}\nDerivation: prefix + sha256(nonce)[:32]\nMarker byte length: 58\nMarker SHA-256: {marker_hash}\n",
        encoding="utf-8",
    )
    _write_file((root / "logs/SANITIZATION.md"), "No replacements required.\n", encoding="utf-8")
    engine_lines = (
        [
            "engine start interval one",
            EXPECTED_IMPLEMENTATION,
            EXPECTED_RENDERER_STAMP,
            EXPECTED_SOURCES_HASH,
        ]
        + [f"engine line {index}" for index in range(30)]
        + [
            "backend launch interval two ready",
            EXPECTED_IMPLEMENTATION,
            EXPECTED_RENDERER_STAMP,
            EXPECTED_SOURCES_HASH,
        ]
    )
    _write_file((root / "logs/engine-complete.log"), "\n".join(engine_lines) + "\n", encoding="utf-8")


def test_consistent_protocol_fixture_can_pass_the_gate(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    _make_consistent_package(root)

    result = validate_evidence(root)

    assert result.valid, [f"{issue.code}: {issue.message}" for issue in result.errors]
