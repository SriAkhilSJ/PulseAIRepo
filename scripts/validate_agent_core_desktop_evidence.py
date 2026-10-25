#!/usr/bin/env python3
"""Validate Agent Core desktop evidence against the b22d6efc rerun protocol.

This is an evidence-integrity gate, not a product acceptance oracle.  A truthful
FAIL or UNAVAILABLE may pass this validator when its raw receipts are complete
and consistent.  Unsupported PASS claims, synthetic substitutes, missing raw
artifacts, prohibited workspaces, and report/trace contradictions fail closed.

Usage:
    python scripts/validate_agent_core_desktop_evidence.py \
        diagnostics/desktop-evidence/agent-core-b22d6efc
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EXPECTED_IMPLEMENTATION = "b22d6efce922357ca7c04b3e59106db2da86849d"
EXPECTED_RENDERER_STAMP = "2026-10-25-41"
EXPECTED_SOURCES_HASH = "9f13da07532512350fc000a8b21039cedced820f1f295381e0f53e0987588d6c"
SCENARIOS = tuple("ABCDEFGHI")
SESSION_SCENARIOS = tuple("ABCDEFGI")
FRESH_SCENARIOS = tuple("ABCDEFI")
ALLOWED_RESULTS = frozenset({"PASS", "FAIL", "UNAVAILABLE"})
PROHIBITED_WORKSPACE_MARKERS = ("testcrusor",)
MUTATION_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "copy_file",
        "install_toolchain",
        "build_target",
    }
)
TERMINAL_TOOLS = frozenset({"terminal", "run_terminal", "execute_code"})
REQUIRED_SCREENSHOTS = (
    "00-build-identity.png",
    "01-disposable-workspace.png",
    "A-final.png",
    "B-final.png",
    "C-final.png",
    "D-final.png",
    "E-final.png",
    "F-final.png",
    "F-file-absent.png",
    "G-resumed-before-prompt.png",
    "G-final.png",
    "H-report-audit.png",
    "I-final.png",
)
SCENARIO_SCREENSHOTS = {
    "A": ("A-final.png",),
    "B": ("B-final.png",),
    "C": ("C-final.png",),
    "D": ("D-final.png",),
    "E": ("E-final.png",),
    "F": ("F-final.png", "F-file-absent.png"),
    "G": ("G-resumed-before-prompt.png", "G-final.png"),
    "H": ("H-report-audit.png",),
    "I": ("I-final.png",),
}
REQUIRED_RESULT_HEADERS = (
    "Branch",
    "Corrective implementation commit",
    "Evidence-base HEAD before capture",
    "OS",
    "Build commands and exit codes",
    "Launch command",
    "Provider/model (or UNAVAILABLE)",
    "Disposable workspace",
    "Workspace first-created timestamp",
    "Session IDs",
    "Start/end local time with timezone",
    "Renderer source stamp",
    "Renderer emitted stamp",
    "Recomputed/committed source hash",
    "Visible renderer stale state",
    "Application-code files modified",
)


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    path: str | None = None


@dataclass
class MatrixRow:
    scenario: str
    result: str
    cells: list[str]
    raw: str


@dataclass
class ToolRecord:
    name: str
    status: str
    args: str
    output: str
    step_index: int | None


@dataclass
class TraceData:
    path: Path
    rows: list[dict[str, Any]]

    def finalized_segments(self) -> list[list[dict[str, Any]]]:
        segments: list[list[dict[str, Any]]] = []
        pending: list[dict[str, Any]] = []
        for row in self.rows:
            pending.append(row)
            if str(row.get("node_name", "")).lower() == "finalize":
                segments.append(pending)
                pending = []
        if pending:
            segments.append(pending)
        return segments


@dataclass
class ValidationResult:
    root: Path
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "validator": "agent-core-desktop-evidence-b22d6efc",
            "root": str(self.root),
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [asdict(issue) for issue in self.issues],
        }


class EvidenceValidator:
    """Fail-closed validator for the corrected Agent Core desktop protocol."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.issues: list[Issue] = []
        self.results_text = ""
        self.headers: dict[str, str] = {}
        self.matrix: dict[str, MatrixRow] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.traces: dict[Path, TraceData] = {}
        self.scenario_traces: dict[str, TraceData] = {}
        self.scenario_reports: dict[str, Path] = {}
        self.report_text: dict[str, str] = {}
        self.runtime_events: list[dict[str, Any]] = []

    def error(self, code: str, message: str, path: Path | str | None = None) -> None:
        rendered_path: str | None = None
        if path is not None:
            candidate = Path(path)
            try:
                rendered_path = str(candidate.resolve().relative_to(self.root))
            except (OSError, ValueError):
                rendered_path = str(path)
        self.issues.append(Issue("error", code, message, rendered_path))

    def warning(self, code: str, message: str, path: Path | str | None = None) -> None:
        rendered_path: str | None = None
        if path is not None:
            candidate = Path(path)
            try:
                rendered_path = str(candidate.resolve().relative_to(self.root))
            except (OSError, ValueError):
                rendered_path = str(path)
        self.issues.append(Issue("warning", code, message, rendered_path))

    def validate(self) -> ValidationResult:
        if not self.root.is_dir():
            self.error("EVIDENCE_ROOT_MISSING", "Evidence root is not a directory.", self.root)
            return ValidationResult(self.root, self.issues)

        self._validate_structure()
        self._load_results()
        self._load_sessions()
        self._validate_provenance()
        self._validate_workspace_markers()
        self._validate_screenshots()
        self._load_traces_and_reports()
        self._validate_trace_report_consistency()
        self._load_and_validate_sqlite()
        self._validate_scenarios()
        self._validate_h_audit()
        self._validate_omission_marker()
        self._validate_engine_log()
        self._validate_synthetic_substitutes()
        self._deduplicate_issues()
        return ValidationResult(self.root, self.issues)

    def _deduplicate_issues(self) -> None:
        seen: set[tuple[str, str, str, str | None]] = set()
        unique: list[Issue] = []
        for issue in self.issues:
            key = (issue.severity, issue.code, issue.message, issue.path)
            if key not in seen:
                seen.add(key)
                unique.append(issue)
        self.issues = unique

    def _validate_structure(self) -> None:
        for filename in ("RESULTS.md", "provenance.txt", "sessions.json"):
            path = self.root / filename
            if not path.is_file():
                self.error("REQUIRED_FILE_MISSING", f"Required file is missing: {filename}", path)
        for dirname in ("screenshots", "traces", "reports", "sqlite", "logs"):
            path = self.root / dirname
            if not path.is_dir():
                self.error("REQUIRED_DIRECTORY_MISSING", f"Required directory is missing: {dirname}/", path)
        required_auxiliary = (
            "screenshots/README.md",
            "sqlite/README.md",
            "logs/engine-complete.log",
            "logs/G-before-restart.txt",
            "logs/G-after-restart.txt",
            "logs/I-marker-hash.txt",
            "logs/SANITIZATION.md",
            "reports/H-report-audit.md",
        )
        for relative in required_auxiliary:
            path = self.root / relative
            if not path.is_file():
                code = "ENGINE_LOG_MISSING" if relative.endswith("engine-complete.log") else "REQUIRED_FILE_MISSING"
                self.error(code, f"Required evidence artifact is missing: {relative}", path)

    @staticmethod
    def _read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _load_results(self) -> None:
        path = self.root / "RESULTS.md"
        if not path.is_file():
            return
        try:
            self.results_text = self._read_text(path)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"RESULTS.md is not valid UTF-8: {exc}", path)
            return

        preamble = self.results_text.split("\n#", 1)[0]
        for line in preamble.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            self.headers[key.strip()] = value.strip()

        for key in REQUIRED_RESULT_HEADERS:
            value = self.headers.get(key)
            if not value:
                self.error("RESULTS_HEADER_MISSING", f"RESULTS.md lacks required non-empty header: {key}", path)

        implementation = self.headers.get("Corrective implementation commit", "")
        if implementation and implementation != EXPECTED_IMPLEMENTATION:
            self.error(
                "IMPLEMENTATION_MISMATCH",
                f"Corrective implementation commit is {implementation!r}, expected {EXPECTED_IMPLEMENTATION}.",
                path,
            )
        for key in ("Renderer source stamp", "Renderer emitted stamp"):
            value = self.headers.get(key, "")
            if value and value != EXPECTED_RENDERER_STAMP:
                self.error("RENDERER_STAMP_MISMATCH", f"{key} is {value!r}, expected {EXPECTED_RENDERER_STAMP}.", path)
        hashes = self.headers.get("Recomputed/committed source hash", "")
        if hashes and hashes.count(EXPECTED_SOURCES_HASH) < 2:
            self.error(
                "SOURCE_HASH_PROOF_INCOMPLETE",
                "RESULTS.md must state both recomputed and committed source hashes explicitly.",
                path,
            )
        stale = self.headers.get("Visible renderer stale state", "").strip().upper()
        if stale and stale != "NOT STALE":
            self.error("RENDERER_IDENTITY_UNPROVEN", f"Visible renderer stale state is {stale!r}, not 'NOT STALE'.", path)
        modified = self.headers.get("Application-code files modified", "").strip().upper()
        if modified and modified != "NONE":
            self.error("DESKTOP_MODIFIED_APPLICATION_CODE", "Desktop evidence reports application-code modifications.", path)
        build_receipt = self.headers.get("Build commands and exit codes", "")
        if build_receipt and not re.search(r"(?:exit(?:\s+code)?\s*[:=]?\s*0|\(0\))", build_receipt, re.IGNORECASE):
            self.error("BUILD_EXIT_CODE_MISSING", "Build header does not include a successful numeric exit-code receipt.", path)

        for line in self.results_text.splitlines():
            if not re.match(r"^\|\s*[A-I]\s*\|", line):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            scenario = cells[0].upper()
            result = cells[2].upper()
            self.matrix[scenario] = MatrixRow(scenario, result, cells, line)

        for scenario in SCENARIOS:
            row = self.matrix.get(scenario)
            if row is None:
                self.error("RESULTS_SCENARIO_MISSING", f"RESULTS.md has no matrix row for scenario {scenario}.", path)
                continue
            if row.result not in ALLOWED_RESULTS:
                self.error(
                    "RESULTS_VERDICT_INVALID",
                    f"Scenario {scenario} uses {row.result!r}; only PASS, FAIL, or UNAVAILABLE are allowed.",
                    path,
                )
            for screenshot in SCENARIO_SCREENSHOTS[scenario]:
                if screenshot not in row.raw:
                    self.error(
                        "RESULTS_SCREENSHOT_REFERENCE_MISSING",
                        f"Scenario {scenario} row does not reference required screenshot {screenshot}.",
                        path,
                    )

    def _load_json(self, path: Path, code: str = "JSON_PARSE_ERROR") -> Any | None:
        if not path.is_file():
            return None
        try:
            return json.loads(self._read_text(path))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.error(code, f"Could not parse JSON: {exc}", path)
            return None

    def _load_sessions(self) -> None:
        path = self.root / "sessions.json"
        raw = self._load_json(path)
        if raw is None:
            return
        entries: list[dict[str, Any]] = []
        if isinstance(raw, list):
            entries = [entry for entry in raw if isinstance(entry, dict)]
        elif isinstance(raw, dict) and isinstance(raw.get("sessions"), list):
            entries = [entry for entry in raw["sessions"] if isinstance(entry, dict)]
        elif isinstance(raw, dict):
            for scenario, entry in raw.items():
                if isinstance(entry, dict) and str(scenario).upper() in SESSION_SCENARIOS:
                    entries.append({"scenario": str(scenario).upper(), **entry})
        else:
            self.error("SESSIONS_SCHEMA_INVALID", "sessions.json must be a list or scenario map.", path)
            return

        for entry in entries:
            scenario = str(entry.get("scenario", "")).upper()
            if scenario not in SESSION_SCENARIOS:
                self.error("SESSION_SCENARIO_INVALID", f"Unknown or missing session scenario: {scenario!r}", path)
                continue
            if scenario in self.sessions:
                self.error("SESSION_SCENARIO_DUPLICATE", f"Scenario {scenario} appears more than once.", path)
                continue
            self.sessions[scenario] = entry

        for scenario in SESSION_SCENARIOS:
            if scenario not in self.sessions:
                self.error("SESSION_SCENARIO_MISSING", f"sessions.json has no desktop session mapping for {scenario}.", path)

        for scenario, entry in self.sessions.items():
            session_id = str(entry.get("session_id") or entry.get("id") or "").strip()
            if not session_id:
                self.error("SESSION_ID_MISSING", f"Scenario {scenario} has no actual session ID.", path)
            workspace = str(entry.get("workspace") or "").strip()
            if not workspace:
                self.error("SESSION_WORKSPACE_MISSING", f"Scenario {scenario} has no canonical workspace.", path)
            elif self._is_prohibited_workspace(workspace):
                self.error(
                    "PROHIBITED_WORKSPACE",
                    f"Scenario {scenario} used prohibited/reused workspace {workspace!r}.",
                    path,
                )
            for field_kind, aliases in {
                "trace filename": ("trace", "trace_file", "trace_filename"),
                "report filename": ("report", "report_file", "report_filename"),
                "screenshots": ("screenshots", "screenshot_files"),
                "start time": ("started_at", "start_time", "start_utc"),
                "end time": ("ended_at", "end_time", "end_utc"),
            }.items():
                if not any(entry.get(alias) for alias in aliases):
                    self.error(
                        "SESSION_METADATA_MISSING",
                        f"Scenario {scenario} session mapping lacks {field_kind}.",
                        path,
                    )

        fresh_ids: dict[str, str] = {}
        for scenario in FRESH_SCENARIOS:
            entry = self.sessions.get(scenario)
            if not entry:
                continue
            session_id = str(entry.get("session_id") or entry.get("id") or "")
            mode = str(entry.get("mode") or entry.get("session_mode") or "").lower()
            fresh = entry.get("fresh")
            if fresh is not True and mode != "fresh":
                self.error("SESSION_NOT_MARKED_FRESH", f"Scenario {scenario} must be marked fresh.", path)
            if session_id in fresh_ids and session_id:
                self.error(
                    "FRESH_SESSION_REUSED",
                    f"Scenarios {fresh_ids[session_id]} and {scenario} reuse session {session_id}.",
                    path,
                )
            elif session_id:
                fresh_ids[session_id] = scenario

        c_entry = self.sessions.get("C")
        g_entry = self.sessions.get("G")
        if c_entry and g_entry:
            c_id = str(c_entry.get("session_id") or c_entry.get("id") or "")
            g_id = str(g_entry.get("session_id") or g_entry.get("id") or "")
            if not c_id or c_id != g_id:
                self.error("G_NOT_RESUMED_FROM_C", "Scenario G must use C's exact desktop session ID.", path)
            mode = str(g_entry.get("mode") or g_entry.get("session_mode") or "").lower()
            if g_entry.get("resumed") is not True and mode != "resumed":
                self.error("G_NOT_MARKED_RESUMED", "Scenario G must be marked resumed, not fresh.", path)

    @staticmethod
    def _is_prohibited_workspace(value: str) -> bool:
        normalized = value.replace("\\", "/").casefold()
        return any(marker in normalized for marker in PROHIBITED_WORKSPACE_MARKERS)

    def _validate_provenance(self) -> None:
        path = self.root / "provenance.txt"
        if not path.is_file():
            return
        try:
            text = self._read_text(path)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"provenance.txt is not UTF-8: {exc}", path)
            return
        for expected, label in (
            (EXPECTED_IMPLEMENTATION, "implementation commit"),
            (EXPECTED_RENDERER_STAMP, "renderer stamp"),
            (EXPECTED_SOURCES_HASH, "committed source hash"),
        ):
            if expected not in text:
                self.error("PROVENANCE_VALUE_MISSING", f"Provenance lacks expected {label}: {expected}", path)
        if not re.search(
            rf"recomputed[^\n]*{re.escape(EXPECTED_SOURCES_HASH)}",
            text,
            re.IGNORECASE,
        ):
            self.error(
                "RECOMPUTED_HASH_RECEIPT_MISSING",
                "Provenance does not print the freshly recomputed source hash value.",
                path,
            )
        workspace_match = re.search(r"^Disposable workspace:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
        if not workspace_match:
            self.error("PROVENANCE_WORKSPACE_MISSING", "Provenance lacks the disposable workspace path.", path)
        elif self._is_prohibited_workspace(workspace_match.group(1)):
            self.error("PROHIBITED_WORKSPACE", "Provenance identifies the known reused testCRUSOR workspace.", path)
        if not re.search(r"initial recursive directory listing", text, re.IGNORECASE):
            self.error(
                "INITIAL_WORKSPACE_LISTING_MISSING",
                "Provenance lacks the required initial recursive directory listing receipt.",
                path,
            )
        if not re.search(r"(?:npm ci|npm install)[^\n]*(?:exit|status)[^\n]*0", text, re.IGNORECASE):
            self.error("BUILD_RECEIPT_MISSING", "Provenance lacks a successful dependency/build command receipt.", path)

    def _validate_workspace_markers(self) -> None:
        offenders: list[str] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                continue
            try:
                text = self._read_text(path)
            except (UnicodeDecodeError, OSError):
                continue
            if any(marker in text.casefold() for marker in PROHIBITED_WORKSPACE_MARKERS):
                offenders.append(str(path.relative_to(self.root)))
        if offenders:
            sample = ", ".join(offenders[:8])
            suffix = "" if len(offenders) <= 8 else f" (+{len(offenders) - 8} more)"
            self.error(
                "PROHIBITED_WORKSPACE_RECEIPTS",
                f"Raw evidence contains prohibited testCRUSOR workspace receipts in: {sample}{suffix}.",
            )

    def _validate_screenshots(self) -> None:
        directory = self.root / "screenshots"
        readme = directory / "README.md"
        readme_text = ""
        if readme.is_file():
            try:
                readme_text = self._read_text(readme)
            except UnicodeDecodeError as exc:
                self.error("TEXT_DECODE_ERROR", f"Screenshot README is not UTF-8: {exc}", readme)
        screenshot_digests: dict[str, str] = {}
        for filename in REQUIRED_SCREENSHOTS:
            path = directory / filename
            if not path.is_file():
                self.error("SCREENSHOT_MISSING", f"Required desktop screenshot is missing: {filename}", path)
                continue
            data = path.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                self.error("SCREENSHOT_INVALID", f"{filename} is not a valid PNG signature.", path)
                continue
            if len(data) < 33 or data[12:16] != b"IHDR":
                self.error("SCREENSHOT_INVALID", f"{filename} lacks a valid PNG IHDR chunk.", path)
            else:
                width = int.from_bytes(data[16:20], "big")
                height = int.from_bytes(data[20:24], "big")
                if width < 640 or height < 360:
                    self.error(
                        "SCREENSHOT_DIMENSIONS_TOO_SMALL",
                        f"{filename} is only {width}x{height}; it cannot show attributable desktop chrome.",
                        path,
                    )
            digest = hashlib.sha256(data).hexdigest()
            prior = screenshot_digests.get(digest)
            if prior:
                self.error(
                    "SCREENSHOT_DUPLICATE",
                    f"{filename} is byte-for-byte identical to {prior}; scenario screenshots must be fresh captures.",
                    path,
                )
            else:
                screenshot_digests[digest] = filename
            matching_lines = [line for line in readme_text.splitlines() if filename in line]
            if not matching_lines:
                self.error("SCREENSHOT_MANIFEST_MISSING", f"Screenshot README has no entry for {filename}.", readme)
            elif not any(digest.lower() in line.lower() for line in matching_lines):
                self.error("SCREENSHOT_HASH_MISMATCH", f"Screenshot README lacks the actual SHA-256 for {filename}.", readme)

    @staticmethod
    def _entry_value(entry: dict[str, Any], aliases: Iterable[str]) -> Any:
        for alias in aliases:
            value = entry.get(alias)
            if value:
                return value
        return None

    def _resolve_evidence_path(
        self,
        entry: dict[str, Any],
        aliases: Iterable[str],
        default_directory: str,
        suffix: str,
    ) -> Path | None:
        raw = self._entry_value(entry, aliases)
        if raw:
            candidate = Path(str(raw).replace("\\", "/"))
            if candidate.is_absolute():
                self.error("SESSION_PATH_ABSOLUTE", f"Session evidence path must be relative: {raw}", self.root / "sessions.json")
                candidate = Path(candidate.name)
            direct = self.root / candidate
            if direct.is_file():
                return direct
            under_default = self.root / default_directory / candidate.name
            if under_default.is_file():
                return under_default
            return direct
        session_id = str(entry.get("session_id") or entry.get("id") or "")
        if not session_id:
            return None
        matches = list((self.root / default_directory).glob(f"*{session_id}*{suffix}"))
        return matches[0] if len(matches) == 1 else self.root / default_directory / f"{session_id}{suffix}"

    def _parse_trace(self, path: Path) -> TraceData | None:
        if path in self.traces:
            return self.traces[path]
        if not path.is_file():
            return None
        rows: list[dict[str, Any]] = []
        try:
            for line_number, line in enumerate(self._read_text(path).splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    self.error("TRACE_JSONL_INVALID", f"Line {line_number} is invalid JSON: {exc}", path)
                    continue
                if not isinstance(value, dict):
                    self.error("TRACE_ROW_INVALID", f"Line {line_number} is not a JSON object.", path)
                    continue
                rows.append(value)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"Trace is not UTF-8: {exc}", path)
            return None
        if not rows:
            self.error("TRACE_EMPTY", "Trace has no JSONL rows.", path)
        indices = [row.get("step_index") for row in rows]
        if any(not isinstance(index, int) for index in indices):
            self.error("TRACE_INDEX_INVALID", "Every trace row must have an integer step_index.", path)
        else:
            typed = [int(index) for index in indices]
            if typed != sorted(typed) or len(typed) != len(set(typed)):
                self.error("TRACE_INDEX_NON_MONOTONIC", "Trace step indices are not strictly monotonic and unique.", path)
        trace = TraceData(path, rows)
        self.traces[path] = trace
        return trace

    def _load_traces_and_reports(self) -> None:
        for scenario in SESSION_SCENARIOS:
            entry = self.sessions.get(scenario)
            if not entry:
                continue
            trace_path = self._resolve_evidence_path(entry, ("trace", "trace_file", "trace_filename"), "traces", ".jsonl")
            if trace_path is None or not trace_path.is_file():
                self.error("TRACE_MISSING", f"Scenario {scenario} has no complete desktop JSONL trace.", trace_path or self.root / "traces")
            else:
                trace = self._parse_trace(trace_path)
                if trace:
                    self.scenario_traces[scenario] = trace
                    expected_id = str(entry.get("session_id") or entry.get("id") or "")
                    row_ids = {str(row.get("session_id")) for row in trace.rows if row.get("session_id")}
                    if expected_id and row_ids != {expected_id}:
                        self.error(
                            "TRACE_SESSION_MISMATCH",
                            f"Scenario {scenario} trace IDs {sorted(row_ids)} do not equal manifest ID {expected_id}.",
                            trace_path,
                        )

            report_path = self._resolve_evidence_path(
                entry,
                ("report", "report_file", "report_filename"),
                "reports",
                ".md",
            )
            matrix_result = self.matrix.get(scenario).result if self.matrix.get(scenario) else ""
            if report_path is None or not report_path.is_file():
                if matrix_result != "UNAVAILABLE":
                    self.error("REPORT_MISSING", f"Scenario {scenario} has no finalized report.", report_path or self.root / "reports")
            else:
                self.scenario_reports[scenario] = report_path
                try:
                    text = self._read_text(report_path)
                    self.report_text[scenario] = text
                except UnicodeDecodeError as exc:
                    self.error("TEXT_DECODE_ERROR", f"Scenario {scenario} report is not UTF-8: {exc}", report_path)

    @staticmethod
    def _tool_records(rows: list[dict[str, Any]]) -> list[ToolRecord]:
        records: list[ToolRecord] = []
        for row in rows:
            calls = row.get("tool_calls") or []
            if not isinstance(calls, list):
                continue
            for call in calls:
                if not isinstance(call, dict):
                    continue
                records.append(
                    ToolRecord(
                        name=str(call.get("name") or ""),
                        status=str(call.get("status") or ""),
                        args=str(call.get("args_summary") or call.get("args") or ""),
                        output=str(call.get("output_preview") or call.get("result") or call.get("error") or ""),
                        step_index=row.get("step_index") if isinstance(row.get("step_index"), int) else None,
                    )
                )
        return records

    def _scenario_segment(self, scenario: str) -> list[dict[str, Any]]:
        trace = self.scenario_traces.get(scenario)
        if not trace:
            return []
        segments = trace.finalized_segments()
        if not segments:
            return trace.rows
        if scenario == "C" and "G" in self.scenario_traces and self.scenario_traces["G"].path == trace.path:
            # C includes an initial greeting turn.  Once G is appended, C is the
            # penultimate completed turn and G is the latest completed turn.
            completed = [segment for segment in segments if segment and str(segment[-1].get("node_name", "")).lower() == "finalize"]
            if len(completed) >= 2:
                return completed[-2]
        return segments[-1]

    @staticmethod
    def _report_field(text: str, field: str) -> str | None:
        pattern = rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*([^|]+)\|"
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip().strip("`") if match else None

    def _validate_trace_report_consistency(self) -> None:
        for scenario in SESSION_SCENARIOS:
            trace = self.scenario_traces.get(scenario)
            if not trace:
                continue
            row = self.matrix.get(scenario)
            result = row.result if row else ""
            segment = self._scenario_segment(scenario)
            finalized = bool(segment and str(segment[-1].get("node_name", "")).lower() == "finalize")
            if result == "PASS" and not finalized:
                self.error(
                    "PASS_WITHOUT_FINALIZATION",
                    f"Scenario {scenario} is PASS but its latest desktop turn has no finalize row.",
                    trace.path,
                )
            if finalized:
                diagnostics = segment[-1].get("diagnostics") or []
                if not any("FINAL_VERDICT:" in str(item) for item in diagnostics):
                    self.error(
                        "FINAL_VERDICT_RECEIPT_MISSING",
                        f"Scenario {scenario} finalize row has no FINAL_VERDICT diagnostic.",
                        trace.path,
                    )

            text = self.report_text.get(scenario)
            if not text:
                continue
            report_verdict = self._report_field(text, "Task verdict")
            if result == "PASS" and report_verdict and report_verdict.lower() in {"in_progress", "pending"}:
                self.error(
                    "PASS_WITH_UNFINISHED_REPORT",
                    f"Scenario {scenario} is PASS while its report verdict is {report_verdict!r}.",
                    self.scenario_reports[scenario],
                )
            report_count = self._report_field(text, "Current-turn executed tool records")
            executed = [record for record in self._tool_records(segment) if record.status.lower() != "proposed"]
            if finalized:
                if report_count is None or report_count.upper() == "N/A":
                    self.error(
                        "REPORT_EXECUTION_COUNT_MISSING",
                        f"Scenario {scenario} finalized with {len(executed)} executions but the report count is unavailable.",
                        self.scenario_reports[scenario],
                    )
                else:
                    number = re.search(r"\d+", report_count)
                    if not number or int(number.group()) != len(executed):
                        self.error(
                            "REPORT_EXECUTION_COUNT_MISMATCH",
                            f"Scenario {scenario} report says {report_count!r}; raw current-turn trace has {len(executed)} executed tool records.",
                            self.scenario_reports[scenario],
                        )
            if "/ 100" not in text:
                self.error("REPORT_DENOMINATOR_INVALID", f"Scenario {scenario} report lacks the / 100 denominator.", self.scenario_reports[scenario])

    def _load_and_validate_sqlite(self) -> None:
        directory = self.root / "sqlite"
        runtime_path = directory / "runtime_events_extract.json"
        raw = self._load_json(runtime_path)
        if isinstance(raw, list):
            self.runtime_events = [event for event in raw if isinstance(event, dict)]
        elif raw is not None:
            self.error("SQLITE_EXTRACT_SCHEMA_INVALID", "runtime_events_extract.json must contain an event list.", runtime_path)

        for filename in ("verification_events_extract.json", "sessions_extract.json"):
            path = directory / filename
            if not path.is_file():
                self.error("SQLITE_EXTRACT_MISSING", f"Required SQLite extract is missing: {filename}", path)
            else:
                self._load_json(path)

        readme = directory / "README.md"
        if readme.is_file():
            try:
                text = self._read_text(readme)
            except UnicodeDecodeError as exc:
                self.error("TEXT_DECODE_ERROR", f"SQLite README is not UTF-8: {exc}", readme)
                text = ""
            for receipt in (".tables", "PRAGMA table_info", "SELECT seq,event_type", "SELECT id,created_at"):
                if receipt.lower() not in text.lower():
                    self.error("SQLITE_QUERY_RECEIPT_MISSING", f"SQLite README lacks required schema/query receipt: {receipt}", readme)

        intents: dict[str, tuple[int, dict[str, Any]]] = {}
        seen_results: set[str] = set()
        for event in sorted(self.runtime_events, key=lambda value: int(value.get("seq", 0) or 0)):
            event_type = str(event.get("event_type") or "")
            call_id = str(event.get("tool_call_id") or "")
            sequence = int(event.get("seq", 0) or 0)
            if event_type == "tool.intent" and call_id:
                intents[call_id] = (sequence, event)
            elif event_type == "tool.result" and call_id:
                seen_results.add(call_id)
                intent = intents.get(call_id)
                if intent is None or intent[0] >= sequence:
                    self.error(
                        "SQLITE_RESULT_WITHOUT_PRIOR_INTENT",
                        f"Runtime result {call_id} at seq {sequence} lacks an earlier matching intent.",
                        runtime_path,
                    )
        dangling = sorted(set(intents) - seen_results)
        if dangling:
            self.error(
                "SQLITE_INTENT_WITHOUT_RESULT",
                f"Runtime intents have no matching result: {', '.join(dangling[:8])}",
                runtime_path,
            )

        manifest_ids = {
            str(entry.get("session_id") or entry.get("id") or "")
            for entry in self.sessions.values()
            if entry.get("session_id") or entry.get("id")
        }
        runtime_ids = {str(event.get("session_id") or "") for event in self.runtime_events}
        missing_ids = sorted(session_id for session_id in manifest_ids if session_id not in runtime_ids)
        if missing_ids:
            self.error(
                "SQLITE_SESSION_RECEIPTS_MISSING",
                f"Runtime extract has no events for manifest sessions: {', '.join(missing_ids)}",
                runtime_path,
            )

    def _events_for(self, scenario: str) -> list[dict[str, Any]]:
        entry = self.sessions.get(scenario) or {}
        session_id = str(entry.get("session_id") or entry.get("id") or "")
        return [event for event in self.runtime_events if str(event.get("session_id") or "") == session_id]

    @staticmethod
    def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
        payload = event.get("payload")
        if isinstance(payload, dict):
            return payload
        payload_json = event.get("payload_json")
        if isinstance(payload_json, dict):
            return payload_json
        if isinstance(payload_json, str):
            try:
                parsed = json.loads(payload_json)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _runtime_tool_names(self, scenario: str, event_type: str | None = None) -> list[str]:
        names: list[str] = []
        for event in self._events_for(scenario):
            if event_type and str(event.get("event_type")) != event_type:
                continue
            payload = self._event_payload(event)
            names.append(str(payload.get("tool_name") or ""))
        return names

    def _runtime_omitted_write(
        self,
        scenario: str,
        path: str,
        expected_size: int | None = None,
    ) -> bool:
        for event in self._events_for(scenario):
            if str(event.get("event_type")) != "tool.intent":
                continue
            payload = self._event_payload(event)
            if str(payload.get("tool_name") or "").lower() != "write_file":
                continue
            args = payload.get("args")
            if not isinstance(args, dict) or str(args.get("path") or "") != path:
                continue
            content = args.get("content")
            if not isinstance(content, dict):
                continue
            if content.get("__omitted__") is not True or content.get("reason") != "tool_body":
                continue
            if expected_size is not None and int(content.get("size", -1) or -1) != expected_size:
                continue
            return True
        return False

    @staticmethod
    def _has_record(
        records: list[ToolRecord],
        names: Iterable[str],
        *,
        executed: bool = True,
        contains: str | None = None,
    ) -> bool:
        allowed = {name.lower() for name in names}
        for record in records:
            if record.name.lower() not in allowed:
                continue
            if executed and record.status.lower() == "proposed":
                continue
            haystack = f"{record.args}\n{record.output}".lower()
            if contains is None or contains.lower() in haystack:
                return True
        return False

    def _scenario_passes(self, scenario: str) -> bool:
        row = self.matrix.get(scenario)
        return bool(row and row.result == "PASS")

    def _validate_scenarios(self) -> None:
        records = {
            scenario: self._tool_records(self._scenario_segment(scenario))
            for scenario in SESSION_SCENARIOS
        }

        if self._scenario_passes("A"):
            a_terminal = [
                record for record in records.get("A", [])
                if record.name.lower() in TERMINAL_TOOLS and record.status.lower() != "proposed"
            ]
            if len(a_terminal) != 1 or "exit code: 0" not in a_terminal[0].output.lower():
                self.error("SCENARIO_A_RECEIPT_INVALID", "A requires exactly one executed terminal receipt with exit code 0.", self.scenario_traces.get("A", TraceData(self.root, [])).path)

        if self._scenario_passes("B"):
            b_records = records.get("B", [])
            if not self._has_record(b_records, ("check_target_toolchains",)):
                self.error("SCENARIO_B_TOOL_MISSING", "B has no executed check_target_toolchains receipt.")
            b_forbidden = [record.name for record in b_records if record.status.lower() != "proposed" and record.name.lower() in MUTATION_TOOLS]
            if b_forbidden:
                self.error("SCENARIO_B_FORBIDDEN_MUTATION", f"B executed forbidden mutation/install tools: {b_forbidden}")

        if self._scenario_passes("C"):
            c_records = records.get("C", [])
            if not self._has_record(c_records, ("write_file",), contains="scratch/interest_probe.py"):
                self.error("SCENARIO_C_WRITE_MISSING", "C has no successful write_file execution receipt for scratch/interest_probe.py.")
            elif not self._runtime_omitted_write("C", "scratch/interest_probe.py"):
                self.error("SCENARIO_C_OMISSION_MISSING", "C's persisted write intent lacks typed tool-body omission metadata.", self.root / "sqlite/runtime_events_extract.json")
            if not any(
                record.name.lower() in TERMINAL_TOOLS
                and record.status.lower() != "proposed"
                and "interest-ok" in record.output
                for record in c_records
            ):
                self.error("SCENARIO_C_RUN_MISSING", "C has no terminal execution receipt showing interest-ok output.")
            c_runtime = self._runtime_tool_names("C", "tool.result")
            if c_runtime and "write_file" not in {name.lower() for name in c_runtime}:
                self.error("SCENARIO_C_NARRATIVE_CONTRADICTION", "C narrative claims creation, but SQLite results contain no write_file execution.", self.root / "sqlite/runtime_events_extract.json")

        if self._scenario_passes("D"):
            d_terminal = [
                record for record in records.get("D", [])
                if record.name.lower() in TERMINAL_TOOLS and record.status.lower() != "proposed"
            ]
            if len(d_terminal) != 1 or "exit code: 3" not in d_terminal[0].output.lower() or "failure-probe" not in d_terminal[0].output:
                self.error("SCENARIO_D_RECEIPT_INVALID", "D requires one terminal execution containing failure-probe and exit code 3.")

        if self._scenario_passes("E") and not self._has_record(records.get("E", []), ("verify_target_app",)):
            self.error("SCENARIO_E_EXECUTION_MISSING", "E has no actual verify_target_app execution receipt.")

        if self._scenario_passes("F"):
            f_records = records.get("F", [])
            if not self._has_record(f_records, ("write_file",), contains="scratch/cleanup_probe.py"):
                self.error("SCENARIO_F_WRITE_MISSING", "F has no successful write receipt for scratch/cleanup_probe.py.")
            elif not self._runtime_omitted_write("F", "scratch/cleanup_probe.py"):
                self.error("SCENARIO_F_OMISSION_MISSING", "F's persisted write intent lacks typed tool-body omission metadata.", self.root / "sqlite/runtime_events_extract.json")
            if not any(
                record.name.lower() in TERMINAL_TOOLS
                and record.status.lower() != "proposed"
                and "cleanup-ok" in record.output
                and "exit code: 0" in record.output.lower()
                for record in f_records
            ):
                self.error("SCENARIO_F_RUN_MISSING", "F has no successful terminal receipt printing cleanup-ok.")
            cleanup_terms = ("remove-item", "unlink", "rm ", "del ", "delete")
            if not any(
                record.name.lower() in TERMINAL_TOOLS
                and record.status.lower() != "proposed"
                and "cleanup_probe.py" in f"{record.args} {record.output}".lower()
                and any(term in f"{record.args} {record.output}".lower() for term in cleanup_terms)
                for record in f_records
            ):
                self.error("SCENARIO_F_CLEANUP_MISSING", "F has no executed cleanup receipt for cleanup_probe.py.")
            for event in self._events_for("F"):
                if str(event.get("event_type")) != "tool.result":
                    continue
                payload = self._event_payload(event)
                payload_text = json.dumps(payload, sort_keys=True).lower()
                if "cancel" in payload_text:
                    self.error("SCENARIO_F_EXECUTION_CANCELLED", "F's persisted terminal result was cancelled, not successfully run and cleaned up.", self.root / "sqlite/runtime_events_extract.json")
                    break
            f_trace = self.scenario_traces.get("F")
            if f_trace and (not f_trace.rows or str(f_trace.rows[-1].get("node_name", "")).lower() != "finalize"):
                self.error("SCENARIO_F_NOT_FINALIZED", "F stopped before a finalize row and cannot be accepted as PASS.", f_trace.path)

        if self._scenario_passes("G"):
            g_records = records.get("G", [])
            if not self._has_record(g_records, ("read_file",), contains="scratch/interest_probe.py"):
                self.error("SCENARIO_G_READ_MISSING", "G has no resumed read_file execution for scratch/interest_probe.py.")
            elif not any(
                record.name.lower() == "read_file"
                and record.status.lower() != "proposed"
                and 'print("interest-ok")' in record.output
                for record in g_records
            ):
                self.error("SCENARIO_G_OUTPUT_MISSING", "G's read receipt does not preserve the expected first line.")
            g_mutations = [
                record.name for record in g_records
                if record.status.lower() != "proposed" and record.name.lower() in MUTATION_TOOLS
            ]
            if g_mutations:
                self.error("SCENARIO_G_FORBIDDEN_MUTATION", f"G executed mutation tools: {g_mutations}")
            self._validate_g_restart()

        if self._scenario_passes("I"):
            i_records = records.get("I", [])
            if not self._has_record(i_records, ("write_file",), contains="scratch/credential_probe.txt"):
                self.error("SCENARIO_I_WRITE_MISSING", "I has no successful write receipt for credential_probe.txt.")
            elif not self._runtime_omitted_write("I", "scratch/credential_probe.txt", expected_size=58):
                self.error("SCENARIO_I_OMISSION_MISSING", "I's persisted write intent lacks 58-byte typed tool-body omission metadata.", self.root / "sqlite/runtime_events_extract.json")
            if not any(
                record.name.lower() in TERMINAL_TOOLS
                and record.status.lower() != "proposed"
                and "credential_probe.txt" in f"{record.args} {record.output}".lower()
                and any(term in f"{record.args} {record.output}".lower() for term in ("remove-item", "unlink", "rm ", "del ", "delete"))
                for record in i_records
            ):
                self.error("SCENARIO_I_CLEANUP_MISSING", "I has no executed cleanup receipt for credential_probe.txt.")

    def _validate_g_restart(self) -> None:
        before = self.root / "logs/G-before-restart.txt"
        after = self.root / "logs/G-after-restart.txt"
        if not before.is_file() or not after.is_file():
            return
        try:
            before_text = self._read_text(before)
            after_text = self._read_text(after)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"G restart log is not UTF-8: {exc}", before if before.is_file() else after)
            return
        required_before = ("trace line count", "maximum step index", "report step count", "trace prefix sha-256", "process")
        required_after = ("trace line count", "maximum step index", "report step count", "trace prefix sha-256", "process")
        for label in required_before:
            if label not in before_text.lower():
                self.error("G_RESTART_RECEIPT_INCOMPLETE", f"G-before-restart lacks {label!r} receipt.", before)
        for label in required_after:
            if label not in after_text.lower():
                self.error("G_RESTART_RECEIPT_INCOMPLETE", f"G-after-restart lacks {label!r} receipt.", after)

        def integer_receipt(text: str, label: str) -> int | None:
            match = re.search(rf"{re.escape(label)}\s*:\s*(\d+)", text, re.IGNORECASE)
            return int(match.group(1)) if match else None

        def hash_receipt(text: str) -> str | None:
            match = re.search(r"Trace prefix SHA-256\s*:\s*([0-9a-f]{64})", text, re.IGNORECASE)
            return match.group(1).lower() if match else None

        before_lines = integer_receipt(before_text, "Trace line count")
        after_lines = integer_receipt(after_text, "Trace line count")
        before_index = integer_receipt(before_text, "Maximum step index")
        after_index = integer_receipt(after_text, "Maximum step index")
        before_report = integer_receipt(before_text, "Report step count")
        after_report = integer_receipt(after_text, "Report step count")
        before_hash = hash_receipt(before_text)
        after_hash = hash_receipt(after_text)

        for label, older, newer in (
            ("trace line count", before_lines, after_lines),
            ("maximum step index", before_index, after_index),
            ("report step count", before_report, after_report),
        ):
            if older is not None and newer is not None and newer <= older:
                self.error("G_RESTART_DID_NOT_ADVANCE", f"G {label} did not advance after resume ({older} -> {newer}).", after)
        if before_hash and after_hash and before_hash != after_hash:
            self.error("G_TRACE_PREFIX_HASH_MISMATCH", "G before/after trace prefix hashes differ.", after)

        trace = self.scenario_traces.get("G")
        if trace and before_lines is not None and after_lines is not None:
            raw_lines = trace.path.read_bytes().splitlines(keepends=True)
            if after_lines != len(raw_lines):
                self.error(
                    "G_TRACE_COUNT_MISMATCH",
                    f"G-after reports {after_lines} trace lines, but committed JSONL has {len(raw_lines)}.",
                    after,
                )
            if before_lines > len(raw_lines):
                self.error("G_TRACE_COUNT_MISMATCH", "G-before line count exceeds the committed post-resume trace.", before)
            elif before_hash:
                actual_prefix_hash = hashlib.sha256(b"".join(raw_lines[:before_lines])).hexdigest()
                if before_hash != actual_prefix_hash:
                    self.error(
                        "G_TRACE_PREFIX_HASH_MISMATCH",
                        "Recorded G prefix hash does not match the original-line prefix in the committed trace.",
                        before,
                    )
        if re.search(r"(?:pytest|unit test|terminal hydration|synthetic session)", before_text + after_text, re.IGNORECASE):
            self.error("SYNTHETIC_DESKTOP_SUBSTITUTE", "G restart receipts describe a terminal/unit substitute, not an actual desktop restart.", before)

    def _parse_markdown_rows(self, text: str) -> dict[str, list[str]]:
        rows: dict[str, list[str]] = {}
        for line in text.splitlines():
            if not re.match(r"^\|\s*[A-I]\s*\|", line):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells:
                rows[cells[0].upper()] = cells
        return rows

    def _validate_h_audit(self) -> None:
        path = self.root / "reports/H-report-audit.md"
        if not path.is_file():
            return
        try:
            text = self._read_text(path)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"H audit is not UTF-8: {exc}", path)
            return
        rows = self._parse_markdown_rows(text)
        for scenario in tuple("ABCDEFGI"):
            if scenario not in rows:
                self.error("H_AUDIT_SCENARIO_MISSING", f"H audit has no row for scenario {scenario}.", path)
        header_line = next((line for line in text.splitlines() if line.startswith("|") and "scenario" in line.lower()), "")
        header = header_line.lower()
        header_cells = [cell.strip().lower() for cell in header_line.strip().strip("|").split("|")] if header_line else []
        required_columns = (
            "sha-256",
            "executed",
            "finalization",
            "measured",
            "runtime dimensions",
            "cache numerator",
            "cache denominator",
            "cache display",
            "cache treatment",
        )
        for column in required_columns:
            if column not in header:
                self.error("H_AUDIT_COLUMN_MISSING", f"H audit lacks required column {column!r}.", path)
        if "all finalized reports" in text.lower() and "in_progress" in text:
            self.error("H_AUDIT_FINALIZATION_CONTRADICTION", "H calls reports finalized while listing an in_progress verdict.", path)

        sha_index = next((index for index, cell in enumerate(header_cells) if "sha-256" in cell), None)
        executed_index = next((index for index, cell in enumerate(header_cells) if "executed" in cell), None)
        cache_indices = [index for index, cell in enumerate(header_cells) if "cache" in cell]
        for scenario, report in self.report_text.items():
            audit_cells = rows.get(scenario)
            if not audit_cells:
                continue
            if sha_index is not None:
                actual_sha = hashlib.sha256(report.encode("utf-8")).hexdigest()
                recorded_sha = audit_cells[sha_index].strip().strip("`") if sha_index < len(audit_cells) else ""
                if recorded_sha.lower() != actual_sha:
                    self.error(
                        "H_REPORT_HASH_MISMATCH",
                        f"H report SHA-256 for {scenario} does not match {self.scenario_reports[scenario].name}.",
                        path,
                    )
            cache_match = re.search(r"Prompt Cache Hit Rate\*\*\s*\|\s*\*\*(N/A|[0-9.]+%)", report, re.IGNORECASE)
            audit_cache = " | ".join(
                audit_cells[index].lower()
                for index in cache_indices
                if index < len(audit_cells)
            )
            if cache_match and cache_match.group(1).upper() != "N/A" and "n/a" in audit_cache:
                self.error(
                    "H_CACHE_CONTRADICTION",
                    f"H labels {scenario} cache N/A while its report contains numeric cache telemetry {cache_match.group(1)}.",
                    path,
                )
            report_count = self._report_field(report, "Current-turn executed tool records")
            numeric_audit: int | None = None
            if executed_index is not None and executed_index < len(audit_cells):
                executed_match = re.fullmatch(r"\d+", audit_cells[executed_index])
                if executed_match:
                    numeric_audit = int(executed_match.group())
            if report_count and report_count.upper() != "N/A" and numeric_audit is not None:
                report_number = re.search(r"\d+", report_count)
                if report_number and int(report_number.group()) != numeric_audit:
                    self.error(
                        "H_REPORT_COUNT_CONTRADICTION",
                        f"H records {numeric_audit} executed tools for {scenario}, but the report renders {report_count}.",
                        path,
                    )

    def _validate_omission_marker(self) -> None:
        path = self.root / "logs/I-marker-hash.txt"
        if not path.is_file():
            return
        try:
            text = self._read_text(path)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"I marker log is not UTF-8: {exc}", path)
            return
        nonce_match = re.search(r"agent-core-omission-[0-9a-f]{32}", text)
        hash_match = re.search(r"Marker SHA-256:\s*([0-9a-f]{64})", text, re.IGNORECASE)
        length_match = re.search(r"Marker byte length:\s*(\d+)", text, re.IGNORECASE)
        if not nonce_match or not hash_match or not length_match:
            self.error("I_MARKER_RECEIPT_INVALID", "I marker log lacks nonce, byte length, or marker SHA-256.", path)
            return
        nonce = nonce_match.group(0)
        marker = "SYNTHETIC_ONLY_DO_NOT_USE_" + hashlib.sha256(nonce.encode("utf-8")).hexdigest()[:32]
        marker_bytes = marker.encode("utf-8")
        expected_hash = hashlib.sha256(marker_bytes).hexdigest()
        if int(length_match.group(1)) != len(marker_bytes):
            self.error("I_MARKER_LENGTH_MISMATCH", "I marker byte-length receipt does not match deterministic derivation.", path)
        if hash_match.group(1).lower() != expected_hash:
            self.error("I_MARKER_HASH_MISMATCH", "I marker hash receipt does not match deterministic derivation.", path)
        leaked: list[str] = []
        for candidate in self.root.rglob("*"):
            if candidate.is_file():
                try:
                    if marker_bytes in candidate.read_bytes():
                        leaked.append(str(candidate.relative_to(self.root)))
                except OSError:
                    continue
        if leaked:
            self.error("I_RAW_MARKER_LEAK", f"Derived raw marker appears in committed evidence: {', '.join(leaked)}")

    def _validate_engine_log(self) -> None:
        path = self.root / "logs/engine-complete.log"
        if not path.is_file():
            return
        try:
            text = self._read_text(path)
        except UnicodeDecodeError as exc:
            self.error("TEXT_DECODE_ERROR", f"Engine log is not UTF-8: {exc}", path)
            return
        if len(text.splitlines()) < 30:
            self.error("ENGINE_LOG_INCOMPLETE", "Engine log is too short to be the required unabridged two-interval log.", path)
        for expected, label in (
            (EXPECTED_IMPLEMENTATION, "implementation identity"),
            (EXPECTED_RENDERER_STAMP, "renderer stamp"),
            (EXPECTED_SOURCES_HASH, "renderer source hash"),
        ):
            occurrences = text.count(expected)
            if occurrences == 0:
                self.error("ENGINE_IDENTITY_MISSING", f"Engine log lacks expected {label}: {expected}", path)
            elif occurrences < 2:
                self.error(
                    "ENGINE_IDENTITY_INTERVALS_INCOMPLETE",
                    f"Engine log shows {label} in only one launch interval.",
                    path,
                )
        start_markers = len(re.findall(r"(?:engine|backend|workbench).{0,40}(?:start|launch|ready)", text, re.IGNORECASE))
        if start_markers < 2:
            self.error("G_RELAUNCH_NOT_PROVEN", "Engine log does not expose two distinct launch/start intervals for G.", path)

    def _validate_synthetic_substitutes(self) -> None:
        for scenario in ("G", "I"):
            row = self.matrix.get(scenario)
            if not row or row.result != "PASS":
                continue
            lowered = row.raw.lower()
            if any(marker in lowered for marker in ("terminal hydration", "terminal omission", "unit test", "src/tests", "pytest")):
                self.error(
                    "SYNTHETIC_DESKTOP_SUBSTITUTE",
                    f"Scenario {scenario} is marked PASS using terminal/unit evidence instead of a desktop session.",
                    self.root / "RESULTS.md",
                )


def validate_evidence(root: Path | str) -> ValidationResult:
    return EvidenceValidator(root).validate()


def _format_summary(result: ValidationResult) -> str:
    verdict = "VALID" if result.valid else "INVALID"
    lines = [
        f"Agent Core desktop evidence: {verdict}",
        f"Root: {result.root}",
        f"Errors: {len(result.errors)}; warnings: {len(result.warnings)}",
    ]
    for issue in result.issues:
        location = f" ({issue.path})" if issue.path else ""
        lines.append(f"[{issue.severity.upper()}] {issue.code}{location}: {issue.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "evidence_root",
        nargs="?",
        default="diagnostics/desktop-evidence/agent-core-b22d6efc",
        help="Path to the desktop evidence package.",
    )
    parser.add_argument("--json-out", type=Path, help="Write the complete machine-readable result to this path.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the human-readable result.")
    args = parser.parse_args(argv)

    result = validate_evidence(args.evidence_root)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        print(_format_summary(result))
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
